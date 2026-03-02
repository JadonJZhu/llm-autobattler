# Implementation Plan: LLM Mode System Prerequisites

This plan covers the infrastructure needed before writing any mode-specific prompts.
Three prerequisites: (1) multi-game history storage, (2) composable prompt builder with config,
(3) LLM-vs-LLM experiment harness.

---

## Step 1: Create `LlmModeConfig` resource

**File:** `godot/scripts/llm_mode_config.gd`

Create a pure data class (`RefCounted`) that holds the three boolean toggles:

```gdscript
class_name LlmModeConfig
extends RefCounted

var instructions_enabled: bool = true
var examples_enabled: bool = false
var reflection_enabled: bool = false
```

This config is passed into the prompt builder and referenced by the game controller.
Each LLM player gets its own config instance (important for LLM-vs-LLM where sides differ).

---

## Step 2: Expand `GameLogger` to store multi-game history

**File:** `godot/scripts/game_logger.gd`

Currently `_previous_game_replay` stores only the last game's replay. We need a rolling
history for all modes (reflection needs 5 games; all modes get history to learn from).

Changes:
- Add `_game_history: Array[Dictionary]` that accumulates every finalized replay.
- Cap at `MAX_GAME_HISTORY = 20` entries (oldest dropped when exceeded).
- In `finalize_game_replay()`: append the replay dict to `_game_history` in addition to
  setting `_previous_game_replay` (keep backward compat for now).
- Add `get_game_history(count: int = -1) -> Array[Dictionary]` that returns the last
  `count` entries (or all if -1).
- Add `get_game_count() -> int` returning `_game_history.size()`.
- Add `clear_history() -> void` for resetting between experiment runs.

No existing callers break — `get_previous_game_replay()` still works as before.

---

## Step 3: Refactor `LlmPromptBuilder` into composable sections

**File:** `godot/scripts/llm_prompt_builder.gd`

The current `build_system_prompt()` returns one monolithic string with full rules.
Refactor it into section builders that compose based on `LlmModeConfig`.

### 3a: Extract section methods

Break the current system prompt into private methods:
- `_build_api_section() -> String` — Grid dimensions, unit costs, PLACE format.
  Always included. This is the minimal "how to interact" info.
- `_build_rules_section() -> String` — Battle mechanics, turn order, scoring, escape rules.
  Only included when `config.instructions_enabled == true`.
- `_build_examples_section() -> String` — Three traced battle examples.
  Only included when `config.examples_enabled == true`. (Content is a placeholder/stub
  for now — actual examples are a later task.)
- `_build_reflection_section(feedback: String) -> String` — Wraps the reflection helper's
  feedback text into the prompt. Only included when `config.reflection_enabled == true`
  and feedback is non-empty. (Stub for now.)
- `_build_response_format() -> String` — The PLACE command format instructions.
  Always included.

### 3b: Update `build_system_prompt` signature

```gdscript
func build_system_prompt(config: LlmModeConfig, reflection_feedback: String = "") -> String
```

Composes sections in order: api → rules (if enabled) → examples (if enabled) →
reflection feedback (if enabled and non-empty) → response format.

### 3c: Update `build_user_message` signature

```gdscript
func build_user_message(
    board: GameBoard,
    llm_shop: Shop,
    turn_number: int,
    game_history: Array[Dictionary],
    config: LlmModeConfig
) -> String
```

Changes:
- Accept the full `game_history` array instead of a single replay dict.
- Format all past games (using `format_game_replay` for each) instead of just the last one.
- Include a game counter header so the LLM knows which game number it's on.

### 3d: Update `format_game_replay` (no signature change needed)

Prefix each replay with a game number label, e.g., "=== Game 3 Replay ===".
Add parameter `game_number: int` to the method.

---

## Step 4: Thread config through `LlmClient`

**File:** `godot/scripts/llm_client.gd`

Changes:
- Add `var _mode_config: LlmModeConfig` field, defaulting to a new instance.
- Add `var _reflection_feedback: String = ""` field.
- Add `set_mode_config(config: LlmModeConfig) -> void`.
- Add `set_reflection_feedback(feedback: String) -> void`.
- Update `request_llm_prep()` signature to accept `game_history: Array[Dictionary]`
  instead of `previous_game_replay: Dictionary`.
- Pass `_mode_config` and `_reflection_feedback` into the prompt builder calls.

---

## Step 5: Update `GameController` to use new signatures

**File:** `godot/scripts/game_controller.gd`

Changes:
- In `_trigger_llm_turn()`: pass `GameLogger.get_game_history()` instead of
  `GameLogger.get_previous_game_replay()`.
- Store a default `LlmModeConfig` on the controller; pass it to `LlmClient` at startup.
- On restart (`_restart_game`), preserve the config across games (don't reset it).

This step is purely mechanical — wire the new signatures without changing behavior.
With `instructions_enabled = true` and other flags `false`, behavior matches current.

---

## Step 6: Create `ReflectionClient`

**File:** `godot/scripts/reflection_client.gd`

A standalone class (extends `Node`) responsible for calling the Claude API to get
reflection feedback. Separate from `LlmClient` to keep responsibilities distinct.

Design:
- Owns its own `HTTPRequest` node.
- `request_reflection(game_history: Array[Dictionary], llm_reasoning_log: Array[String]) -> void`
  — sends the last 5 game replays + the LLM's reasoning from those games to Claude.
- Signal: `reflection_response_received(feedback: String)`.
- Signal: `reflection_request_failed(error: String)`.
- Uses a smaller model (Haiku) or same model — configurable via constant.
- Builds its own prompt (a simple system prompt telling it to analyze strategies and suggest improvements).
- Stores the latest feedback text so it can be retrieved by the game controller.

Does NOT need to be an autoload — owned by `GameController` as a child node.

### 6a: Store LLM reasoning text

Currently the LLM's reasoning (the full response text before the PLACE line) is printed
to console but not stored. We need to capture and accumulate it.

Changes to `LlmClient`:
- Add signal `llm_reasoning_captured(reasoning_text: String)`.
- In `_process_api_response`, extract the text before the PLACE line and emit it.

Changes to `GameLogger`:
- Add `_reasoning_history: Array[String]` to accumulate per-game reasoning texts.
- Add `log_llm_reasoning(text: String) -> void`.
- Add `get_recent_reasoning(count: int) -> Array[String]`.
- Clear reasoning for the current game on `finalize_game_replay`.

Changes to `GameController`:
- Connect `LlmClient.llm_reasoning_captured` → `GameLogger.log_llm_reasoning`.

---

## Step 7: Wire reflection into the game loop

**File:** `godot/scripts/game_controller.gd`

The reflection helper triggers every 5 completed games when `config.reflection_enabled`
is true.

Changes:
- Add `var _reflection_client: ReflectionClient` as a child node (created in `_ready`).
- Add `var _games_since_reflection: int = 0` counter.
- In `_on_game_over` (or `_restart_game`): increment the counter. If it reaches 5 and
  reflection is enabled, call `_reflection_client.request_reflection(...)` with the last
  5 game replays and reasoning.
- Connect `reflection_response_received` → store the feedback string on `LlmClient`
  via `set_reflection_feedback()`. Reset the counter to 0.
- If the reflection request fails, log a warning and continue without new feedback.
- The reflection call happens **between games** (during the restart flow), so we need to
  delay `_start_game()` until the reflection response arrives. Add a flag
  `_awaiting_reflection: bool` and gate `_restart_game` on it. Show a
  "Reflection helper is analyzing..." status message while waiting.

---

## Step 8: Add UI toggles for the three modes

**File:** `godot/scripts/main_ui.gd`

Add three `CheckButton` nodes below the autoplay toggle:
- "Instructions" (default: ON)
- "Examples" (default: OFF)
- "Reflection" (default: OFF)

Design:
- New signal: `mode_config_changed(config: LlmModeConfig)`.
- Each CheckButton toggle updates a local `LlmModeConfig` and emits the signal.
- Toggles are only interactive during prep phase (disable during battle to prevent
  mid-game config changes) — or alternatively, only apply on next game restart.
- Style consistently with the existing autoplay button.

Changes to `GameController`:
- Connect `main_ui.mode_config_changed` → `_on_mode_config_changed`.
- `_on_mode_config_changed` updates `LlmClient.set_mode_config(config)`.

---

## Step 9: Build the LLM-vs-LLM experiment harness

### 9a: Create `LlmPlayerAdapter`

**File:** `godot/scripts/llm_player_adapter.gd`

A class that acts as an LLM-controlled "human side" player. It:
- Has its own `LlmModeConfig`.
- Has its own `LlmPromptBuilder` (mirrored for human-side perspective — rows 2-3).
- Sends API requests and parses responses like `LlmClient`, but for the human side.
- Emits `human_llm_response_received(unit_type, grid_pos)`.

Key difference from `LlmClient`: the prompt tells this LLM it controls rows 2-3,
and the response parser accepts rows 2-3 instead of 0-1.

Approach: Parameterize `LlmResponseParser` to accept a configurable row range instead
of hardcoding rows 0-1. Add `var valid_rows: Array[int] = [0, 1]` that can be set
to `[2, 3]` for the human-side adapter.

### 9b: Create `ExperimentRunner`

**File:** `godot/scripts/experiment_runner.gd`

Orchestrates automated LLM-vs-LLM game sequences.

Design:
- Extends `Node`, added as a child of the root scene (or a separate experiment scene).
- Configuration:
  - `llm_config: LlmModeConfig` — config for the LLM (top) side.
  - `human_config: LlmModeConfig` — config for the human-side LLM.
  - `games_per_trial: int = 30`
  - `current_game: int = 0`
- Flow:
  1. Sets up both players' configs.
  2. Calls `_start_game()` on GameController.
  3. When it's "human's turn," instead of waiting for clicks, triggers the
     `LlmPlayerAdapter` to make an API call.
  4. On game over, logs results, increments counter, auto-restarts.
  5. After `games_per_trial` games, emits `trial_completed(results: Dictionary)`.
- Results dictionary: win counts, score differentials, average game length, per-game log.

### 9c: Modify `TurnManager` for automated human turns

Currently `TurnManager` waits for `cell_clicked` from the board for human turns.
For LLM-vs-LLM, we need to programmatically trigger human placements.

Add a method:
```gdscript
func apply_human_prep_placement(type: UnitData.UnitType, pos: Vector2i) -> bool
```

This mirrors `apply_llm_prep_placement` but for the human side. It bypasses the
click-select-place flow. The existing click flow remains for human-vs-LLM games.

### 9d: Wire `GameController` to support both modes

Add a flag `var experiment_mode: bool = false` to `GameController`.

When `experiment_mode` is true:
- On `_on_prep_turn_changed(PrepTurn.HUMAN)`: instead of waiting for clicks,
  trigger `LlmPlayerAdapter.request_human_llm_prep(...)`.
- Connect `LlmPlayerAdapter.human_llm_response_received` →
  `turn_manager.apply_human_prep_placement(...)`.
- On game over: auto-restart instead of waiting for click.
- Disable human shop UI interaction.

### 9e: Experiment logging

Extend `GameLogger`:
- Add `var _experiment_results: Array[Dictionary]` for aggregate stats.
- Add `log_experiment_game(game_number: int, llm_config_label: String, human_config_label: String, outcome: Dictionary) -> void`.
- Add `save_experiment_log(filename: String) -> void` — writes a summary CSV or JSON
  with one row per game: game number, LLM config, human config, winner, scores, game length.
- Add config label generation: `LlmModeConfig.get_label() -> String` returning something
  like "I1_E0_R0" (instructions=on, examples=off, reflection=off).

---

## Implementation Order

Execute steps in this order to minimize broken intermediate states:

1. **Step 1** — `LlmModeConfig` (pure data, no dependencies)
2. **Step 2** — `GameLogger` multi-game history (additive, no breakage)
3. **Step 3** — Refactor `LlmPromptBuilder` (composable sections)
4. **Step 4** — Thread config through `LlmClient`
5. **Step 5** — Update `GameController` wiring (restore working state)
6. **Step 6** — `ReflectionClient` + reasoning capture
7. **Step 7** — Wire reflection into game loop
8. **Step 8** — UI toggles
9. **Step 9a-9e** — LLM-vs-LLM experiment harness (can be done in parallel with 6-8)

Steps 1-5 are the **critical path** — after those, the system works identically to today
but with the infrastructure ready for mode prompts.

Steps 6-7 (reflection) and Step 8 (UI) are independent of each other and can be
parallelized.

Step 9 (experiment harness) is the largest chunk but is mostly additive new code.

---

## What This Plan Does NOT Cover (deferred)

- Writing the actual prompt content for each mode (instructions text, example traces,
  reflection helper system prompt)
- Running the full 8-mode experiment
- Statistical analysis tooling
- Cost optimization (Haiku for validation runs, context truncation)
- Shop seed fixing for controlled experiments
   