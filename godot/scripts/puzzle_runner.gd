class_name PuzzleRunner
extends Node
## Runs a single puzzle scenario for one LLM mode configuration across attempts.
## Keeps attempt state and scripted opponent placement queue.

signal puzzle_started(scenario_id: String, config_label: String)
signal attempt_started(scenario_id: String, attempt_number: int, max_attempts: int)
signal attempt_completed(result: Dictionary)
signal puzzle_completed(summary: Dictionary)

var current_attempt: int = 0
var max_attempts: int = 10
var mode_config: LlmModeConfig
var scenario

var _is_running: bool = false
var _attempt_results: Array[Dictionary] = []
var _remaining_opponent_placements: Array[Dictionary] = []


func start_puzzle(next_scenario, next_mode_config: LlmModeConfig,
		attempt_limit: int = 10) -> void:
	scenario = next_scenario
	mode_config = next_mode_config
	max_attempts = maxi(1, attempt_limit)
	current_attempt = 1
	_attempt_results.clear()
	_is_running = true
	_reset_opponent_queue()
	GameLogger.clear_history()
	puzzle_started.emit(scenario.id, mode_config.get_label())
	attempt_started.emit(scenario.id, current_attempt, max_attempts)


func stop() -> void:
	_is_running = false


func is_running() -> bool:
	return _is_running


func has_pending_opponent_placements() -> bool:
	return not _remaining_opponent_placements.is_empty()


func get_opponent_queue_snapshot() -> Array[Dictionary]:
	return _remaining_opponent_placements.duplicate(true)


func consume_next_opponent_placement() -> Dictionary:
	if _remaining_opponent_placements.is_empty():
		return {}
	return _remaining_opponent_placements.pop_front()


func record_attempt_result(winner, score_data: Dictionary, battle_step_count: int) -> bool:
	if not _is_running:
		return false

	var winner_label: String
	if winner == null:
		winner_label = "Tie"
	elif winner == UnitData.Owner.LLM:
		winner_label = "LLM"
	else:
		winner_label = "Human"

	var llm_score: int = int(score_data.get("llm_score", 0))
	var opponent_score: int = int(score_data.get("human_score", 0))
	var solved: bool = llm_score > opponent_score

	var result: Dictionary = {
		"scenario_id": scenario.id,
		"attempt": current_attempt,
		"winner": winner_label,
		"llm_score": llm_score,
		"opponent_score": opponent_score,
		"llm_remaining": int(score_data.get("llm_remaining", 0)),
		"opponent_remaining": int(score_data.get("human_remaining", 0)),
		"llm_escaped": int(score_data.get("llm_escaped", 0)),
		"opponent_escaped": int(score_data.get("human_escaped", 0)),
		"battle_steps": battle_step_count,
		"solved_this_attempt": solved,
	}
	_attempt_results.append(result)
	attempt_completed.emit(result)

	if solved or current_attempt >= max_attempts:
		_is_running = false
		puzzle_completed.emit(_build_summary(solved))
		return false

	current_attempt += 1
	_reset_opponent_queue()
	return true


func _reset_opponent_queue() -> void:
	_remaining_opponent_placements = scenario.opponent_placements.duplicate(true)


func _build_summary(solved: bool) -> Dictionary:
	var attempts_needed: int = max_attempts
	if solved:
		for result in _attempt_results:
			if result.get("solved_this_attempt", false):
				attempts_needed = int(result.get("attempt", max_attempts))
				break

	return {
		"puzzle_id": scenario.id,
		"description": scenario.description,
		"difficulty": scenario.difficulty,
		"config": mode_config.get_label(),
		"solved": solved,
		"attempts_needed": attempts_needed,
		"max_attempts": max_attempts,
		"attempt_scores": _attempt_results.duplicate(true),
	}
