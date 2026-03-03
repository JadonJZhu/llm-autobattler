The prompt files in `godot/prompts/` are modular text components used to build the Claude API `system` prompt and `user` message for the LLM player.

This document reflects the **current puzzle-ablation architecture**.

## 1) Prompt Loader (`prompt_loader.gd`)

All prompt files are loaded through `godot/scripts/prompt_loader.gd`.

- `load_prompt(filename)`: reads and caches plain text prompts from `res://prompts/`.
- `load_template(filename, placeholders)`: reads a template and replaces placeholders (used for reflection feedback).

## 2) Main Prompt Construction (`llm_prompt_builder.gd`)

`LlmClient` calls `LlmPromptBuilder` each LLM prep turn.

### System prompt composition order

`LlmPromptBuilder.build_system_prompt(config, reflection_feedback)` appends sections in this order and joins with `\n\n`:

1. `llm_role.txt` (always)
2. `llm_rules.txt` (only when `config.instructions_enabled`)
3. `llm_examples.txt` (only when `config.examples_enabled`)
4. `llm_reflection.txt` (only when `config.reflection_enabled` and feedback is non-empty)
5. `llm_response_format.txt` (always)

### User message composition

`LlmPromptBuilder.build_user_message(...)` produces:

```
=== GAME N — PREP TURN N ===        ← header includes game count once history exists
                                      (first game: "=== PREP TURN N ===" only)

Current board state:
       col 0  col 1  col 2
       +------+------+------+
row 0  |  La  |  .   |  La  |  (LLM)
row 1  |  .   |  Lb  |  .   |  (LLM)
row 2  |  Ha  |  .   |  Hb  |  (Opponent)
row 3  |  .   |  Hd  |  .   |  (Opponent)
       +------+------+------+

Score Summary: LLM N | Opponent N

Your shop: <unit type list and gold>
Opponent's shop: <unit type list and gold>

=== Game 1 Replay ===               ← one block per completed game, chronological

Start-of-battle board:
       col 0  col 1  col 2
       ...
       +------+------+------+

Score Summary: LLM N | Opponent N

Battle trace:
  1. <event string>
  2. <event string>
  ...

Outcome: LLM wins                   ← "LLM wins", "Opponent wins", or "Tie"
Final score: LLM N vs Opponent N

=== Game 2 Replay ===
...

Choose a unit to place on your side of the board (rows 0-1).
```

**Game history details:**

- Supplied by `GameLogger.get_game_history()`, which keeps a rolling window of the last **10 completed games**.
- Each replay dictionary contains: `start_board` (ASCII grid string), `battle_steps` (array of event strings), `outcome` ("LLM" / "Human" / "Tie"), `llm_score`, `human_score`.
- `format_game_replay` maps the stored `"Human"` outcome value to `"Opponent"` before inserting it into the prompt.
- The board ASCII grid is produced by `BoardSerializer.serialize_snapshot` at battle-start time and stored verbatim in `GameLogger`.
- `battle_steps` are produced in `BattleEngine.execute_step(...)` (`battle_engine.gd`) and logged via `TurnManager._execute_battle_step(...)` → `GameLogger.log_battle_step(...)`.
- To reduce mechanics leakage for induction-focused modes (especially `I0`), battle events use stripped transition strings instead of explanatory prose:
  - attack: `<TYPE> (<r1>,<c1>) x (<r2>,<c2>)`
  - advance: `<TYPE> (<r1>,<c1>) -> (<r2>,<c2>)`
  - no action: `<TYPE> (<r>,<c>) no_action` or `PASS`
  - escape: `<TYPE> (<r>,<c>) escape`
  - terminal marker: `END` (or appended as `| END`)
- Importantly, battle events no longer include rationale text like "cell occupied", "turn skipped for owner", or score-based winner narration; outcome/score remain in dedicated replay fields.

### LLM reasoning capture

After each API response, `LlmClient` extracts all text **before** the final `PLACE:` line as reasoning and emits it via `llm_reasoning_captured`. `GameLogger` accumulates this per-game in `_current_game_reasoning`. At game end, the joined reasoning string is appended to `_reasoning_history`, which is consumed by `ReflectionClient`.

## 3) Reflection Prompt Flow (`reflection_client.gd`)

When reflection is enabled and the trigger interval is reached, `ReflectionClient.request_reflection(game_history, llm_reasoning_log)` runs a separate Claude API call (model: `claude-sonnet-4-6`).

**System prompt:** `reflection_system.txt`

**User message structure:**

```
=== RECENT GAME REPLAYS (N games) ===

--- Game 1 ---
Start-of-battle board:
  ...
Battle trace:
  1. <event>
  ...
Outcome: <outcome>
Score: LLM N vs Human N

--- Game 2 ---
...

=== LLM REASONING LOG ===

Turn 1 reasoning:
<reasoning text>

...

<reflection_user_footer.txt>
```

- Includes the **last 5 games** (`MAX_GAME_REPLAYS = 5`) from the full game history.
- Includes all accumulated per-game reasoning strings from `GameLogger.get_recent_reasoning()`.
- The resulting feedback string is stored in `ReflectionClient` and passed to subsequent `LlmPromptBuilder.build_system_prompt(...)` calls, where it is injected via `llm_reflection.txt`.

## 4) Puzzle Ablation Wiring

In ablation mode (`AblationRunner` + `PuzzleRunner`):

- only the main LLM prompt stack is used (no mirrored human prompt files)
- scripted opponent placements are applied in `GameController` on human turns
- prompt generation remains identical to normal LLM turns, so each mode comparison is controlled by `LlmModeConfig` toggles only

## 5) Mode Toggles (`llm_mode_config.gd`)

`LlmModeConfig` controls ablation switches:

- `instructions_enabled`
- `examples_enabled`
- `reflection_enabled`

The label format is `I{0|1}_E{0|1}_R{0|1}` and is used by ablation logging/aggregation.