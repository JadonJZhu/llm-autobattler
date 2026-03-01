# Technical Plan

## Game Mechanics

### Board Layout
- **Grid**: 6x6 grid (36 cells). Each cell is 64px with 72px spacing between tile centers, offset from the top-left by `(100, 60)`.
- **Tile types** (`Tile.TileType`):
  - `ARROW` — Directional tile with one of four orientations (UP `^`, RIGHT `>`, DOWN `v`, LEFT `<`). These are the interactive tiles.
  - `DESTINATION_X` — Path start marker, displayed as "X" (green background). Placed randomly in the top-left 3x3 area (cols 0–2, rows 0–2).
  - `DESTINATION_Y` — Path end marker, displayed as "Y" (amber background). Placed randomly in the bottom-right 3x3 area (cols 3–5, rows 3–5).
  - `EMPTY` — Inactive cell (dark background, no interaction). Any grid cell not on the generated path and not a destination becomes empty.
- **Locked state**: Any arrow tile can be locked. Locked tiles show a red 12px indicator in the top-right corner and change to a reddish background. Locked tiles cannot be flipped by the human player but _can_ be toggled (locked/unlocked) by the LLM.

### Board Generation (`GameBoard.create_simple_board_data`)
1. Place `DESTINATION_X` at a random position in the top-left 3x3 region.
2. Place `DESTINATION_Y` at a random position in the bottom-right 3x3 region.
3. Build a stochastic path from X to Y by randomly stepping **right** or **down** at each step (never left or up), guaranteeing a monotonic path.
4. Each path cell (excluding X and Y themselves) becomes an `ARROW` tile. The **correct direction** for each arrow points toward the next cell in the path (RIGHT if the next cell is to the right, DOWN if below).
5. The **initial direction** of each arrow is randomized along the same axis as its correct direction — so a tile whose solution is RIGHT starts as either RIGHT or LEFT; a tile whose solution is DOWN starts as either UP or DOWN. This means a flip always toggles between the correct and incorrect orientation on the relevant axis.
6. All other cells are `EMPTY`.

### Hidden Rule
- The solution is a directed path of arrows from X to Y. The LLM is **never told** this objective.
- The LLM receives only an opaque **correctness score**: the count of arrow tiles currently matching their correct orientation (`Tile.is_correct()` — compares `direction` against `correct_direction`).
- **Maximum correctness** = total number of arrow tiles on the board. Achieving this means every arrow points correctly along the path.

### Flipping Mechanic
- Flipping an arrow tile toggles it to its **opposite** direction along its axis:
  - UP ↔ DOWN
  - LEFT ↔ RIGHT
- Flipping is only allowed on `ARROW` tiles that are not locked.
- Because initial directions are randomized on the correct axis, every arrow is always either correct or one flip away from correct.

### Turn Structure
Each round consists of an **LLM turn** (two sub-phases) followed by a **Human turn**:

1. **LLM Turn — Flip** (`TurnPhase.LLM_FLIP`): The LLM selects one unlocked arrow tile to flip. The tile's direction toggles to its opposite. Score is recalculated.
2. **LLM Turn — Lock** (`TurnPhase.LLM_LOCK`): The LLM selects one arrow tile (any, including the one just flipped) to **toggle its lock state** (locked → unlocked, or unlocked → locked). The lock target cannot be the same tile that was flipped (enforced in the random simulation; the real LLM integration should maintain this). Win condition is checked after locking.
3. **Human Turn** (`TurnPhase.HUMAN`): The human clicks one unlocked arrow tile to flip it. Locked tiles, destinations, and empty tiles are unclickable. Score is recalculated and win condition checked. Then the next LLM turn begins.

### Win Condition
- After each move (LLM lock or human flip), the game checks if `correctness_score >= max_correctness_score`.
- If met, the game transitions to `TurnPhase.GAME_OVER`, emits `game_won`, logs the result, and saves the log file.
- The winner is always labeled "llm" — the LLM wins by achieving a perfect score; the human's goal is to delay or prevent this.

### Input to LLM
- **Text grid**: A table serialized by `BoardSerializer` with column headers (0–5), row labels (0–5), and pipe-separated cells. Each cell shows:
  - `X` / `Y` for destinations
  - `^`, `>`, `v`, `<` for arrow directions
  - Suffix `L` on arrows that are locked (e.g., `>L`)
  - `.` for empty cells
- **Correctness score**: integer score + max score
- **Turn history**: maintained by the game logger

### Current Phase 1 LLM Simulation
In Phase 1, the LLM turn is simulated with random moves (`game_controller.gd`):
- Flip target: a random unlocked arrow tile.
- Lock target: a random arrow tile (excluding the flip target). Lock is _toggled_, not always set — so it can also unlock a previously locked tile.
- The serialized board state is printed to console after each LLM turn for debugging.

## Architecture

### Godot (Frontend + Game Logic)
- **GameBoard** (`game_board.gd`): Owns the 6x6 `tiles` dictionary (`Vector2i → Tile`). Handles board initialization from generated data, tile creation/layout, flip and lock operations, and correctness scoring. Emits `tile_clicked` and `board_ready` signals.
- **Tile** (`tile.gd`): Individual tile node. Builds its own visuals programmatically (ColorRect background, Label for arrow/destination text, ColorRect lock indicator, invisible Button for click detection). Handles flip logic (axis-based toggle), locked state, and serialization to a text label.
- **TurnManager** (`turn_manager.gd`): State machine with four phases (`LLM_FLIP`, `LLM_LOCK`, `HUMAN`, `GAME_OVER`). Enforces phase transitions, delegates flip/lock to GameBoard, checks win condition, and emits signals for UI updates.
- **GameController** (`game_controller.gd`): Root scene controller. Wires GameBoard, TurnManager, and UI labels together. Currently simulates LLM turns with random moves (Phase 1). Will be replaced with real API calls in Phase 2.
- **BoardSerializer** (`board_serializer.gd`): Static utility (`RefCounted`) that converts the board into a pipe-delimited text table with column/row headers for LLM consumption.
- **GameLogger** (`game_logger.gd`): Autoloaded singleton. Logs each turn (LLM and human), game results, and saves to `user://game_logs/` as timestamped JSON files.
- UI: Score label, turn phase label, and status label — updated via signals from TurnManager.

### LLM Integration (API Layer)
- HTTP requests from Godot to Claude API (Claude Opus 4.6 only)
- Structured prompt with: text grid state, correctness score, turn history, game rules (mechanics only, not the hidden path objective)
- Parse LLM response for two coordinate pairs
- Capture and display chain-of-thought / reasoning tokens

### Logging
- Log all turns: LLM reasoning, moves made, correctness score, lock usage
- JSON export for later analysis

## Implementation Phases

### Phase 1: Core Game (Godot)
- Grid rendering, arrow tiles, X/Y tiles
- Click-to-flip mechanic
- Turn alternation logic
- Board state serialization to text
- Correctness scoring

### Phase 2: LLM Integration
- Claude Opus 4.6 API integration via HTTPRequest
- Prompt engineering for the game context
- Response parsing for coordinate pairs
- Turn loop: serialize state → query LLM → apply moves → human turn

### Phase 3: UI & Polish
- LLM thinking/reasoning display panel
- Chat interface for human-LLM communication
- Lock indicators, turn indicators, correctness display
- Visual path highlighting when solved

### Phase 4: Logging
- JSON turn logging

## Verification
- Manually play through a game to verify turn logic and correctness scoring
- Verify LLM receives accurate text grid representations
- Run baseline (no adversary) to confirm LLM can solve simple boards
- Check that locking mechanics work correctly
- Validate logging captures turn data correctly

## Key Files
- `godot/project.godot` — Godot project config
- `godot/scenes/game_board.tscn` — Main game scene (GameController root + GameBoard + TurnManager + UI nodes)
- `godot/scripts/game_board.gd` — Grid state, tile management, correctness scoring, board generation
- `godot/scripts/tile.gd` — Tile behavior: type, direction, lock state, visuals, flip logic, serialization
- `godot/scripts/turn_manager.gd` — Turn phase state machine, win condition checking
- `godot/scripts/game_controller.gd` — Root scene wiring, LLM turn simulation (Phase 1)
- `godot/scripts/board_serializer.gd` — Board state → text table for LLM
- `godot/scripts/game_logger.gd` — Autoloaded singleton for JSON turn logging
- `godot/scripts/llm_client.gd` — Claude API integration (Phase 2, not yet implemented)
- `godot/scripts/ui_controller.gd` — Thinking panel, chat interface (Phase 3, not yet implemented)
- `CLAUDE.md` — Project conventions and context
