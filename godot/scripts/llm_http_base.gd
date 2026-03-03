class_name LlmHttpBase
extends Node
## Shared HTTP infrastructure for LLM API communication.
## Supports Anthropic and OpenAI-compatible API formats.
## Subclasses override _on_api_response_parsed() to handle the response text.
##
## Configuration via environment variables (all optional):
##   LLM_API_KEY       — API key
##   LLM_API_ENDPOINT  — Full URL for chat completions endpoint
##   LLM_API_MODEL     — Model identifier string
##   LLM_API_FORMAT    — "anthropic" or "openai"

const DEFAULT_API_ENDPOINT: String = "https://api.anthropic.com/v1/messages"
const DEFAULT_API_MODEL: String = "claude-sonnet-4-6"
const DEFAULT_API_FORMAT: String = "anthropic"
const ANTHROPIC_VERSION: String = "2023-06-01"
const REQUEST_TIMEOUT_SECONDS: float = 120.0
const MAX_TOKENS: int = 4096

var api_model: String = DEFAULT_API_MODEL
var _api_endpoint: String = DEFAULT_API_ENDPOINT
var _api_format: String = DEFAULT_API_FORMAT
var _api_key: String = ""
var _http_request: HTTPRequest
var _is_requesting: bool = false


func _ready() -> void:
	_load_config()
	_load_api_key()
	_http_request = HTTPRequest.new()
	_http_request.timeout = REQUEST_TIMEOUT_SECONDS
	_http_request.request_completed.connect(_on_request_completed)
	add_child(_http_request)


func has_api_key() -> bool:
	return not _api_key.is_empty()


func _load_config() -> void:
	var env_endpoint: String = OS.get_environment("LLM_API_ENDPOINT")
	if not env_endpoint.is_empty():
		_api_endpoint = env_endpoint

	var env_model: String = OS.get_environment("LLM_API_MODEL")
	if not env_model.is_empty():
		api_model = env_model

	var env_format: String = OS.get_environment("LLM_API_FORMAT").to_lower()
	if env_format == "anthropic" or env_format == "openai":
		_api_format = env_format

	print("%s: Config — endpoint=%s  model=%s  format=%s" % [
		_get_client_name(), _api_endpoint, api_model, _api_format
	])


func _load_api_key() -> void:
	var env_key: String = OS.get_environment("LLM_API_KEY")
	if not env_key.is_empty():
		_api_key = env_key
		return

	push_warning("%s: No API key found (set LLM_API_KEY env var)." % _get_client_name())


func _send_request(system_prompt: String, user_message: String) -> void:
	var request_body: Dictionary = _build_request_body(system_prompt, user_message)
	var headers: PackedStringArray = _build_headers()
	var json_body: String = JSON.stringify(request_body)
	var error: Error = _http_request.request(_api_endpoint, headers, HTTPClient.METHOD_POST, json_body)
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


func _build_headers() -> PackedStringArray:
	if _api_format == "openai":
		return PackedStringArray([
			"Content-Type: application/json",
			"Authorization: Bearer " + _api_key,
		])
	else:
		return PackedStringArray([
			"Content-Type: application/json",
			"x-api-key: " + _api_key,
			"anthropic-version: " + ANTHROPIC_VERSION,
		])


func _build_request_body(system_prompt: String, user_message: String) -> Dictionary:
	if _api_format == "openai":
		return {
			"model": _get_api_model(),
			# Newer OpenAI models (e.g., o-series) require max_completion_tokens.
			"max_completion_tokens": MAX_TOKENS,
			"messages": [
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_message},
			],
		}
	else:
		return {
			"model": _get_api_model(),
			"max_tokens": MAX_TOKENS,
			"temperature": 0,
			"system": system_prompt,
			"messages": [
				{"role": "user", "content": user_message},
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
	if _api_format == "openai":
		var choices: Array = response.get("choices", [])
		if choices.is_empty():
			return ""
		var first_choice: Dictionary = choices[0] as Dictionary
		var message: Dictionary = first_choice.get("message", {})
		return message.get("content", "")
	else:
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
