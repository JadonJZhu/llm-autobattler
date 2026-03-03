class_name LlmHttpBase
extends Node
## Shared HTTP infrastructure for communicating with the Claude API.
## Subclasses override _on_api_response_parsed() to handle the response text.

const API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const ANTHROPIC_VERSION: String = "2023-06-01"
const API_KEY_FILE_PATH: String = "res://api_key.txt"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096

var api_model: String = "claude-sonnet-4-6"
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
		_on_request_error(
			"HTTPRequest.request() failed with error code: %d" % error,
			{
				"is_api_error": true,
				"retryable": true,
				"status_code": 0,
				"suggested_delay_seconds": 0.0,
			}
		)


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
		"temperature": 0,
		"system": system_prompt,
		"messages": [
			{
				"role": "user",
				"content": user_message,
			}
		],
	}


func _on_request_completed(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray) -> void:
	_is_requesting = false

	if result != HTTPRequest.RESULT_SUCCESS:
		_on_request_error(
			"HTTP request failed with result code: %d" % result,
			{
				"is_api_error": true,
				"retryable": true,
				"status_code": 0,
				"suggested_delay_seconds": 0.0,
			}
		)
		return

	if response_code != 200:
		var error_text: String = body.get_string_from_utf8()
		var header_map: Dictionary = _headers_to_map(headers)
		var retry_after_seconds: float = _parse_retry_after_seconds(header_map)
		_on_request_error(
			"API returned status %d: %s" % [response_code, error_text.left(500)],
			{
				"is_api_error": true,
				"retryable": _is_retryable_status(response_code),
				"status_code": response_code,
				"retry_after_seconds": retry_after_seconds,
				"suggested_delay_seconds": retry_after_seconds,
			}
		)
		return

	var json_string: String = body.get_string_from_utf8()
	var json := JSON.new()
	var parse_error: Error = json.parse(json_string)
	if parse_error != OK:
		_on_request_error(
			"Failed to parse API response JSON: %s" % json.get_error_message(),
			{
				"is_api_error": true,
				"retryable": false,
				"status_code": 200,
				"suggested_delay_seconds": 0.0,
			}
		)
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


func _headers_to_map(headers: PackedStringArray) -> Dictionary:
	var parsed: Dictionary = {}
	for header_line in headers:
		var parts: PackedStringArray = String(header_line).split(":", false, 1)
		if parts.size() < 2:
			continue
		var key: String = String(parts[0]).strip_edges().to_lower()
		var value: String = String(parts[1]).strip_edges()
		if key.is_empty():
			continue
		parsed[key] = value
	return parsed


func _parse_retry_after_seconds(headers_map: Dictionary) -> float:
	if not headers_map.has("retry-after"):
		return 0.0
	var value: String = String(headers_map.get("retry-after", "")).strip_edges()
	if value.is_empty():
		return 0.0
	if value.is_valid_float():
		return maxf(0.0, float(value))
	if value.is_valid_int():
		return maxf(0.0, float(int(value)))
	return 0.0


func _is_retryable_status(status_code: int) -> bool:
	if status_code == 429:
		return true
	return status_code >= 500 and status_code <= 599


## Override in subclasses to handle successful API response text.
func _on_api_response_parsed(_response_text: String) -> void:
	push_error("%s: _on_api_response_parsed not implemented." % _get_client_name())


## Override in subclasses to handle request errors.
func _on_request_error(_error_message: String, _error_meta: Dictionary = {}) -> void:
	push_error("%s: _on_request_error not implemented." % _get_client_name())


## Override to return a descriptive name for log messages.
func _get_client_name() -> String:
	return "LlmHttpBase"


## Override in subclasses to choose a different model.
func _get_api_model() -> String:
	return api_model
