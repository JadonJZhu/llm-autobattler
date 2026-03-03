class_name LlmHttpBase
extends Node
## Shared HTTP infrastructure for communicating with the Claude API.
## Subclasses override _on_api_response_parsed() to handle the response text.

const API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const ANTHROPIC_VERSION: String = "2023-06-01"
const API_KEY_FILE_PATH: String = "res://api_key.txt"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096

var api_model: String = "claude-opus-4-6"
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


func _send_request(system_prompt: String, user_message: String) -> void:
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
		_on_request_error("HTTPRequest.request() failed with error code: %d" % error)


func _load_api_key() -> void:
	var file := FileAccess.open(API_KEY_FILE_PATH, FileAccess.READ)
	if file == null:
		push_warning("%s: No API key file found at %s." % [_get_client_name(), API_KEY_FILE_PATH])
		return
	_api_key = file.get_as_text().strip_edges()
	file.close()
	if _api_key.is_empty():
		push_warning("%s: API key file is empty." % _get_client_name())


func _build_request_body(system_prompt: String, user_message: String) -> Dictionary:
	return {
		"model": _get_api_model(),
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
		_on_request_error("HTTP request failed with result code: %d" % result)
		return

	if response_code != 200:
		var error_text: String = body.get_string_from_utf8()
		_on_request_error("API returned status %d: %s" % [response_code, error_text.left(500)])
		return

	var json_string: String = body.get_string_from_utf8()
	var json := JSON.new()
	var parse_error: Error = json.parse(json_string)
	if parse_error != OK:
		_on_request_error("Failed to parse API response JSON: %s" % json.get_error_message())
		return

	var response: Dictionary = json.data
	var response_text: String = _extract_response_text(response)
	print("%s: Response text:\n%s" % [_get_client_name(), response_text])
	_on_api_response_parsed(response_text)


func _extract_response_text(response: Dictionary) -> String:
	var content_blocks: Array = response.get("content", [])
	var response_text: String = ""
	for block in content_blocks:
		var block_dict: Dictionary = block as Dictionary
		var block_type: String = block_dict.get("type", "")
		if block_type == "text":
			response_text += block_dict.get("text", "")
	return response_text


## Override in subclasses to handle successful API response text.
func _on_api_response_parsed(_response_text: String) -> void:
	push_error("%s: _on_api_response_parsed not implemented." % _get_client_name())


## Override in subclasses to handle request errors.
func _on_request_error(_error_message: String) -> void:
	push_error("%s: _on_request_error not implemented." % _get_client_name())


## Override to return a descriptive name for log messages.
func _get_client_name() -> String:
	return "LlmHttpBase"


## Override in subclasses to choose a different model.
func _get_api_model() -> String:
	return api_model
