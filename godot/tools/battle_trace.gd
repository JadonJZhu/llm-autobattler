extends SceneTree
## Headless driver that runs BattleEngine over given board positions and writes a
## step-by-step JSON trace.
##
## Usage:
##   godot --headless --path godot -s tools/battle_trace.gd --cases <in.json> --out <out.json>
##
## This is the ground-truth side of a differential test, so it adds no rules of its
## own: it drives the engine exactly as TurnManager's battle loop does and records
## what came back. GameBoard.apply_battle_step is view-only bookkeeping, so no board
## or scene is needed; the engine mutates the snapshot itself.
##
## Its one job beyond that is to never report agreement it did not establish, so a
## malformed case is rejected outright rather than turned into a plausible trace.

# A real battle always terminates, because every step kills, moves or escapes a unit.
# The cap only keeps a divergence in the engine from hanging the run.
const MAX_STEPS: int = 200

const ROWS: int = GridConstants.ROWS
const COLS: int = GridConstants.COLS

const UNIT_FIELDS: Array[String] = ["row", "col", "type", "owner", "placement_order"]

# True once the run has chosen its exit code. See _process.
var _exit_decided: bool = false


func _initialize() -> void:
	var argv: PackedStringArray = OS.get_cmdline_args()
	var cases_path: String = _option(argv, "--cases")
	var out_path: String = _option(argv, "--out")
	if cases_path.is_empty() or out_path.is_empty():
		_fail("usage: godot --headless --path godot -s tools/battle_trace.gd --cases <in.json> --out <out.json>")
		return

	if not _clear_output(out_path):
		return

	var cases_file: FileAccess = FileAccess.open(cases_path, FileAccess.READ)
	if cases_file == null:
		_fail("cannot read %s: %s" % [cases_path, error_string(FileAccess.get_open_error())])
		return

	var parsed: Variant = JSON.parse_string(cases_file.get_as_text())
	var input_error: String = _input_error(parsed)
	if not input_error.is_empty():
		_fail("%s: %s" % [cases_path, input_error])
		return

	var traces: Array = []
	for case_dict: Dictionary in (parsed as Dictionary)["cases"]:
		var trace: Dictionary = _run_case(case_dict)
		# A GDScript runtime error unwinds one frame and hands the caller the return
		# type's default, so an empty trace means _run_case was aborted part-way.
		# Godot has already printed why; never write a half-run out as a result.
		if trace.is_empty():
			_fail("case %s: the run was aborted part-way" % case_dict["id"])
			return
		traces.append(trace)

	var out_file: FileAccess = FileAccess.open(out_path, FileAccess.WRITE)
	if out_file == null:
		_fail("cannot write %s: %s" % [out_path, error_string(FileAccess.get_open_error())])
		return
	out_file.store_string(JSON.stringify({ "traces": traces }))
	_exit_decided = true
	quit(0)


## _initialize does the whole run, so reaching a frame at all means it was aborted
## part-way by a GDScript error and nothing decided an exit code. Godot has already
## printed the error; stop, rather than leaving the SceneTree spinning forever with
## no output. Without this, one unvalidated malformed field hangs the process.
func _process(_delta: float) -> bool:
	if not _exit_decided:
		printerr("battle_trace: aborted before a trace was written")
		quit(1)
	return true


## Deletes a previous run's trace before this run starts, so a failed run cannot
## leave stale output behind for a driver that misses the exit code.
func _clear_output(out_path: String) -> bool:
	if not FileAccess.file_exists(out_path):
		return true
	var error: Error = DirAccess.remove_absolute(out_path)
	if error != OK:
		_fail("cannot remove existing %s: %s" % [out_path, error_string(error)])
		return false
	return true


## Checks the entire input before any of it is used. Returns "" when it is usable,
## otherwise one line naming the case and what is wrong with it.
##
## This is a whole pass up front rather than a check beside each read for two
## reasons. The caller is a puzzle generator, so a malformed board is an expected
## input and not an impossible one; and reading a missing or wrongly typed field
## raises a GDScript error, which aborts _initialize part-way and hangs the run.
func _input_error(parsed: Variant) -> String:
	if typeof(parsed) != TYPE_DICTIONARY or not (parsed as Dictionary).has("cases"):
		return "not JSON of the form {\"cases\": [...]}"
	var cases: Variant = (parsed as Dictionary)["cases"]
	if typeof(cases) != TYPE_ARRAY:
		return "\"cases\" is %s, expected an array" % type_string(typeof(cases))
	if (cases as Array).is_empty():
		return "\"cases\" is empty, so there is nothing to trace"

	var seen_ids: Dictionary = {}
	for case_variant: Variant in cases as Array:
		if typeof(case_variant) != TYPE_DICTIONARY:
			return "case entry is %s, expected an object" % type_string(typeof(case_variant))
		var case_dict: Dictionary = case_variant
		if not case_dict.has("id") or typeof(case_dict["id"]) != TYPE_STRING:
			return "case is missing a string \"id\""
		var case_id: String = case_dict["id"]
		if seen_ids.has(case_id):
			return "case %s: a second case has this id, so traces cannot be matched up" % case_id
		seen_ids[case_id] = true
		var case_error: String = _case_error(case_dict)
		if not case_error.is_empty():
			return "case %s: %s" % [case_id, case_error]
	return ""


func _case_error(case_dict: Dictionary) -> String:
	if not case_dict.has("units") or typeof(case_dict["units"]) != TYPE_ARRAY:
		return "missing a \"units\" array"

	var occupied: Dictionary = {}
	var placements: Dictionary = {}
	var index: int = 0
	for unit_variant: Variant in case_dict["units"] as Array:
		if typeof(unit_variant) != TYPE_DICTIONARY:
			return "unit %d is %s, expected an object" % [index, type_string(typeof(unit_variant))]
		var unit: Dictionary = unit_variant

		for field: String in UNIT_FIELDS:
			if not unit.has(field):
				return "unit %d is missing \"%s\"" % [index, field]
		# Godot's JSON parser returns every number as a float, so being a whole
		# number is a check on the value and not on the type: 1.9 has to be
		# rejected rather than truncated to 1, and 1e400 arrives as inf.
		for field: String in ["row", "col", "placement_order"]:
			var value: Variant = unit[field]
			if typeof(value) != TYPE_FLOAT or not is_finite(value) or value != floor(value):
				return "unit %d has \"%s\": %s, expected a whole number" % [
					index, field, JSON.stringify(value)
				]
		for field: String in ["type", "owner"]:
			if typeof(unit[field]) != TYPE_STRING:
				return "unit %d has \"%s\": %s, expected a string" % [
					index, field, JSON.stringify(unit[field])
				]

		# Squares are checked for being on the board, and deliberately not for being
		# on the unit owner's own half. Units cross into enemy rows during a battle,
		# so starting a case from an arbitrary mid-battle position is legitimate and
		# a stronger test input. The engine holds no such rule, so this tool adds none.
		var pos := Vector2i(int(unit["row"]), int(unit["col"]))
		if pos.x < 0 or pos.x >= ROWS or pos.y < 0 or pos.y >= COLS:
			return "unit %d is at (%d,%d), off a %dx%d board" % [index, pos.x, pos.y, ROWS, COLS]
		if occupied.has(pos):
			return "unit %d shares square (%d,%d) with unit %d" % [
				index, pos.x, pos.y, occupied[pos]
			]
		occupied[pos] = index

		if _type_from_name(unit["type"]) < 0:
			return "unit %d has unknown unit type %s" % [index, JSON.stringify(unit["type"])]
		if _owner_from_name(unit["owner"]) < 0:
			return "unit %d has unknown owner %s" % [index, JSON.stringify(unit["owner"])]

		# Two units of one owner sharing a placement_order leave the engine's acting
		# order undefined on the tie, and it then falls back to the order the units
		# were listed in. A trace that depends on JSON array order cannot arbitrate a
		# port, so reject it here rather than record it.
		var placement: Array = [unit["owner"], int(unit["placement_order"])]
		if placements.has(placement):
			return "unit %d and unit %d are both %s placement_order %d" % [
				index, placements[placement], unit["owner"], int(unit["placement_order"])
			]
		placements[placement] = index

		index += 1
	return ""


## Runs one validated case to completion.
func _run_case(case_dict: Dictionary) -> Dictionary:
	var snapshot := BattleSnapshot.new()
	for unit: Dictionary in case_dict["units"]:
		snapshot.units[Vector2i(int(unit["row"]), int(unit["col"]))] = {
			"unit_type": _type_from_name(unit["type"]),
			"owner": _owner_from_name(unit["owner"]),
			"placement_order": int(unit["placement_order"]),
		}

	var engine := BattleEngine.new()
	var active_owner: UnitData.Owner = UnitData.Owner.LLM  # LLM always goes first
	var steps: Array = []
	var last_result: Dictionary = {}
	var aborted: bool = false

	while true:
		if steps.size() >= MAX_STEPS:
			aborted = true
			break
		var result: Dictionary = engine.execute_step(snapshot, active_owner)
		last_result = result
		steps.append(_step_record(steps.size() + 1, result))
		if result["is_finished"]:
			break
		if active_owner == UnitData.Owner.LLM:
			active_owner = UnitData.Owner.HUMAN
		else:
			active_owner = UnitData.Owner.LLM

	return {
		"id": case_dict["id"],
		"steps": steps,
		"final": _final_record(last_result, steps.size()),
		"aborted": aborted,
	}


## Every field but the step number is the engine's own, copied verbatim. Nothing is
## re-derived from this driver's state, so a driver bug shows up as a disagreement
## instead of hiding behind a value the driver computed for itself.
func _step_record(n: int, result: Dictionary) -> Dictionary:
	return {
		"n": n,
		"active_owner": _owner_name(result["active_owner"]),
		"event": result["event"],
		"event_type": result["event_type"],
		"is_finished": result["is_finished"],
		"winner": _step_winner(result),
		"llm_score": int(result["llm_score"]),
		"human_score": int(result["human_score"]),
		"llm_remaining": int(result["llm_remaining"]),
		"human_remaining": int(result["human_remaining"]),
		"llm_escaped": int(result["llm_escaped"]),
		"human_escaped": int(result["human_escaped"]),
	}


## The engine leaves winner null both for an unfinished step and for a finished tie,
## so is_finished is what tells those apart: null while the battle is still running,
## and "llm", "human" or "tie" once it has ended.
func _step_winner(result: Dictionary) -> Variant:
	if not result["is_finished"]:
		return null
	return _score_winner(result)


## An aborted run reports whoever leads on score, exactly as a finished battle does;
## its "aborted" flag is the only thing that says the result is not a real outcome.
func _final_record(result: Dictionary, step_count: int) -> Dictionary:
	return {
		"winner": _score_winner(result),
		"llm_score": int(result["llm_score"]),
		"human_score": int(result["human_score"]),
		"llm_remaining": int(result["llm_remaining"]),
		"human_remaining": int(result["human_remaining"]),
		"llm_escaped": int(result["llm_escaped"]),
		"human_escaped": int(result["human_escaped"]),
		"steps": step_count,
	}


func _score_winner(result: Dictionary) -> String:
	var llm_score: int = int(result["llm_score"])
	var human_score: int = int(result["human_score"])
	if llm_score > human_score:
		return "llm"
	if human_score > llm_score:
		return "human"
	return "tie"


func _owner_name(unit_owner: int) -> String:
	return "llm" if unit_owner == UnitData.Owner.LLM else "human"


## Returns -1 for an unrecognised name rather than guessing, so a malformed case can
## never turn into a plausible-looking trace.
func _owner_from_name(name: String) -> int:
	match name:
		"llm": return UnitData.Owner.LLM
		"human": return UnitData.Owner.HUMAN
	return -1


func _type_from_name(name: String) -> int:
	match name:
		"A": return UnitData.UnitType.A
		"B": return UnitData.UnitType.B
		"C": return UnitData.UnitType.C
		"D": return UnitData.UnitType.D
	return -1


func _option(argv: PackedStringArray, flag: String) -> String:
	var index: int = argv.find(flag)
	if index < 0 or index + 1 >= argv.size():
		return ""
	return argv[index + 1]


func _fail(message: String) -> void:
	printerr("battle_trace: %s" % message)
	_exit_decided = true
	quit(1)
