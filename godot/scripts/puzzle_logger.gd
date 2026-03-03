class_name PuzzleLogger
extends RefCounted
## Persists puzzle ablation run outputs to user://game_logs/.

const LOG_CONSTANTS = preload("res://scripts/log_constants.gd")


func save_ablation_results(results: Dictionary, filename_prefix: String = "ablation") -> String:
	DirAccess.make_dir_recursive_absolute(LOG_CONSTANTS.LOG_DIRECTORY)
	var timestamp: String = _build_timestamp()
	var file_path: String = "%s%s_%s.json" % [LOG_CONSTANTS.LOG_DIRECTORY, filename_prefix, timestamp]
	var file := FileAccess.open(file_path, FileAccess.WRITE)
	if file == null:
		push_error("PuzzleLogger: Failed to open log file: " + file_path)
		return ""

	var payload: Dictionary = {
		"timestamp": Time.get_datetime_string_from_system(),
		"results": results,
	}
	file.store_string(JSON.stringify(payload, "\t"))
	file.close()
	print("PuzzleLogger: Saved ablation log to " + file_path)
	return file_path


func _build_timestamp() -> String:
	var date: Dictionary = Time.get_datetime_dict_from_system()
	return "%04d%02d%02d_%02d%02d%02d" % [
		date["year"], date["month"], date["day"],
		date["hour"], date["minute"], date["second"],
	]
