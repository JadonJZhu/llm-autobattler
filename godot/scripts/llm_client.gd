extends LlmHttpBase
## Autoload singleton that communicates with the Claude API for the LLM player.
## Extends LlmHttpBase for shared HTTP infrastructure.

signal llm_prep_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i)
signal llm_request_failed(error_message: String, is_api_error: bool, error_meta: Dictionary)
signal llm_reasoning_captured(reasoning_text: String)

var _prompt_builder: LlmPromptBuilder
var _response_parser: LlmResponseParser
var _mode_config: LlmModeConfig = LlmModeConfig.new()
var _reflection_feedback: String = ""


func _ready() -> void:
	super._ready()
	if _prompt_builder == null:
		_prompt_builder = LlmPromptBuilder.new()
	if _response_parser == null:
		_response_parser = LlmResponseParser.new()


func set_prompt_builder(builder: LlmPromptBuilder) -> void:
	_prompt_builder = builder


func set_response_parser(parser: LlmResponseParser) -> void:
	_response_parser = parser


func set_mode_config(config: LlmModeConfig) -> void:
	_mode_config = config


func set_reflection_feedback(feedback: String) -> void:
	_reflection_feedback = feedback


func request_llm_prep(board: GameBoard, llm_shop: Shop, human_shop: Shop,
		turn_number: int, game_history: Array[Dictionary]) -> void:
	if _is_requesting:
		push_warning("LlmClient: Request already in progress.")
		return
	if not has_api_key():
		llm_request_failed.emit("No API key loaded.", false)
		return

	_is_requesting = true
	var system_prompt: String = _prompt_builder.build_system_prompt(
		_mode_config, _reflection_feedback
	)
	var user_message: String = _prompt_builder.build_user_message(
		board, llm_shop, human_shop, turn_number, game_history, _mode_config
	)
	_send_request(system_prompt, user_message)


func _on_api_response_parsed(response_text: String) -> void:
	# Extract reasoning (everything before the PLACE line)
	var place_index: int = response_text.rfind("PLACE:")
	var reasoning_text: String = ""
	if place_index >= 0:
		reasoning_text = response_text.left(place_index).strip_edges()
	elif place_index == -1:
		reasoning_text = response_text.strip_edges()
	if not reasoning_text.is_empty():
		llm_reasoning_captured.emit(reasoning_text)

	var parse_result: Dictionary = _response_parser.parse_place_command(response_text)
	if parse_result.is_empty():
		llm_request_failed.emit("Failed to parse PLACE command from LLM response.", false)
		return

	llm_prep_response_received.emit(parse_result["unit_type"], parse_result["position"])


func _on_request_error(error_message: String, error_meta: Dictionary = {}) -> void:
	var is_api_error: bool = bool(error_meta.get("is_api_error", true))
	llm_request_failed.emit(error_message, is_api_error, error_meta)


func _get_client_name() -> String:
	return "LlmClient"
