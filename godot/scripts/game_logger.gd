extends Node
## Autoloaded singleton for logging game turns, LLM reasoning, and moves.
## Writes JSON logs to user://game_logs/.

const LOG_DIRECTORY: String = "user://game_logs/"

var _log_entries: Array[Dictionary] = []
var _session_id: String = ""


func _ready() -> void:
	_session_id = _generate_session_id()
	DirAccess.make_dir_recursive_absolute(LOG_DIRECTORY)


func log_turn(turn_number: int, turn_data: Dictionary) -> void:
	var entry: Dictionary = {
		"session_id": _session_id,
		"turn_number": turn_number,
		"timestamp": Time.get_datetime_string_from_system(),
	}
	entry.merge(turn_data)
	_log_entries.append(entry)


func log_llm_turn(turn_number: int, flip_pos: Vector2i, lock_pos: Vector2i,
		score: int, reasoning: String) -> void:
	log_turn(turn_number, {
		"actor": "llm",
		"flip_position": {"x": flip_pos.x, "y": flip_pos.y},
		"lock_position": {"x": lock_pos.x, "y": lock_pos.y},
		"correctness_score": score,
		"reasoning": reasoning,
	})


func log_human_turn(turn_number: int, flip_pos: Vector2i, score: int) -> void:
	log_turn(turn_number, {
		"actor": "human",
		"flip_position": {"x": flip_pos.x, "y": flip_pos.y},
		"correctness_score": score,
	})


func log_game_result(winner: String, final_score: int, total_turns: int) -> void:
	log_turn(total_turns, {
		"event": "game_over",
		"winner": winner,
		"final_score": final_score,
	})


func save_log() -> void:
	var file_path: String = LOG_DIRECTORY + "game_" + _session_id + ".json"
	var file := FileAccess.open(file_path, FileAccess.WRITE)
	if file == null:
		push_error("GameLogger: Failed to open log file: " + file_path)
		return
	file.store_string(JSON.stringify(_log_entries, "\t"))
	file.close()
	print("GameLogger: Saved log to " + file_path)


func get_entries() -> Array[Dictionary]:
	return _log_entries


func _generate_session_id() -> String:
	var datetime: Dictionary = Time.get_datetime_dict_from_system()
	return "%04d%02d%02d_%02d%02d%02d" % [
		datetime["year"], datetime["month"], datetime["day"],
		datetime["hour"], datetime["minute"], datetime["second"],
	]
