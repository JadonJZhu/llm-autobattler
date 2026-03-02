extends Node
## Autoloaded singleton for logging game turns, LLM reasoning, and moves.
## Writes JSON logs to user://game_logs/.

const LOG_DIRECTORY: String = "user://game_logs/"

var _log_entries: Array[Dictionary] = []
var _session_id: String = ""

var _current_battle_start_board: String = ""
var _current_battle_steps: Array[String] = []
var _previous_game_replay: Dictionary = {}
var _current_game_score_data: Dictionary = {}


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


func log_prep_placement(turn_number: int, unit_owner: String, unit_type: String,
		pos: Vector2i, gold_remaining: int) -> void:
	log_turn(turn_number, {
		"phase": "prep",
		"actor": unit_owner,
		"unit_type": unit_type,
		"position": {"row": pos.x, "col": pos.y},
		"gold_remaining": gold_remaining,
	})


func log_battle_step(step_number: int, active_owner: String, events: String) -> void:
	var has_escape: bool = events.find("escaped off the board") != -1
	log_turn(step_number, {
		"phase": "battle",
		"active_owner": active_owner,
		"events": events,
		"had_escape": has_escape,
	})
	_current_battle_steps.append(events)


func set_current_game_score_data(score_data: Dictionary) -> void:
	_current_game_score_data = score_data.duplicate()


func log_game_result(winner: String, final_score: int = -1, total_turns: int = -1,
		total_prep_turns: int = -1, total_battle_steps: int = -1) -> void:
	var entry: Dictionary = {
		"event": "game_over",
		"winner": winner,
		"llm_score": int(_current_game_score_data.get("llm_score", 0)),
		"human_score": int(_current_game_score_data.get("human_score", 0)),
		"llm_remaining": int(_current_game_score_data.get("llm_remaining", 0)),
		"human_remaining": int(_current_game_score_data.get("human_remaining", 0)),
		"llm_escaped": int(_current_game_score_data.get("llm_escaped", 0)),
		"human_escaped": int(_current_game_score_data.get("human_escaped", 0)),
	}
	if final_score >= 0:
		entry["final_score"] = final_score
	if total_turns >= 0:
		entry["total_turns"] = total_turns
	if total_prep_turns >= 0:
		entry["total_prep_turns"] = total_prep_turns
	if total_battle_steps >= 0:
		entry["total_battle_steps"] = total_battle_steps
	log_turn(maxi(total_turns, total_battle_steps), entry)


func record_battle_start(serialized_board: String) -> void:
	_current_battle_start_board = serialized_board
	_current_battle_steps.clear()


func finalize_game_replay(outcome: String) -> void:
	_previous_game_replay = {
		"start_board": _current_battle_start_board,
		"battle_steps": _current_battle_steps.duplicate(),
		"outcome": outcome,
		"llm_score": int(_current_game_score_data.get("llm_score", 0)),
		"human_score": int(_current_game_score_data.get("human_score", 0)),
		"llm_remaining": int(_current_game_score_data.get("llm_remaining", 0)),
		"human_remaining": int(_current_game_score_data.get("human_remaining", 0)),
		"llm_escaped": int(_current_game_score_data.get("llm_escaped", 0)),
		"human_escaped": int(_current_game_score_data.get("human_escaped", 0)),
	}
	_current_battle_start_board = ""
	_current_battle_steps.clear()
	_current_game_score_data = {}


func get_previous_game_replay() -> Dictionary:
	return _previous_game_replay


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
