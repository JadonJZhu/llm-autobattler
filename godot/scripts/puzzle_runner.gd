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
## When true a puzzle plays max_attempts attempts whatever their outcome; when
## false it stops at the first solve. Under stop-on-solve the number of attempts
## a puzzle contributes is decided by the outcome being measured, so an easy
## puzzle contributes one solved attempt and a hard one contributes a full cap of
## failures. Any per-attempt statistic drawn across puzzles then reads a slope
## that the stopping rule put there.
var play_all_attempts: bool = false
var mode_config: LlmModeConfig
var scenario

var _is_running: bool = false
var _attempt_results: Array[Dictionary] = []
var _remaining_opponent_placements: Array[Dictionary] = []


func start_puzzle(next_scenario, next_mode_config: LlmModeConfig,
		attempt_limit: int = 10, play_every_attempt: bool = false) -> void:
	scenario = next_scenario
	mode_config = next_mode_config
	max_attempts = maxi(1, attempt_limit)
	play_all_attempts = play_every_attempt
	current_attempt = 1
	_attempt_results.clear()
	_is_running = true
	_reset_opponent_queue()
	GameLogger.clear_history()
	_begin_attempt_logging()
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

	var stop_here: bool = current_attempt >= max_attempts
	if solved and not play_all_attempts:
		stop_here = true
	if stop_here:
		_is_running = false
		puzzle_completed.emit(_build_summary())
		return false

	current_attempt += 1
	_reset_opponent_queue()
	_begin_attempt_logging()
	return true


func _begin_attempt_logging() -> void:
	## This runner holds the only copy of the three values that name an attempt
	## and of the stopping rule it is played under, so it is the only place that
	## can put them in the game log. It runs on every attempt, not just the first,
	## because attempt_started is emitted only for attempt 1 and the controller
	## restarts the rest directly.
	GameLogger.begin_puzzle_attempt(
		scenario.id, mode_config.get_label(), current_attempt, play_all_attempts
	)


func _reset_opponent_queue() -> void:
	_remaining_opponent_placements = scenario.opponent_placements.duplicate(true)


func _build_summary() -> Dictionary:
	## "solved" is whether any attempt solved the puzzle and "attempts_needed" is
	## the first attempt that did, so a puzzle solved on attempt 2 of 5 stays
	## solved in 2 even though attempts 3 to 5 were played and lost. Reading both
	## off the recorded attempts rather than off the one that ended the puzzle is
	## what makes them mean the same thing in both modes: under stop-on-solve only
	## the final attempt can be a solve, so this is that same answer.
	var solved: bool = false
	var attempts_needed: int = max_attempts
	for result in _attempt_results:
		if result.get("solved_this_attempt", false):
			solved = true
			attempts_needed = int(result.get("attempt", max_attempts))
			break

	return {
		"puzzle_id": scenario.id,
		"difficulty": scenario.difficulty,
		"config": mode_config.get_label(),
		"solved": solved,
		"attempts_needed": attempts_needed,
		"max_attempts": max_attempts,
		"attempt_scores": _attempt_results.duplicate(true),
	}
