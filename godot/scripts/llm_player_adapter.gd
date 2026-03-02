class_name LlmPlayerAdapter
extends LlmHttpBase
## Controls an LLM-driven player on the human side (rows 2-3) for LLM-vs-LLM experiments.
## Extends LlmHttpBase for shared HTTP infrastructure. Builds prompts from the human perspective.

signal human_llm_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i)
signal human_llm_request_failed(error_message: String)

var _mode_config: LlmModeConfig = LlmModeConfig.new()
var _prompt_builder: LlmPromptBuilder = LlmPromptBuilder.new()
var _response_parser: LlmResponseParser = LlmResponseParser.new()


func _ready() -> void:
	super._ready()
	_response_parser.valid_rows = [2, 3]


func set_mode_config(config: LlmModeConfig) -> void:
	_mode_config = config


func request_human_llm_prep(board: GameBoard, human_shop: Shop, turn_number: int,
		game_history: Array[Dictionary]) -> void:
	if _is_requesting:
		push_warning("LlmPlayerAdapter: Request already in progress.")
		return
	if not has_api_key():
		human_llm_request_failed.emit("No API key loaded.")
		return

	_is_requesting = true
	var system_prompt: String = _build_human_system_prompt()
	var user_message: String = _build_human_user_message(board, human_shop, turn_number, game_history)
	_send_request(system_prompt, user_message)


func _on_api_response_parsed(response_text: String) -> void:
	var parse_result: Dictionary = _response_parser.parse_place_command(response_text)
	if parse_result.is_empty():
		human_llm_request_failed.emit("Failed to parse PLACE command from human LLM response.")
		return
	human_llm_response_received.emit(parse_result["unit_type"], parse_result["position"])


func _on_request_error(error_message: String) -> void:
	human_llm_request_failed.emit(error_message)


func _get_client_name() -> String:
	return "LlmPlayerAdapter"


# --- Human-perspective prompt building ---


func _build_human_system_prompt() -> String:
	var sections: PackedStringArray = PackedStringArray()

	sections.append(_build_human_role_section())

	if _mode_config.instructions_enabled:
		sections.append(_build_human_rules_section())

	if _mode_config.examples_enabled:
		sections.append(_build_human_examples_section())

	sections.append(_build_human_response_format())

	return "\n\n".join(sections)


func _build_human_role_section() -> String:
	return "You are playing a 4x3 autochess game. The board has 4 rows and 3 columns.
You control the bottom 2 rows (rows 2-3). Your opponent (LLM) controls the top 2 rows (rows 0-1).

GAME PHASES:
1. PREPARATION: You and the opponent alternate placing units. The opponent places first each round.
2. BATTLE: Units fight automatically (you don't control this phase).

UNIT TYPES AND COSTS:
- A (1 gold): Attacks the cell directly ahead. If enemy there, removes it. Otherwise advances forward one cell.
- B (1 gold): Attacks diagonally left-ahead. If on leftmost column (col 0), cannot attack. Otherwise advances forward.
- C (1 gold): Attacks diagonally right-ahead. If on rightmost column (col 2), cannot attack. Otherwise advances forward.
- D (2 gold): Ranged unit. Removes the closest enemy by Manhattan distance (ties broken left-to-right, then top-to-bottom).

YOUR SHOP shows which unit types you can buy and your remaining gold."


func _build_human_rules_section() -> String:
	return "BATTLE MECHANICS:
- Your units face UP (toward lower rows). Opponent units face DOWN (toward higher rows).
- Turn order scan: A units are checked first, then B, then C, then D. Within same type, earlier-placed units are checked first.
- If the highest-priority unit is blocked and cannot act, the scan continues to the next unit in priority order until one can act.
- If no unit on that side can act, that side's step is skipped.
- Units that advance past the opponent's edge ESCAPE and earn 1 point.
- Battle alternates: opponent goes first, then you, repeat until neither side can take any action.
- Score is: units still on board + escaped units. Higher score wins. Equal scores are a tie.

STRATEGY TIPS:
- Consider what the opponent might place and position your units to counter."


func _build_human_examples_section() -> String:
	return "EXAMPLES:
(Example battle traces will be provided here in future updates.)"


func _build_human_response_format() -> String:
	return "RESPONSE FORMAT:
Think through your reasoning, then end your response with exactly this line:
PLACE: <type> (row, col)

Where <type> is A, B, C, or D, and row is 2 or 3 (your rows), col is 0, 1, or 2.
The PLACE line must be the last non-empty line of your response."


func _build_human_user_message(board: GameBoard, human_shop: Shop, turn_number: int,
		game_history: Array[Dictionary]) -> String:
	var parts: PackedStringArray = PackedStringArray()

	var game_count: int = game_history.size()
	if game_count > 0:
		parts.append("=== GAME %d — PREP TURN %d ===" % [game_count + 1, turn_number])
	else:
		parts.append("=== PREP TURN %d ===" % turn_number)
	parts.append("")
	parts.append("Current board state:")
	parts.append(BoardSerializer.serialize(board))
	parts.append("")
	parts.append("Your shop: %s" % human_shop.get_purchase_summary())
	parts.append("")

	for i in range(game_history.size()):
		var replay_text: String = _prompt_builder.format_game_replay(game_history[i], i + 1)
		if not replay_text.is_empty():
			parts.append(replay_text)
			parts.append("")

	parts.append("Choose a unit to place on your side of the board (rows 2-3).")
	return "\n".join(parts)
