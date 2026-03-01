extends Node
## Autoload singleton that communicates with the Claude Opus 4.6 API.
## Builds prompts from game state, sends HTTP requests, and parses coordinate responses.

signal llm_response_received(flip_pos: Vector2i, lock_pos: Vector2i, thinking_text: String)
signal llm_request_failed(error_message: String)

const API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const API_MODEL: String = "claude-opus-4-6"
const ANTHROPIC_VERSION: String = "2023-06-01"
const API_KEY_FILE_PATH: String = "res://api_key.txt"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096
const GRID_SIZE: int = 6

var _api_key: String = ""
var _http_request: HTTPRequest
var _is_requesting: bool = false


func _ready() -> void:
	_load_api_key()
	_http_request = HTTPRequest.new()
	_http_request.timeout = REQUEST_TIMEOUT_SECONDS
	_http_request.request_completed.connect(_on_request_completed)
	add_child(_http_request)


func has_api_key() -> bool:
	return not _api_key.is_empty()


func request_llm_turn(board: GameBoard, turn_number: int, log_entries: Array[Dictionary]) -> void:
	if _is_requesting:
		push_warning("LlmClient: Request already in progress.")
		return
	if not has_api_key():
		llm_request_failed.emit("No API key loaded.")
		return

	_is_requesting = true
	var system_prompt: String = _build_system_prompt()
	var user_message: String = _build_user_message(board, turn_number, log_entries)
	var request_body: Dictionary = _build_request_body(system_prompt, user_message)

	var headers: PackedStringArray = PackedStringArray([
		"Content-Type: application/json",
		"x-api-key: " + _api_key,
		"anthropic-version: " + ANTHROPIC_VERSION,
	])

	var json_body: String = JSON.stringify(request_body)
	var error: Error = _http_request.request(API_ENDPOINT, headers, HTTPClient.METHOD_POST, json_body)
	if error != OK:
		_is_requesting = false
		llm_request_failed.emit("HTTPRequest.request() failed with error code: %d" % error)


func _load_api_key() -> void:
	var file := FileAccess.open(API_KEY_FILE_PATH, FileAccess.READ)
	if file == null:
		push_warning("LlmClient: No API key file found at %s. LLM calls will fail." % API_KEY_FILE_PATH)
		return
	_api_key = file.get_as_text().strip_edges()
	file.close()
	if _api_key.is_empty():
		push_warning("LlmClient: API key file is empty.")


func _build_system_prompt() -> String:
	return "You are playing a 6x6 grid puzzle game. Your goal is to maximize a correctness score by flipping arrow tiles.

BOARD ELEMENTS:
- Arrow tiles show a direction: ^ (up), v (down), < (left), > (right)
- Arrows with \"L\" suffix are locked (e.g., \">L\")
- \"X\" and \"Y\" are fixed destination markers
- \".\" is an empty cell

YOUR TURN:
Each turn you must make exactly two moves:
1. FLIP: Choose one unlocked arrow tile to flip. Flipping reverses the arrow on its axis (^ becomes v, < becomes >).
2. LOCK: Choose one arrow tile (different from the flip target) to toggle its lock state. Locking a tile prevents the human from flipping it. Unlocking a previously locked tile frees it.

RULES:
- You receive a correctness score after each turn (higher is better).
- The human opponent gets one flip after your turn (on any unlocked arrow).
- Locked tiles cannot be flipped by the human but can be unlocked by you on a future turn.
- Your goal: reach the maximum correctness score.

STRATEGY TIPS:
- Track how your score changes after each move to infer which flips help.
- Use locks strategically to protect tiles you believe are in their correct orientation.
- The human will try to undo your progress.

RESPONSE FORMAT:
Think through your reasoning freely, then end your response with exactly these two lines:
FLIP: (row, col)
LOCK: (row, col)

Where row and col are zero-indexed integers matching the grid coordinates shown. The FLIP and LOCK lines must be the last two non-empty lines of your response."


func _build_user_message(board: GameBoard, turn_number: int, log_entries: Array[Dictionary]) -> String:
	var parts: PackedStringArray = PackedStringArray()

	parts.append("=== TURN %d ===" % turn_number)
	parts.append("")
	parts.append("Current board state:")
	parts.append(BoardSerializer.serialize(board))
	parts.append("")

	var score: int = board.get_correctness_score()
	var max_score: int = board.get_max_correctness_score()
	parts.append("Correctness score: %d / %d" % [score, max_score])
	parts.append("")

	if not log_entries.is_empty():
		parts.append("Turn history:")
		for entry: Dictionary in log_entries:
			parts.append(_format_log_entry(entry))
		parts.append("")

	parts.append("Choose your FLIP and LOCK targets.")

	return "\n".join(parts)


func _format_log_entry(entry: Dictionary) -> String:
	var actor: String = entry.get("actor", "unknown")
	var turn_num: int = entry.get("turn_number", 0)
	var score_val: int = entry.get("correctness_score", 0)

	if actor == "llm":
		var flip: Dictionary = entry.get("flip_position", {})
		var lock: Dictionary = entry.get("lock_position", {})
		return "  Turn %d (LLM): flipped (%d,%d), locked (%d,%d), score=%d" % [
			turn_num, flip.get("y", 0), flip.get("x", 0),
			lock.get("y", 0), lock.get("x", 0), score_val
		]
	elif actor == "human":
		var flip: Dictionary = entry.get("flip_position", {})
		return "  Turn %d (Human): flipped (%d,%d), score=%d" % [
			turn_num, flip.get("y", 0), flip.get("x", 0), score_val
		]
	return "  Turn %d: %s" % [turn_num, str(entry)]


func _build_request_body(system_prompt: String, user_message: String) -> Dictionary:
	return {
		"model": API_MODEL,
		"max_tokens": MAX_TOKENS,
		"thinking": {
			"type": "adaptive",
		},
		"system": system_prompt,
		"messages": [
			{
				"role": "user",
				"content": user_message,
			}
		],
	}


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_is_requesting = false

	if result != HTTPRequest.RESULT_SUCCESS:
		llm_request_failed.emit("HTTP request failed with result code: %d" % result)
		return

	if response_code != 200:
		var error_text: String = body.get_string_from_utf8()
		llm_request_failed.emit("API returned status %d: %s" % [response_code, error_text.left(500)])
		return

	var json_string: String = body.get_string_from_utf8()
	var json := JSON.new()
	var parse_error: Error = json.parse(json_string)
	if parse_error != OK:
		llm_request_failed.emit("Failed to parse API response JSON: %s" % json.get_error_message())
		return

	var response: Dictionary = json.data
	_process_api_response(response)


func _process_api_response(response: Dictionary) -> void:
	var content_blocks: Array = response.get("content", [])
	var thinking_text: String = ""
	var response_text: String = ""

	for block in content_blocks:
		var block_dict: Dictionary = block as Dictionary
		var block_type: String = block_dict.get("type", "")
		if block_type == "thinking":
			thinking_text += block_dict.get("thinking", "") + "\n"
		elif block_type == "text":
			response_text += block_dict.get("text", "")

	print("LlmClient: Thinking content:\n" + thinking_text)
	print("LlmClient: Response text:\n" + response_text)

	var parse_result: Dictionary = _parse_coordinates(response_text)
	if parse_result.is_empty():
		llm_request_failed.emit("Failed to parse FLIP/LOCK coordinates from LLM response.")
		return

	var flip_pos: Vector2i = parse_result["flip"]
	var lock_pos: Vector2i = parse_result["lock"]

	llm_response_received.emit(flip_pos, lock_pos, thinking_text)


func _parse_coordinates(text: String) -> Dictionary:
	var flip_pos: Vector2i = _extract_tagged_coordinate(text, "FLIP")
	var lock_pos: Vector2i = _extract_tagged_coordinate(text, "LOCK")

	if flip_pos == Vector2i(-1, -1) or lock_pos == Vector2i(-1, -1):
		push_error("LlmClient: Could not parse coordinates. FLIP=%s LOCK=%s" % [str(flip_pos), str(lock_pos)])
		return {}

	if flip_pos == lock_pos:
		push_error("LlmClient: FLIP and LOCK positions are the same: %s" % str(flip_pos))
		return {}

	return {"flip": flip_pos, "lock": lock_pos}


func _extract_tagged_coordinate(text: String, tag: String) -> Vector2i:
	# Search for the LAST occurrence of the tag to handle cases where
	# the LLM mentions coordinates earlier in its reasoning.
	var search_pattern: String = tag + ":"
	var last_index: int = text.rfind(search_pattern)
	if last_index == -1:
		return Vector2i(-1, -1)

	var after_tag: String = text.substr(last_index + search_pattern.length())
	var open_paren: int = after_tag.find("(")
	var close_paren: int = after_tag.find(")")
	if open_paren == -1 or close_paren == -1 or close_paren <= open_paren:
		return Vector2i(-1, -1)

	var coord_text: String = after_tag.substr(open_paren + 1, close_paren - open_paren - 1)
	var parts: PackedStringArray = coord_text.split(",")
	if parts.size() != 2:
		return Vector2i(-1, -1)

	var row_str: String = parts[0].strip_edges()
	var col_str: String = parts[1].strip_edges()
	if not row_str.is_valid_int() or not col_str.is_valid_int():
		return Vector2i(-1, -1)

	var row: int = row_str.to_int()
	var col: int = col_str.to_int()

	if row < 0 or row >= GRID_SIZE or col < 0 or col >= GRID_SIZE:
		return Vector2i(-1, -1)

	# Convert from (row, col) to Vector2i(col, row) to match internal representation
	return Vector2i(col, row)
