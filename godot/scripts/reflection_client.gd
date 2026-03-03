extends "res://scripts/llm_http_base.gd"
class_name ReflectionClient
## Calls the Claude API to get reflection feedback on recent game performance.
## Separate from LlmClient to keep responsibilities distinct (Single Responsibility).

signal reflection_response_received(feedback: String)
signal reflection_request_failed(error: String)

const REFLECTION_MODEL: String = "claude-sonnet-4-6"
const MAX_GAME_REPLAYS: int = 5

var _latest_feedback: String = ""
var _prompt_loader = preload("res://scripts/prompt_loader.gd").new()


func _ready() -> void:
	super._ready()


func get_latest_feedback() -> String:
	return _latest_feedback


func request_reflection(game_history: Array[Dictionary], llm_reasoning_log: Array[String]) -> void:
	if _is_requesting:
		push_warning("ReflectionClient: Request already in progress.")
		return
	if not has_api_key():
		reflection_request_failed.emit("No API key loaded.")
		return
	if game_history.is_empty():
		reflection_request_failed.emit("No game history to reflect on.")
		return

	_is_requesting = true
	var system_prompt: String = _prompt_loader.load_prompt("reflection_system.txt")
	var user_message: String = _build_user_message(game_history, llm_reasoning_log)
	_send_request(system_prompt, user_message)


func _build_user_message(game_history: Array[Dictionary], llm_reasoning_log: Array[String]) -> String:
	var recent_games: Array[Dictionary] = _get_recent_games(game_history)
	var parts: PackedStringArray = PackedStringArray()

	parts.append("=== RECENT GAME REPLAYS (%d games) ===" % recent_games.size())
	parts.append("")

	for game_index in range(recent_games.size()):
		var game: Dictionary = recent_games[game_index]
		parts.append("--- Game %d ---" % (game_index + 1))
		_append_game_details(parts, game)
		parts.append("")

	if not llm_reasoning_log.is_empty():
		parts.append("=== LLM REASONING LOG ===")
		parts.append("")
		for reasoning_index in range(llm_reasoning_log.size()):
			var reasoning: String = llm_reasoning_log[reasoning_index]
			parts.append("Turn %d reasoning:" % (reasoning_index + 1))
			parts.append(reasoning)
			parts.append("")

	parts.append(_prompt_loader.load_prompt("reflection_user_footer.txt"))

	return "\n".join(parts)


func _get_recent_games(game_history: Array[Dictionary]) -> Array[Dictionary]:
	var start_index: int = maxi(0, game_history.size() - MAX_GAME_REPLAYS)
	var recent: Array[Dictionary] = []
	for i in range(start_index, game_history.size()):
		recent.append(game_history[i])
	return recent


func _append_game_details(parts: PackedStringArray, game: Dictionary) -> void:
	var start_board: String = game.get("start_board", "")
	if not start_board.is_empty():
		parts.append("Start-of-battle board:")
		parts.append(start_board)

	var battle_steps: Array = game.get("battle_steps", [])
	if not battle_steps.is_empty():
		parts.append("Battle trace:")
		for i in range(battle_steps.size()):
			parts.append("  %d. %s" % [i + 1, battle_steps[i]])

	var outcome: String = game.get("outcome", "")
	if not outcome.is_empty():
		parts.append("Outcome: %s" % outcome)

	var llm_score: int = int(game.get("llm_score", -1))
	var human_score: int = int(game.get("human_score", -1))
	if llm_score >= 0 and human_score >= 0:
		parts.append("Score: LLM %d vs Human %d" % [llm_score, human_score])


func _on_api_response_parsed(response_text: String) -> void:
	var feedback: String = response_text.strip_edges()
	if feedback.is_empty():
		reflection_request_failed.emit("No text content found in API response.")
		return

	_latest_feedback = feedback
	print("ReflectionClient: Feedback received:\n" + feedback)
	reflection_response_received.emit(feedback)


func _on_request_error(error_message: String) -> void:
	reflection_request_failed.emit(error_message)


func _get_client_name() -> String:
	return "ReflectionClient"


func _get_api_model() -> String:
	return REFLECTION_MODEL
