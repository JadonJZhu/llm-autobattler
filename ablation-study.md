# Ablation Study Deep Dive (`godot/scripts/ablation_runner.gd`)

This document explains, in implementation-level detail, how the puzzle ablation system works in this project, centered on `godot/scripts/ablation_runner.gd` and the scripts it orchestrates.

---

## 1) What the ablation runner is actually doing

`AblationRunner` is an orchestration node that executes a full grid search over prompt-mode toggles, across all loaded puzzle scenarios.

- **Prompt mode grid**: `instructions ∈ {off,on}`, `examples ∈ {off,on}`, `reflection ∈ {off,on}`.
- **Total configs**: `2 × 2 × 2 = 8`.
- **For each config**: run every puzzle once (where each puzzle may contain multiple attempts up to a cap).
- **Per puzzle/config pair**: delegated to `PuzzleRunner`, which handles repeated attempts until solved or max attempts reached.
- **Final output**: one dictionary containing raw per-puzzle summaries + per-config aggregates, then persisted by `PuzzleLogger`.

So conceptually:

1. Build all 8 `LlmModeConfig`s.
2. Iterate puzzle list for config 1.
3. Iterate puzzle list for config 2.
4. ...
5. Iterate puzzle list for config 8.
6. Compute aggregate metrics and emit `ablation_completed(results)`.

---

## 2) Entry point and top-level controls

The ablation flow is triggered via `GameController.start_ablation(...)`:

```gdscript
func start_ablation(max_attempts_per_puzzle: int = 10, puzzle_path: String = DEFAULT_PUZZLE_PATH) -> void
```

### Parameters exposed to caller

1. **`max_attempts_per_puzzle`** (default `10`)
   - Upper bound on attempts for each `(config, puzzle)` run.
   - Clamped to at least 1 internally (`maxi(1, attempt_limit)` in both runner layers).
2. **`puzzle_path`** (default `res://puzzles/puzzle_suite.json`)
   - JSON file loaded by `PuzzleLoader`.
   - Must parse and validate into non-empty scenarios; otherwise ablation does not start.

### Side effects when starting ablation

When `start_ablation(...)` succeeds in `GameController`:

- Puzzle mode enabled (`_puzzle_mode_enabled = true`).
- Battle autoplay forced on (`turn_manager.set_autoplay(true)`).
- Human shop buttons disabled.
- `_ablation_runner.start(puzzles, max_attempts_per_puzzle)` invoked.

---

## 3) `AblationRunner` API, state, and signals

### Public API

`AblationRunner.start(puzzles: Array, attempt_limit: int = 10) -> bool`

- Returns `false` if puzzle list is empty.
- Otherwise initializes internal state and emits first puzzle request.

`AblationRunner.stop() -> void`

- Sets `_is_running = false`.

`AblationRunner.is_running() -> bool`

- Simple running flag accessor.

`AblationRunner.record_puzzle_summary(summary: Dictionary) -> void`

- Called by controller after `PuzzleRunner` completes one puzzle/config pair.
- Appends summary, emits progress, advances indices, emits next request or final results.

### Internal state fields

- `max_attempts_per_puzzle: int` (default 10; clamped min 1).
- `_is_running: bool`
- `_configs: Array[LlmModeConfig]` (always 8 entries when started).
- `_puzzles: Array`
- `_results: Array[Dictionary]` (one summary per completed puzzle/config pair).
- `_current_config_index: int`
- `_current_puzzle_index: int`

### Signals emitted by `AblationRunner`

1. `puzzle_requested(config: LlmModeConfig, scenario, max_attempts: int)`
   - Tells outer controller to run one scenario with one config.
2. `ablation_progress(config_label: String, puzzle_id: String, completed: int, total: int)`
   - Emitted after each puzzle summary is recorded.
3. `ablation_completed(results: Dictionary)`
   - Emitted once all config/puzzle pairs finish.

---

## 4) The “hyperparameter” space in this project

Strictly from code behavior, the ablation manipulates these experiment knobs:

## A) Prompt-mode toggles (primary ablation dimensions)

Defined in `LlmModeConfig`:

- `instructions_enabled: bool`
- `examples_enabled: bool`
- `reflection_enabled: bool`

Label format:

- `I%d_E%d_R%d` (e.g. `I1_E0_R1`)

Generated exhaustively by nested loops over `[false, true]` in `AblationRunner._build_mode_configs()`, giving:

1. `I0_E0_R0`
2. `I0_E0_R1`
3. `I0_E1_R0`
4. `I0_E1_R1`
5. `I1_E0_R0`
6. `I1_E0_R1`
7. `I1_E1_R0`
8. `I1_E1_R1`

## B) Attempt budget (secondary search/control knob)

- `max_attempts_per_puzzle` (global per ablation run).
- Applied to every puzzle under every config.
- If unsolved within this budget, puzzle marked unsolved and `attempts_needed` set to max.

## C) Puzzle suite itself

- The loaded puzzle set is effectively part of experiment configuration.
- Current `puzzle_suite.json` has 9 puzzles (IDs across easy/medium/hard).
- Total puzzle/config evaluations in default suite:
  - `8 configs × 9 puzzles = 72 puzzle summaries`.

---

## 5) How mode toggles change the real LLM prompt

`LlmClient` uses `LlmPromptBuilder.build_system_prompt(config, reflection_feedback)`.

Prompt section behavior:

1. Always includes role/API section (`llm_role.txt`).
2. Include `llm_rules.txt` only if `instructions_enabled`.
3. Include `llm_examples.txt` only if `examples_enabled`.
4. Include reflection template (`llm_reflection.txt`) only if:
   - `reflection_enabled == true` **and**
   - `reflection_feedback` is non-empty.
5. Always includes response format (`llm_response_format.txt`).

Important ablation-specific detail: `GameController._on_ablation_puzzle_requested(...)` resets reflection feedback each time:

- `LlmClient.set_reflection_feedback("")`
- `_games_since_reflection = 0`

Because reflection feedback is forcibly cleared at each puzzle request, the reflection section will typically not be injected during ablation (unless some other code path repopulates it before the next LLM request in that puzzle). So `R` may currently act as a near no-op toggle under this orchestration.

---

## 6) Full control-flow timeline per run

### Phase 1: Setup

1. `start_ablation(...)` called.
2. `PuzzleLoader.load_puzzles(path)` parses and validates puzzle JSON.
3. `AblationRunner.start(puzzles, max_attempts)` initializes indices/configs/results.
4. `AblationRunner` emits first `puzzle_requested(...)`.

### Phase 2: Per `(config, puzzle)` execution

1. Controller receives `puzzle_requested(config, scenario, max_attempts)`.
2. Controller:
   - sets `_mode_config = config`,
   - calls `LlmClient.set_mode_config(config)`,
   - clears reflection feedback.
3. `PuzzleRunner.start_puzzle(scenario, config, max_attempts)`:
   - resets attempt state,
   - copies opponent scripted placements queue,
   - clears `GameLogger` history,
   - emits `attempt_started(...)`.
4. Controller reacts to `attempt_started` by calling `_start_game()`.
5. During prep:
   - LLM moves through API/fallback.
   - Opponent uses scripted queue (`consume_next_opponent_placement`).
6. Battle auto-runs (`autoplay=true`) until game over.
7. On game over, controller calls:
   - `PuzzleRunner.record_attempt_result(winner, score_data, battle_step_count)`.
8. `PuzzleRunner`:
   - appends attempt result,
   - if solved or attempts exhausted -> emits `puzzle_completed(summary)`,
   - else increments attempt and reruns same puzzle.

### Phase 3: Aggregation and progression

1. Controller receives `puzzle_completed(summary)`.
2. If ablation still running: `AblationRunner.record_puzzle_summary(summary)`.
3. `AblationRunner`:
   - appends summary,
   - emits progress,
   - advances puzzle/config indices,
   - either requests next puzzle or emits final completion.

### Phase 4: Persistence

On `ablation_completed(results)`:

1. Controller disables puzzle mode.
2. `PuzzleLogger.save_ablation_results(results)` called.
3. JSON written to `user://game_logs/ablation_YYYYMMDD_HHMMSS.json`.
4. UI status shows saved path.

---

## 7) Data that is saved: exact structures

There are **two distinct logging channels** active during ablation:

1. **Ablation summary log** (from `PuzzleLogger`) — one file per full ablation run.
2. **Per-game operational logs** (from `GameLogger`) — saved at each game end to `game_<session>.json`.

The ablation file is the primary study artifact.

## A) Ablation output file structure

Top-level payload written by `PuzzleLogger`:

```json
{
  "timestamp": "system datetime string",
  "results": {
    "max_attempts_per_puzzle": 10,
    "puzzle_count": 9,
    "config_count": 8,
    "results": [ /* per puzzle summary entries */ ],
    "by_config": { /* aggregate metrics keyed by config label */ }
  }
}
```

### `results.results[]` (raw per puzzle/config summaries)

Each entry comes from `PuzzleRunner._build_summary(...)`:

- `puzzle_id: String`
- `description: String`
- `difficulty: int`
- `config: String` (e.g. `I1_E0_R1`)
- `solved: bool`
- `attempts_needed: int`
  - first successful attempt index, else `max_attempts`
- `max_attempts: int`
- `attempt_scores: Array[Dictionary]`

`attempt_scores[]` per attempt contains:

- `scenario_id`
- `attempt` (1-indexed)
- `winner` (`LLM`, `Human`, `Tie`)
- `llm_score`
- `opponent_score`
- `llm_remaining`
- `opponent_remaining`
- `llm_escaped`
- `opponent_escaped`
- `battle_steps`
- `solved_this_attempt` (`llm_score > opponent_score`)

### `results.by_config` (aggregated metrics)

Each config label maps to:

- `config: String`
- `puzzles_total: int`
- `puzzles_solved: int`
- `sum_attempts_needed: int` (only solved puzzles contribute)
- `mean_attempts_solved_only: float`
  - `sum_attempts_needed / puzzles_solved` if solved > 0 else `0.0`
- `pass_rate: float`
  - `puzzles_solved / puzzles_total` if total > 0 else `0.0`

## B) Game log files saved during ablation

`TurnManager._end_game()` calls `GameLogger.save_log()` every game end. This writes/overwrites:

- `user://game_logs/game_<session_id>.json`

with a chronological array of turn/battle/game-over entries for the current session.

Even though ablation has its own summary file, these game logs can be useful for deeper debugging/tracing specific failures.

---

## 8) Puzzle input schema and validation rules

Loaded from JSON root:

```json
{
  "puzzles": [ ... ]
}
```

Per puzzle required/expected fields:

- `id` (required non-empty string)
- `description` (string, optional default empty)
- `difficulty` (int, clamped min 1)
- `llm_shop` (array of unit labels `A|B|C|D`, must be non-empty)
- `llm_gold` (int, clamped min 0)
- `opponent_shop` (array of unit labels `A|B|C|D`, must be non-empty)
- `opponent_gold` (int, clamped min 0)
- `opponent_placements` (array of dicts)
  - each: `{ "type": "A|B|C|D", "row": int, "col": int }`
  - position must be inside grid and on human rows only (`GridConstants.HUMAN_ROWS`)

Invalid entries are skipped with `push_error(...)`; if key constraints fail (e.g., empty required shop), that puzzle is dropped.

---

## 9) Evaluation semantics (what counts as “solved”)

A puzzle attempt is marked solved iff:

- `llm_score > opponent_score`

Tie does **not** solve the puzzle.

Per puzzle summary semantics:

- `solved=true` means at least one attempt solved within budget.
- `attempts_needed` is first successful attempt index.
- If never solved, `attempts_needed = max_attempts`.

Per config aggregate semantics:

- `pass_rate` is puzzle-level success fraction, not attempt-level win fraction.
- `mean_attempts_solved_only` ignores unsolved puzzles.

---

## 10) Runtime/UI signals and observability

During run, UI status messages are updated from callbacks:

- Attempt start: `"Puzzle <id> attempt x/y (<config>)"`
- Attempt complete: winner and score.
- Progress: `"Ablation progress completed/total | <config> | <puzzle_id>"`
- Completion: final saved log path.

Also emitted as machine-usable signals:

- `puzzle_requested`
- `ablation_progress`
- `ablation_completed`
- `attempt_started`
- `attempt_completed`
- `puzzle_completed`

---

## 11) Practical experiment sizing and compute expectations

If:

- `P = number of puzzles`
- `C = 8 configs`
- `A = max_attempts_per_puzzle`

Then upper bound on total games played:

- `C × P × A`

For current suite (`P=9`) and default `A=10`:

- Max games = `8 × 9 × 10 = 720` game simulations (actual count lower if puzzles solve early).

---

## 12) Known implementation caveats to keep in mind

1. **Reflection toggle caveat**
   - Ablation request callback clears reflection feedback every puzzle request.
   - This can reduce meaningful effect of `R` unless reflection text is replenished before prompting.

2. **No RNG seed control in runner**
   - The runner itself does not expose seeded reproducibility controls.
   - Determinism depends on battle/puzzle setup and any stochastic fallback paths.

3. **No confidence intervals/stat tests in built-in output**
   - Output provides descriptive metrics only (`pass_rate`, mean attempts on solved).
   - Statistical significance analysis must be done offline.

4. **Game logs and ablation logs are separate artifacts**
   - Ablation summary is compact and analysis-friendly.
   - Detailed step traces live in `game_<session>.json`.

5. **History trace leakage control**
   - `battle_steps` in replay history are serialized as compact state transitions (`x`, `->`, `no_action`, `escape`, `END`) instead of explanatory natural-language mechanics.
   - This reduces instructional leakage into `I0` ("no instructions") mode while preserving observability of state changes.

---

## 13) Minimal “how to run” and where to look

Programmatic call:

```gdscript
start_ablation(10, "res://puzzles/puzzle_suite.json")
```

Primary analysis artifact:

- `user://game_logs/ablation_<timestamp>.json`

Supplementary detailed traces:

- `user://game_logs/game_<session_id>.json`

---

## 14) Suggested post-processing metrics (not yet in code)

If you want richer analysis after export, compute offline:

- Attempts-to-solve distribution (median, p90) per config.
- Difficulty-stratified pass rates (easy/medium/hard buckets).
- Per-puzzle hardness ranking by minimum achieved attempts.
- Pairwise config deltas (`I1_E1_R0` vs `I0_E1_R0`, etc.).
- Bootstrap confidence intervals for pass rate differences.

These can all be computed directly from saved `results.results[]` entries.
