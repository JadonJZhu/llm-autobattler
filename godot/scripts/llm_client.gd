extends Node
## Autoload singleton that communicates with the Claude Opus 4.6 API.
## Builds prompts for the autochess prep phase and parses PLACE responses.

signal llm_prep_response_received(unit_type: Unit.UnitType, grid_pos: Vector2i)
signal llm_request_failed(error_message: String)

const API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const API_MODEL: String = "claude-opus-4-6"
const ANTHROPIC_VERSION: String = "2023-06-01"
const API_KEY_FILE_PATH: String = "res://api_key.txt"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096

const ROWS: int = 4
const COLS: int = 3

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


func request_llm_prep(board: GameBoard, llm_shop: Shop, turn_number: int,
		previous_game_replay: Dictionary) -> void:
	if _is_requesting:
		push_warning("LlmClient: Request already in progress.")
		return
	if not has_api_key():
		llm_request_failed.emit("No API key loaded.")
		return

	_is_requesting = true
	var system_prompt: String = _build_system_prompt()
	var user_message: String = _build_user_message(board, llm_shop, turn_number, previous_game_replay)
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
	return "You are playing a 4x3 autochess game. The board has 4 rows and 3 columns.
You control the top 2 rows (rows 0-1). Your opponent (Human) controls the bottom 2 rows (rows 2-3).

GAME PHASES:
1. PREPARATION: You and the human alternate placing units. You place first each round.
2. BATTLE: Units fight automatically (you don't control this phase).

UNIT TYPES AND COSTS:
- A (1 gold): Attacks the cell directly ahead. If enemy there, removes it. Otherwise advances forward one cell.
- B (1 gold): Attacks diagonally left-ahead. If on leftmost column (col 0), cannot attack. Otherwise advances forward.
- C (1 gold): Attacks diagonally right-ahead. If on rightmost column (col 2), cannot attack. Otherwise advances forward.
- D (2 gold): Ranged unit. Removes the closest enemy by Manhattan distance (ties broken left-to-right, then top-to-bottom).

BATTLE MECHANICS:
- Your units face DOWN (toward higher rows). Human units face UP (toward lower rows).
- Turn order scan: A units are checked first, then B, then C, then D. Within same type, earlier-placed units are checked first.
- If the highest-priority unit is blocked and cannot act, the scan continues to the next unit in priority order until one can act.
- If no unit on that side can act, that side's step is skipped.
- Units that advance past the opponent's edge ESCAPE and earn 1 point.
- Battle alternates: you go first, then human, repeat until neither side can take any action.
- Score is: units still on board + escaped units. Higher score wins. Equal scores are a tie.

STRATEGY TIPS:
- A units are strong direct attackers but predictable.
- B and C units can attack diagonally, useful for flanking.
- D units are expensive (2 gold) but can snipe the most threatening enemy anywhere on the board.
- Escaping units is a valid way to score and can be better than chasing eliminations.
- Consider what the human might place and position your units to counter.

YOUR SHOP shows which unit types you can buy and your remaining gold.

RESPONSE FORMAT:
Think through your reasoning, then end your response with exactly this line:
PLACE: <type> (row, col)

Where <type> is A, B, C, or D, and row is 0 or 1 (your rows), col is 0, 1, or 2.
The PLACE line must be the last non-empty line of your response."


func _build_user_message(board: GameBoard, llm_shop: Shop, turn_number: int,
		previous_game_replay: Dictionary) -> String:
	var parts: PackedStringArray = PackedStringArray()

	parts.append("=== PREP TURN %d ===" % turn_number)
	parts.append("")
	parts.append("Current board state:")
	parts.append(BoardSerializer.serialize(board))
	parts.append("")
	parts.append("Your shop: %s" % llm_shop.get_purchase_summary())
	parts.append("")

	var replay_text: String = _format_game_replay(previous_game_replay)
	if not replay_text.is_empty():
		parts.append(replay_text)
		parts.append("")

	parts.append("Choose a unit to place on your side of the board (rows 0-1).")

	return "\n".join(parts)


func _format_game_replay(replay: Dictionary) -> String:
	if replay.is_empty():
		return ""

	var parts: PackedStringArray = PackedStringArray()
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


func _build_request_body(system_prompt: String, user_message: String) -> Dictionary:
	return {
		"model": API_MODEL,
		"max_tokens": MAX_TOKENS,
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
	var response_text: String = ""

	for block in content_blocks:
		var block_dict: Dictionary = block as Dictionary
		var block_type: String = block_dict.get("type", "")
		if block_type == "text":
			response_text += block_dict.get("text", "")

	print("LlmClient: Response text:\n" + response_text)

	var parse_result: Dictionary = _parse_place_command(response_text)
	if parse_result.is_empty():
		llm_request_failed.emit("Failed to parse PLACE command from LLM response.")
		return

	llm_prep_response_received.emit(parse_result["unit_type"], parse_result["position"])


func _parse_place_command(text: String) -> Dictionary:
	# Search for the LAST occurrence of PLACE: to handle LLM mentioning it in reasoning
	var search_pattern: String = "PLACE:"
	var last_index: int = text.rfind(search_pattern)
	if last_index == -1:
		push_error("LlmClient: No PLACE: command found in response.")
		return {}

	var after_tag: String = text.substr(last_index + search_pattern.length()).strip_edges()

	# Expected format: <type> (row, col)
	# Extract the type letter (first non-space character)
	var type_str: String = ""
	var paren_start: int = -1
	for i in range(after_tag.length()):
		var character: String = after_tag[i]
		if character == "(":
			paren_start = i
			break
		if character != " ":
			type_str += character

	type_str = type_str.strip_edges().to_upper()
	if type_str not in ["A", "B", "C", "D"]:
		push_error("LlmClient: Invalid unit type in PLACE command: '%s'" % type_str)
		return {}

	if paren_start == -1:
		push_error("LlmClient: No coordinates found in PLACE command.")
		return {}

	var paren_end: int = after_tag.find(")", paren_start)
	if paren_end == -1:
		push_error("LlmClient: Missing closing paren in PLACE command.")
		return {}

	var coord_text: String = after_tag.substr(paren_start + 1, paren_end - paren_start - 1)
	var parts: PackedStringArray = coord_text.split(",")
	if parts.size() != 2:
		push_error("LlmClient: Expected 2 coordinates, got %d." % parts.size())
		return {}

	var row_str: String = parts[0].strip_edges()
	var col_str: String = parts[1].strip_edges()
	if not row_str.is_valid_int() or not col_str.is_valid_int():
		push_error("LlmClient: Non-integer coordinates: '%s', '%s'" % [row_str, col_str])
		return {}

	var row: int = row_str.to_int()
	var col: int = col_str.to_int()

	# Validate LLM-side rows (0-1) and columns (0-2)
	if row < 0 or row > 1:
		push_error("LlmClient: Row %d is not on LLM side (must be 0 or 1)." % row)
		return {}
	if col < 0 or col >= COLS:
		push_error("LlmClient: Column %d is out of range (must be 0-%d)." % [col, COLS - 1])
		return {}

	var unit_type: Unit.UnitType = Unit.type_from_string(type_str)
	return {
		"unit_type": unit_type,
		"position": Vector2i(row, col),
	}
