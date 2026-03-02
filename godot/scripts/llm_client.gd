extends Node
## Autoload singleton that communicates with the Claude Opus 4.6 API.
## Owns API key loading, request dispatch, and response transport.

signal llm_prep_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i)
signal llm_request_failed(error_message: String)
signal llm_reasoning_captured(reasoning_text: String)

const API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const API_MODEL: String = "claude-opus-4-6"
const ANTHROPIC_VERSION: String = "2023-06-01"
const API_KEY_FILE_PATH: String = "res://api_key.txt"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096

var _api_key: String = ""
var _http_request: HTTPRequest
var _is_requesting: bool = false
var _prompt_builder: LlmPromptBuilder = LlmPromptBuilder.new()
var _response_parser: LlmResponseParser = LlmResponseParser.new()
var _mode_config: LlmModeConfig = LlmModeConfig.new()
var _reflection_feedback: String = ""


func _ready() -> void:
	_load_api_key()
	_http_request = HTTPRequest.new()
	_http_request.timeout = REQUEST_TIMEOUT_SECONDS
	_http_request.request_completed.connect(_on_request_completed)
	add_child(_http_request)


func has_api_key() -> bool:
	return not _api_key.is_empty()


func set_mode_config(config: LlmModeConfig) -> void:
	_mode_config = config


func set_reflection_feedback(feedback: String) -> void:
	_reflection_feedback = feedback


func request_llm_prep(board: GameBoard, llm_shop: Shop, turn_number: int,
		game_history: Array[Dictionary]) -> void:
	if _is_requesting:
		push_warning("LlmClient: Request already in progress.")
		return
	if not has_api_key():
		llm_request_failed.emit("No API key loaded.")
		return

	_is_requesting = true
	var system_prompt: String = _prompt_builder.build_system_prompt(
		_mode_config, _reflection_feedback
	)
	var user_message: String = _prompt_builder.build_user_message(
		board,
		llm_shop,
		turn_number,
		game_history,
		_mode_config
	)
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

	# Extract reasoning (everything before the PLACE line)
	var place_index: int = response_text.rfind("PLACE:")
	var reasoning_text: String = ""
	if place_index > 0:
		reasoning_text = response_text.left(place_index).strip_edges()
	elif place_index == -1:
		reasoning_text = response_text.strip_edges()
	if not reasoning_text.is_empty():
		llm_reasoning_captured.emit(reasoning_text)

	var parse_result: Dictionary = _response_parser.parse_place_command(response_text)
	if parse_result.is_empty():
		llm_request_failed.emit("Failed to parse PLACE command from LLM response.")
		return

	llm_prep_response_received.emit(parse_result["unit_type"], parse_result["position"])
