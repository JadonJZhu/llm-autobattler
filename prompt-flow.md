The prompt files in `godot/prompts/` are modular text components used to build the Claude API `system` prompt and `user` message for the LLM player.

This document reflects the **current puzzle-ablation architecture** (no human-side LLM adapter).

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

`LlmPromptBuilder.build_user_message(...)` includes:

- current board state via `BoardSerializer.serialize(board)`
- both shops (`llm_shop` and opponent shop)
- current turn number
- replay history from `GameLogger.get_game_history()`
- final instruction to place on rows `0-1`

## 3) Reflection Prompt Flow (`reflection_client.gd`)

When reflection is enabled and the trigger interval is reached, `ReflectionClient` runs:

- system prompt: `reflection_system.txt`
- user footer/instruction: `reflection_user_footer.txt`
- input body: recent replays + recent LLM reasoning

The resulting feedback is stored and passed into subsequent `LlmPromptBuilder.build_system_prompt(...)` calls via `llm_reflection.txt`.

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
