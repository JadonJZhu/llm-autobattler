# CLAUDE.md — Interactive Puzzle-Solving Project

## Project Overview

A 4x3 autochess game built in Godot where an LLM (Claude Sonnet 4.6) competes against a human player. Both players spend gold to buy and place units during a **Prep phase**, then watch units fight automatically in a **Battle phase**. The LLM receives a full game replay of the previous match to inform its next prep decisions.

The project also supports a **Puzzle-Based Ablation Mode**: the opponent follows a scripted sequence of placements, and the LLM is evaluated across all prompt configurations (`instructions`, `examples`, `reflection`) by how many attempts it needs to solve each puzzle.

- **Grid**: 4 rows × 3 columns. LLM occupies rows 0–1 (top); Human occupies rows 2–3 (bottom).
- **Prep**: Players alternate placing units from a randomized shop (3 gold to start). LLM always goes first.
- **Battle**: Deterministic. Units activate by priority (A > B > C > D, then placement order). Units advance toward the opponent's edge and escape for 1 point each.
- **Win condition**: Score = units remaining on board + units escaped. Higher score wins.

## Code Principles

### SOLID
- **Single Responsibility**: Each script handles one concern. Do not combine unrelated logic.
- **Open/Closed**: Design systems to be extensible without modifying existing code. Use signals and composition over deep inheritance. New unit types or board layouts should not require rewriting core game logic.
- **Liskov Substitution**: If using inheritance, subtypes must be fully substitutable for their base type without breaking behavior.
- **Interface Segregation**: Keep node interfaces small and focused. A unit node should not expose logging methods. A UI node should not know about API payloads.
- **Dependency Inversion**: High-level modules (turn manager, game board) should depend on abstractions, not concrete implementations. Pass dependencies via signals, exported variables, or node references — not hardcoded paths.

### General Code Quality
- Prefer composition over inheritance. Use Godot's node tree and signals as the primary coupling mechanism.
- Keep functions short and focused. If a function does more than one thing, split it.
- Name variables and functions clearly. Avoid abbreviations. `unit_owner` over `own`.
- No magic numbers. Use `GridConstants` or exported variables for configurable values.
- Handle errors explicitly. API calls, file I/O, and JSON parsing must have error handling. Do not silently swallow failures.
- Write GDScript that follows Godot's official style guide (snake_case, typed variables where possible).

## Key File Structure

```
godot/
  project.godot
  api_key.txt              — Claude API key (not committed); read by LlmClient at startup
  scenes/
    game_board.tscn        — Root scene; contains GameBoard, TurnManager, UI nodes
  scripts/
    game_controller.gd     — Root Node2D. Wires all subsystems; owns game/restart flow
    turn_manager.gd        — Prep/battle phase orchestration, win condition, autoplay timer
    game_board.gd          — 4x3 grid: unit placement, removal, move, snapshot, cell_clicked signal
    board_ui.gd            — Cell button creation and visual styling; re-emits cell_clicked
    unit.gd                — Unit visual node (Panel + Label). Pure view — no game logic
    unit_data.gd           — Shared enums (UnitType, Owner), costs, colors (class UnitData)
    shop.gd                — Per-player gold + available unit types; purchase logic
    shop_ui.gd             — Shop buttons, gold labels, status/turn labels, thinking animation
    main_ui.gd             — Autoplay toggle button + manual-step hint label
    instructions_menu.gd   — Full-screen help overlay (Esc key or ? button)
    battle_engine.gd       — Pure battle logic; operates on BattleSnapshot, never holds Nodes
    battle_snapshot.gd     — Mutable snapshot of live battle state (units dict + escaped counts)
    board_serializer.gd    — Board state → ASCII text grid for LLM prompt and logging
    llm_http_base.gd       — Shared HTTP base class for Claude API communication
    llm_client.gd          — Autoload singleton (extends LlmHttpBase). LLM player API requests
    llm_prompt_builder.gd  — Builds system prompt and user message for LLM prep turn
    llm_response_parser.gd — Parses "PLACE: <type> (row, col)" from LLM response text
    llm_fallback.gd        — Random valid placement when LLM fails or API key is absent
    llm_mode_config.gd     — Pure data class for LLM mode toggles (instructions, examples, reflection)
    reflection_client.gd   — Requests strategic reflection feedback from Claude API
    game_logger.gd         — Autoload singleton. JSON logging to user://game_logs/; replay data
    puzzle_scenario.gd     — Data model for a scripted puzzle definition
    puzzle_loader.gd       — Loads puzzle scenarios from JSON
    puzzle_runner.gd       — Runs one puzzle across multiple attempts for a mode config
    ablation_runner.gd     — Iterates all 8 mode configs across puzzle scenarios
    puzzle_logger.gd       — Persists puzzle ablation outputs to JSON
    grid_constants.gd      — ROWS=4, COLS=3, LLM_ROWS=[0,1], HUMAN_ROWS=[2,3]
    style_utils.gd         — StyleBoxFlat factory helper (bg, border, corner radius)
  puzzles/
    puzzle_suite.json      — Scripted puzzle set for ablation experiments
```

### Autoloads
- `LlmClient` — global singleton; connects signals to `GameController`
- `GameLogger` — global singleton; accessed directly by `TurnManager` and `GameController`

## Unit Types

| Type | Cost | Behavior |
|------|------|----------|
| A | 1g | Attacks enemy directly ahead; advances if clear |
| B | 1g | Attacks enemy diagonally left-ahead; advances if clear (or on leftmost col) |
| C | 1g | Attacks enemy diagonally right-ahead; advances if clear (or on rightmost col) |
| D | 2g | Ranged: removes closest enemy by Manhattan distance (tie-break: left-to-right, top-to-bottom) |

- LLM units face **down** (increasing row). Human units face **up** (decreasing row).
- Priority order within a turn: A → B → C → D, then by `placement_order` (earlier = higher priority).
- A unit that would advance off the board **escapes** and contributes 1 to its owner's score.

## When to Stop and Defer to the Human Engineer

**If a task requires any of the following, stop and describe what the human should do instead of attempting it yourself:**

- Manually positioning, scaling, or configuring nodes in the Godot editor Inspector panel
- Creating or editing `.tscn` scene files by hand (the serialization format is fragile and editor-managed)
- Importing, configuring, or assigning assets (textures, sprites, fonts, audio) through the Godot import system
- Setting up AnimationPlayer keyframes, Tween configurations, or visual shader graphs
- Adjusting physics layers, collision shapes, or navigation meshes in the editor
- Configuring project settings that require the Godot GUI (input map, display settings, autoloads) — unless the exact `project.godot` text format is known and straightforward
- Any task where the Godot editor's visual tools are the correct and less error-prone workflow

**Format for deferring:** Clearly state what needs to be done, which nodes/scenes are involved, and what properties to set. Provide step-by-step instructions the human can follow in the editor.

## LLM Integration Notes

- API target: Claude Sonnet 4.6 (`claude-sonnet-4-6`) only
- `LlmClient` is an autoload singleton using Godot's `HTTPRequest` node
- API key is read from `res://api_key.txt` at startup; if absent, `LlmFallback` is used instead
- The LLM prompt includes: current board state (ASCII grid), shop contents + gold, turn number, and the full previous game replay (prep placements + battle trace + outcome)
- Response format expected: `PLACE: <type> (row, col)` as the last non-empty line
- Parsed by `LlmResponseParser`; on failure, `LlmFallback` picks a random valid placement
- No extended thinking / chain-of-thought extraction currently implemented

## Puzzle Ablation Notes

- `GameController.start_ablation(max_attempts_per_puzzle, puzzle_path)` starts an end-to-end run.
- Puzzles are loaded from `res://puzzles/puzzle_suite.json` by `PuzzleLoader`.
- Each puzzle defines fixed LLM shop, fixed opponent shop, and a turn-by-turn scripted opponent placement sequence.
- During puzzle mode, the opponent turn is not human input or a second LLM; it is consumed from the scripted queue.
- `AblationRunner` evaluates all 8 `LlmModeConfig` combinations (`I{0,1}_E{0,1}_R{0,1}`) across all puzzles.
- Results are written by `PuzzleLogger` to `user://game_logs/ablation_<timestamp>.json`.

## Conventions

- Godot version: 4.x
- Language: GDScript
- Signals over direct method calls for cross-node communication
- Use `@export` for inspector-configurable values
- Use typed variables (`var score: int = 0`) wherever possible
- Group related constants at the top of each script
- One script per file, one primary responsibility per script
- Pure data/logic classes extend `RefCounted` (e.g., `Shop`, `BattleEngine`, `BattleSnapshot`, `UnitData`)
- Scene-aware classes extend `Node`, `Node2D`, or `Control` as appropriate
