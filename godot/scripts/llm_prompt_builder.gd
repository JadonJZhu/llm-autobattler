class_name LlmPromptBuilder
extends RefCounted

var _prompt_loader = preload("res://scripts/prompt_loader.gd").new()


func build_system_prompt(config: LlmModeConfig, reflection_feedback: String = "") -> String:
	var sections: PackedStringArray = PackedStringArray()

	sections.append(_build_api_section())

	if config.instructions_enabled:
		sections.append(_build_rules_section())

	if config.examples_enabled:
		sections.append(_build_examples_section())

	if config.reflection_enabled and not reflection_feedback.is_empty():
		sections.append(_build_reflection_section(reflection_feedback))

	sections.append(_build_response_format())

	return "\n\n".join(sections)


func build_user_message(
	board: GameBoard,
	llm_shop: Shop,
	turn_number: int,
	game_history: Array[Dictionary],
	_config: LlmModeConfig
) -> String:
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
	parts.append("Your shop: %s" % llm_shop.get_purchase_summary())
	parts.append("")

	for i in range(game_history.size()):
		var replay_text: String = format_game_replay(game_history[i], i + 1)
		if not replay_text.is_empty():
			parts.append(replay_text)
			parts.append("")

	parts.append("Choose a unit to place on your side of the board (rows 0-1).")
	return "\n".join(parts)


func format_game_replay(replay: Dictionary, game_number: int = 0) -> String:
	if replay.is_empty():
		return ""

	var parts: PackedStringArray = PackedStringArray()

	if game_number > 0:
		parts.append("=== Game %d Replay ===" % game_number)
	else:
		parts.append("Previous game replay:")
	parts.append("")

	var start_board: String = replay.get("start_board", "")
	if not start_board.is_empty():
		parts.append("Start-of-battle board:")
		parts.append(start_board)
		parts.append("")

	var battle_steps: Array = replay.get("battle_steps", [])
	if not battle_steps.is_empty():
		parts.append("Battle trace:")
		for i in range(battle_steps.size()):
			parts.append("  %d. %s" % [i + 1, battle_steps[i]])
		parts.append("")

	var outcome: String = replay.get("outcome", "")
	var llm_score: int = int(replay.get("llm_score", -1))
	var human_score: int = int(replay.get("human_score", -1))
	if not outcome.is_empty():
		parts.append("Outcome: %s wins" % outcome if outcome != "Tie" else "Outcome: Tie")
	if llm_score >= 0 and human_score >= 0:
		parts.append(
			"Final score: LLM %d vs Human %d" % [llm_score, human_score]
		)

	return "\n".join(parts)


# --- Private section builders ---


func _build_api_section() -> String:
	return _prompt_loader.load_prompt("llm_role.txt")


func _build_rules_section() -> String:
	return _prompt_loader.load_prompt("llm_rules.txt")


func _build_examples_section() -> String:
	return _prompt_loader.load_prompt("llm_examples.txt")


func _build_reflection_section(feedback: String) -> String:
	return _prompt_loader.load_template("llm_reflection.txt", {
		"feedback": feedback
	})


func _build_response_format() -> String:
	return _prompt_loader.load_prompt("llm_response_format.txt")
