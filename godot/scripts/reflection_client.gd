extends Node
class_name ReflectionClient
## Calls the Claude API to get reflection feedback on recent game performance.
## Separate from LlmClient to keep responsibilities distinct (Single Responsibility).

signal reflection_response_received(feedback: String)
signal reflection_request_failed(error: String)

const API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const API_MODEL: String = "claude-sonnet-4-6"
const ANTHROPIC_VERSION: String = "2023-06-01"
const API_KEY_FILE_PATH: String = "res://api_key.txt"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096
const MAX_GAME_REPLAYS: int = 5

const SYSTEM_PROMPT: String = """You are a strategic coach for an autochess game played on a 4x3 grid.

You will receive recent game replays (board states, battle traces, outcomes, scores) and the LLM player's reasoning log from those games. Your job is to analyze performance and provide actionable feedback.

Instructions:
1. Analyze the game replays provided — look at board states, battle traces, outcomes, and scores.
2. Identify patterns in what worked and what didn't — which unit placements led to wins or losses, which formations were effective, and where positioning mistakes were made.
3. Provide concrete, actionable strategy suggestions for improvement — reference specific unit types (A, B, C, D) and board positions (row, col) where relevant.
4. Keep feedback concise: 3-5 bullet points maximum.

Unit reference:
- A (1g): Attacks directly ahead, advances if clear.
- B (1g): Attacks diagonally left-ahead, advances if clear.
- C (1g): Attacks diagonally right-ahead, advances if clear.
- D (2g): Ranged — removes closest enemy by Manhattan distance.

Grid: 4 rows x 3 columns. LLM owns rows 0-1 (top), Human owns rows 2-3 (bottom).
LLM units move downward (increasing row). Human units move upward (decreasing row).

Respond ONLY with your bullet-point feedback. No preamble or sign-off."""

var _api_key: String = ""
var _http_request: HTTPRequest
var _is_requesting: bool = false
var _latest_feedback: String = ""


func _ready() -> void:
	_load_api_key()
	_http_request = HTTPRequest.new()
	_http_request.timeout = REQUEST_TIMEOUT_SECONDS
	_http_request.request_completed.connect(_on_request_completed)
	add_child(_http_request)


func has_api_key() -> bool:
	return not _api_key.is_empty()


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

	var user_message: String = _build_user_message(game_history, llm_reasoning_log)
	var request_body: Dictionary = _build_request_body(user_message)

	var headers: PackedStringArray = PackedStringArray([
		"Content-Type: application/json",
		"x-api-key: " + _api_key,
		"anthropic-version: " + ANTHROPIC_VERSION,
	])

	var json_body: String = JSON.stringify(request_body)
	var error: Error = _http_request.request(API_ENDPOINT, headers, HTTPClient.METHOD_POST, json_body)
	if error != OK:
		_is_requesting = false
		reflection_request_failed.emit("HTTPRequest.request() failed with error code: %d" % error)


func _load_api_key() -> void:
	var file := FileAccess.open(API_KEY_FILE_PATH, FileAccess.READ)
	if file == null:
		push_warning("ReflectionClient: No API key file found at %s. Reflection calls will fail." % API_KEY_FILE_PATH)
		return
	_api_key = file.get_as_text().strip_edges()
	file.close()
	if _api_key.is_empty():
		push_warning("ReflectionClient: API key file is empty.")


func _build_request_body(user_message: String) -> Dictionary:
	return {
		"model": API_MODEL,
		"max_tokens": MAX_TOKENS,
		"system": SYSTEM_PROMPT,
		"messages": [
			{
				"role": "user",
				"content": user_message,
			}
		],
	}


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

	parts.append("Based on the above replays and reasoning, provide 3-5 bullet points of strategic feedback for the LLM player to improve.")

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


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_is_requesting = false

	if result != HTTPRequest.RESULT_SUCCESS:
		reflection_request_failed.emit("HTTP request failed with result code: %d" % result)
		return

	if response_code != 200:
		var error_text: String = body.get_string_from_utf8()
		reflection_request_failed.emit("API returned status %d: %s" % [response_code, error_text.left(500)])
		return

	var json_string: String = body.get_string_from_utf8()
	var json := JSON.new()
	var parse_error: Error = json.parse(json_string)
	if parse_error != OK:
		reflection_request_failed.emit("Failed to parse API response JSON: %s" % json.get_error_message())
		return

	var response: Dictionary = json.data
	var feedback: String = _extract_feedback_text(response)

	if feedback.is_empty():
		reflection_request_failed.emit("No text content found in API response.")
		return

	_latest_feedback = feedback
	print("ReflectionClient: Feedback received:\n" + feedback)
	reflection_response_received.emit(feedback)


func _extract_feedback_text(response: Dictionary) -> String:
	var content_blocks: Array = response.get("content", [])
	var feedback_text: String = ""

	for block in content_blocks:
		var block_dict: Dictionary = block as Dictionary
		var block_type: String = block_dict.get("type", "")
		if block_type == "text":
			feedback_text += block_dict.get("text", "")

	return feedback_text.strip_edges()
