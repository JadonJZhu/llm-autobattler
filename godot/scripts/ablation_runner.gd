class_name AblationRunner
extends Node
## Iterates all prompt-mode configurations across all puzzle scenarios.
## Delegates per-puzzle attempts to PuzzleRunner via orchestration signals.

signal puzzle_requested(config: LlmModeConfig, scenario, max_attempts: int)
signal ablation_progress(config_label: String, puzzle_id: String, completed: int, total: int)
signal ablation_completed(results: Dictionary)

var max_attempts_per_puzzle: int = 10

var _is_running: bool = false
var _configs: Array[LlmModeConfig] = []
var _puzzles: Array = []
var _results: Array[Dictionary] = []
var _current_config_index: int = 0
var _current_puzzle_index: int = 0


func start(puzzles: Array, attempt_limit: int = 10) -> bool:
	if puzzles.is_empty():
		push_error("AblationRunner: Cannot start with empty puzzle list.")
		return false

	_puzzles = puzzles
	_configs = _build_mode_configs()
	_results.clear()
	_current_config_index = 0
	_current_puzzle_index = 0
	max_attempts_per_puzzle = maxi(1, attempt_limit)
	_is_running = true
	_emit_current_request()
	return true


func stop() -> void:
	_is_running = false


func is_running() -> bool:
	return _is_running


func record_puzzle_summary(summary: Dictionary) -> void:
	if not _is_running:
		return

	_results.append(summary.duplicate(true))
	var completed_count: int = _results.size()
	var total_count: int = _configs.size() * _puzzles.size()
	ablation_progress.emit(
		str(summary.get("config", "")),
		str(summary.get("puzzle_id", "")),
		completed_count,
		total_count
	)

	_advance_indices()
	if _current_config_index >= _configs.size():
		_is_running = false
		ablation_completed.emit(_build_final_results())
		return

	_emit_current_request()


func _emit_current_request() -> void:
	puzzle_requested.emit(
		_configs[_current_config_index],
		_puzzles[_current_puzzle_index],
		max_attempts_per_puzzle
	)


func _advance_indices() -> void:
	_current_puzzle_index += 1
	if _current_puzzle_index >= _puzzles.size():
		_current_puzzle_index = 0
		_current_config_index += 1


func _build_final_results() -> Dictionary:
	var aggregate_by_config: Dictionary = {}
	for config in _configs:
		var label: String = config.get_label()
		aggregate_by_config[label] = {
			"config": label,
			"puzzles_total": 0,
			"puzzles_solved": 0,
			"sum_attempts_needed": 0,
			"mean_attempts_solved_only": 0.0,
			"pass_rate": 0.0,
		}

	for result in _results:
		var label: String = str(result.get("config", ""))
		if not aggregate_by_config.has(label):
			continue
		var bucket: Dictionary = aggregate_by_config[label]
		bucket["puzzles_total"] = int(bucket["puzzles_total"]) + 1
		if bool(result.get("solved", false)):
			bucket["puzzles_solved"] = int(bucket["puzzles_solved"]) + 1
			bucket["sum_attempts_needed"] = int(bucket["sum_attempts_needed"]) + int(
				result.get("attempts_needed", 0)
			)
		aggregate_by_config[label] = bucket

	for label in aggregate_by_config.keys():
		var bucket: Dictionary = aggregate_by_config[label]
		var solved: int = int(bucket["puzzles_solved"])
		var total: int = int(bucket["puzzles_total"])
		var attempts_sum: int = int(bucket["sum_attempts_needed"])
		if solved > 0:
			bucket["mean_attempts_solved_only"] = float(attempts_sum) / float(solved)
		if total > 0:
			bucket["pass_rate"] = float(solved) / float(total)
		aggregate_by_config[label] = bucket

	return {
		"max_attempts_per_puzzle": max_attempts_per_puzzle,
		"puzzle_count": _puzzles.size(),
		"config_count": _configs.size(),
		"results": _results.duplicate(true),
		"by_config": aggregate_by_config,
	}


func _build_mode_configs() -> Array[LlmModeConfig]:
	var configs: Array[LlmModeConfig] = []
	for instructions_on in [false, true]:
		for examples_on in [false, true]:
			for reflection_on in [false, true]:
				var config := LlmModeConfig.new()
				config.instructions_enabled = instructions_on
				config.examples_enabled = examples_on
				config.reflection_enabled = reflection_on
				configs.append(config)
	return configs
