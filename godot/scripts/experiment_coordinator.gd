class_name ExperimentCoordinator
extends Node
## Manages LLM-vs-LLM experiment mode: human-side LLM adapter, fallback placement,
## experiment runner lifecycle, and trial results. Keeps GameController focused on
## core game flow.

signal experiment_status_updated(message: String)
signal experiment_ended(results: Dictionary)
signal human_llm_placement_ready(unit_type: UnitData.UnitType, grid_pos: Vector2i)
signal human_llm_placement_failed()

var experiment_mode: bool = false

var _experiment_runner: ExperimentRunner
var _human_llm_adapter: LlmPlayerAdapter
var _experiment_logger: ExperimentLogger = ExperimentLogger.new()


func _ready() -> void:
	_experiment_runner = ExperimentRunner.new()
	_experiment_runner.trial_completed.connect(_on_trial_completed)
	add_child(_experiment_runner)

	_human_llm_adapter = LlmPlayerAdapter.new()
	_human_llm_adapter.human_llm_response_received.connect(_on_human_llm_response_received)
	_human_llm_adapter.human_llm_request_failed.connect(_on_human_llm_request_failed)
	add_child(_human_llm_adapter)


func start_experiment(llm_cfg: LlmModeConfig, human_cfg: LlmModeConfig,
		num_games: int = 30) -> void:
	experiment_mode = true
	_human_llm_adapter.set_mode_config(human_cfg)
	GameLogger.clear_history()
	_experiment_logger.clear()
	_experiment_runner.start_trial(llm_cfg, human_cfg, num_games)


func stop_experiment() -> void:
	experiment_mode = false
	_experiment_runner.stop_trial()


func is_experiment_running() -> bool:
	return experiment_mode and _experiment_runner.is_running()


func record_game_result(winner_text: String, score_data: Dictionary,
		battle_step_count: int) -> bool:
	## Records a game result during an experiment. Returns true if experiment should
	## continue (i.e. still running after recording).
	if not is_experiment_running():
		return false

	var outcome: Dictionary = score_data.duplicate()
	outcome["winner"] = winner_text
	outcome["battle_steps"] = battle_step_count
	_experiment_runner.record_game_result(outcome)
	_experiment_logger.log_game(
		_experiment_runner.current_game,
		_experiment_runner.llm_config.get_label(),
		_experiment_runner.human_config.get_label(),
		outcome
	)
	experiment_status_updated.emit(
		"[Experiment %s] %s | LLM %d — Human %d" % [
			_experiment_runner.get_progress(), winner_text,
			int(score_data.get("llm_score", 0)),
			int(score_data.get("human_score", 0)),
		]
	)
	return _experiment_runner.is_running()


func trigger_human_llm_turn(board: GameBoard, human_shop: Shop,
		turn_number: int) -> void:
	if _human_llm_adapter.has_api_key():
		experiment_status_updated.emit("Human (LLM) is thinking...")
		_human_llm_adapter.request_human_llm_prep(
			board, human_shop, turn_number, GameLogger.get_game_history()
		)
	else:
		_apply_fallback_human_llm_prep(board, human_shop)


func _apply_fallback_human_llm_prep(board: GameBoard, human_shop: Shop) -> void:
	var affordable_types: Array[UnitData.UnitType] = []
	for unit_type in human_shop.available_types:
		if human_shop.can_afford(unit_type):
			affordable_types.append(unit_type)
	if affordable_types.is_empty():
		push_warning("Human LLM has no affordable units. Skipping turn.")
		experiment_status_updated.emit("Human LLM has no valid moves. Skipping.")
		human_llm_placement_failed.emit()
		return

	var empty_positions: Array[Vector2i] = board.get_empty_positions_for(UnitData.Owner.HUMAN)
	if empty_positions.is_empty():
		push_warning("Human LLM has no empty positions. Skipping turn.")
		experiment_status_updated.emit("Human LLM has no space. Skipping.")
		human_llm_placement_failed.emit()
		return

	var chosen_type: UnitData.UnitType = affordable_types[randi() % affordable_types.size()]
	var chosen_pos: Vector2i = empty_positions[randi() % empty_positions.size()]
	human_llm_placement_ready.emit(chosen_type, chosen_pos)


func _on_human_llm_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i) -> void:
	human_llm_placement_ready.emit(unit_type, grid_pos)


func _on_human_llm_request_failed(error_message: String) -> void:
	push_error("Human LLM request failed: " + error_message)
	experiment_status_updated.emit("Human LLM error. Using random placement.")
	human_llm_placement_failed.emit()


func _on_trial_completed(results: Dictionary) -> void:
	experiment_mode = false
	var filename: String = "experiment_%s_vs_%s.json" % [
		results.get("llm_config_label", "unknown"),
		results.get("human_config_label", "unknown"),
	]
	_experiment_logger.save_log(filename)
	experiment_ended.emit(results)
