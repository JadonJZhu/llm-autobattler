class_name ExperimentRunner
extends Node
## Orchestrates automated LLM-vs-LLM game sequences.
## Acts as a state tracker — does not own game flow directly.
## GameController checks is_running() to decide behavior.

signal trial_completed(results: Dictionary)
signal game_completed(game_number: int, outcome: Dictionary)

var llm_config: LlmModeConfig
var human_config: LlmModeConfig
var games_per_trial: int = 30
var current_game: int = 0

var _is_running: bool = false
var _results: Array[Dictionary] = []


func start_trial(llm_cfg: LlmModeConfig, human_cfg: LlmModeConfig, num_games: int = 30) -> void:
	llm_config = llm_cfg
	human_config = human_cfg
	games_per_trial = num_games
	current_game = 0
	_results.clear()
	_is_running = true


func stop_trial() -> void:
	_is_running = false


func record_game_result(outcome: Dictionary) -> void:
	current_game += 1
	_results.append(outcome)
	game_completed.emit(current_game, outcome)

	if current_game >= games_per_trial:
		_is_running = false
		var results: Dictionary = _compile_results()
		trial_completed.emit(results)


func is_running() -> bool:
	return _is_running


func get_progress() -> String:
	return "Game %d / %d" % [current_game, games_per_trial]


func _compile_results() -> Dictionary:
	var llm_wins: int = 0
	var human_wins: int = 0
	var ties: int = 0
	var llm_total_score: int = 0
	var human_total_score: int = 0
	var total_battle_steps: int = 0

	for result: Dictionary in _results:
		var llm_score: int = result.get("llm_score", 0)
		var human_score: int = result.get("human_score", 0)
		llm_total_score += llm_score
		human_total_score += human_score
		total_battle_steps += result.get("battle_steps", 0)

		if llm_score > human_score:
			llm_wins += 1
		elif human_score > llm_score:
			human_wins += 1
		else:
			ties += 1

	var games_played: int = _results.size()
	var average_game_length: float = 0.0
	if games_played > 0:
		average_game_length = float(total_battle_steps) / float(games_played)

	return {
		"llm_wins": llm_wins,
		"human_wins": human_wins,
		"ties": ties,
		"llm_total_score": llm_total_score,
		"human_total_score": human_total_score,
		"average_game_length": average_game_length,
		"llm_config_label": llm_config.get_label() if llm_config else "",
		"human_config_label": human_config.get_label() if human_config else "",
		"games_played": games_played,
		"per_game_log": _results.duplicate(),
	}
