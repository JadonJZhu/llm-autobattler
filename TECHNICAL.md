# TECHNICAL.md — Interactive Puzzle-Solving Project

## Gameplay Rules

- **Grid**: 4 rows × 3 columns. LLM occupies rows 0–1 (top); Human occupies rows 2–3 (bottom).
- **Prep**: Players alternate placing units from a randomized shop (3 gold to start). LLM always goes first.
- **Battle**: Deterministic. Units activate by priority (A > B > C > D, then placement order). Units advance toward the opponent's edge and escape for 1 point each.
- **Win condition**: Score = units remaining on board + units escaped. Higher score wins.


## Key File Structure

```
godot/
  project.godot
  .env                     — Environment variables (LLM_API_KEY, endpoint/model/format, optional GODOT_PATH)
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
    llm_http_base.gd       — Shared HTTP base class; anthropic and openai request formats
    llm_client.gd          — Autoload singleton (extends LlmHttpBase). LLM player API requests
    llm_prompt_builder.gd  — Builds system prompt and user message for LLM prep turn
    llm_response_parser.gd — Parses "PLACE: <type> (row, col)" from LLM response text
    llm_fallback.gd        — Random valid placement when LLM fails or API key is absent
    llm_mode_config.gd     — Pure data class for LLM mode toggles (instructions, examples, reflection)
    reflection_client.gd   — Requests strategic reflection feedback from the LLM API
    game_logger.gd         — Autoload singleton. JSON logs to user://game_logs/; replay history, the
                             placement look-back window, and the model and attempt identity stamped
                             on every entry
    puzzle_scenario.gd     — Data model for a scripted puzzle definition
    puzzle_loader.gd       — Loads puzzle scenarios from JSON
    puzzle_runner.gd       — Runs one puzzle across multiple attempts for a mode config
    ablation_runner.gd     — Iterates all 8 mode configs across puzzle scenarios
    puzzle_logger.gd       — Persists puzzle ablation outputs to JSON
    grid_constants.gd      — ROWS=4, COLS=3, LLM_ROWS=[0,1], HUMAN_ROWS=[2,3]
    style_utils.gd         — StyleBoxFlat factory helper (bg, border, corner radius)
  puzzles/
    puzzle_suite.json      — Shipped scripted puzzle set; the default for ablation runs
    pilot_suite.json       — Generated suites, chosen with --puzzle-path
    lowtail_suite.json
    crossed_suite.json     — Difficulty crossed against action-space size, built by oracle/generate.py
```

### Autoloads
- `LlmClient` — global singleton; connects signals to `GameController`
- `GameLogger` — global singleton; accessed directly by `TurnManager`, `GameController` and `PuzzleRunner`

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

- API target: whatever `LLM_API_MODEL` names, sent in the `anthropic` or `openai` request format that
  `LLM_API_FORMAT` selects. The defaults are `claude-sonnet-4-6` and `anthropic`
- `LlmClient` is an autoload singleton using Godot's `HTTPRequest` node
- API key is read from `LLM_API_KEY` (environment/.env) at startup; if absent, `LlmFallback` is used instead
- `GameController._ready()` passes `LlmClient.model_identity()` to the logger, so every game-log entry
  names what produced the run. A keyless run records `LlmHttpBase.NO_MODEL` rather than a model name,
  because every LLM placement in it came from `LlmFallback`
- The LLM prompt includes: current board state (ASCII grid), shop contents + gold, turn number, and the
  game replays (prep placements + battle trace + outcome) that fall inside the placement look-back window
- `GameLogger.get_placement_history()` is that window, and what bounds it is the attempt boundary
  rather than a fixed size. In free play nothing ever closes it, so it holds every game of the session
  the logger still has, capped at `MAX_GAME_HISTORY` = 10, which is wider there than the reflection
  channel's window of the last `REFLECTION_GAME_INTERVAL` = 2 games. In a puzzle run it closes at the
  start of every attempt, so by default a placement prompt carries no replay at all: none from an
  earlier attempt, and none from inside its own attempt, because an attempt is a single game.
  Reflection is not bounded by the attempt boundary, which is what lets attempts be independent of each
  other's replays while reflection still has something to reflect on
- Response format expected: `PLACE: <type> (row, col)` as the last non-empty line
- Parsed by `LlmResponseParser`; on failure, `LlmFallback` picks a random valid placement
- No extended thinking / chain-of-thought extraction currently implemented

## Puzzle Ablation Notes

- `GameController.start_ablation(max_attempts_per_puzzle, puzzle_path, configs, play_all_attempts, carry_attempt_history)`
  starts an end-to-end run. `start_mini_ablation` takes the same arguments and defaults to 3 attempts.
- `PuzzleLoader` loads the suite named by `--puzzle-path`, which defaults to
  `res://puzzles/puzzle_suite.json`.
- Each puzzle defines fixed LLM shop, fixed opponent shop, and a turn-by-turn scripted opponent placement sequence.
- During puzzle mode, the opponent turn is not human input or a second LLM; it is consumed from the scripted queue.
- `AblationRunner` evaluates all 8 `LlmModeConfig` combinations (`I{0,1}_E{0,1}_R{0,1}`) across all puzzles.
- Attempts at one puzzle are independent trials by default: no replay of an earlier attempt reaches a
  later attempt's placement prompt, so under a reflection-off config wins out of N is N separate draws.
  N is the attempts actually played: `play_all_attempts` is false unless `--all-attempts` is passed, so
  a puzzle stops at its first solve and how many attempts it contributes is decided by the outcome
  being measured.
  Reflection is the stated exception and keeps its look-back across attempts on purpose, so under a
  reflection-on config a later attempt carries conclusions drawn from the earlier ones.
- `--carry-attempt-history` restores the older regime, where a later attempt's placement prompt carried
  the earlier attempts' replays outright, and it is the only way to reproduce the attempt counts already
  published. It is a flag on a direct `godot --path godot -- --ablation` invocation; neither
  `scripts/run_ablation.py` nor `scripts/run_official_experiment.py` forwards it, or `--all-attempts`.
- Which regime a run used is stamped on every game-log entry as `carry_attempt_history`, and written into
  the ablation results file under the same key, so a pass rate says what it means without a join.
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
