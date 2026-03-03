class_name ExperimentLogger
extends RefCounted
## Tracks and persists per-game results during LLM-vs-LLM experiments.
## Separated from GameLogger so that experiment-specific concerns don't
## pollute the core game logging singleton.

const LOG_CONSTANTS = preload("res://scripts/log_constants.gd")

var _results: Array[Dictionary] = []


func log_game(game_number: int, llm_config_label: String,
		human_config_label: String, outcome: Dictionary) -> void:
	var entry: Dictionary = {
		"game_number": game_number,
		"llm_config": llm_config_label,
		"human_config": human_config_label,
		"winner": outcome.get("winner", "Unknown"),
		"llm_score": int(outcome.get("llm_score", 0)),
		"human_score": int(outcome.get("human_score", 0)),
		"battle_steps": int(outcome.get("battle_steps", 0)),
	}
	_results.append(entry)


func save_log(filename: String) -> void:
	var file_path: String = LOG_CONSTANTS.LOG_DIRECTORY + filename
	DirAccess.make_dir_recursive_absolute(LOG_CONSTANTS.LOG_DIRECTORY)
	var file := FileAccess.open(file_path, FileAccess.WRITE)
	if file == null:
		push_error("ExperimentLogger: Failed to open log file: " + file_path)
		return
	file.store_string(JSON.stringify(_results, "\t"))
	file.close()
	print("ExperimentLogger: Saved experiment log to " + file_path)


func clear() -> void:
	_results.clear()
