class_name PuzzleLoader
extends RefCounted
## Loads puzzle scenarios from JSON and validates required fields.

const DEFAULT_PUZZLE_PATH: String = "res://puzzles/puzzle_suite.json"
const PUZZLE_SCENARIO_SCRIPT = preload("res://scripts/puzzle_scenario.gd")


func load_puzzles(path: String = DEFAULT_PUZZLE_PATH) -> Array:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("PuzzleLoader: Failed to open puzzle file: " + path)
		return []

	var text: String = file.get_as_text()
	file.close()

	var json := JSON.new()
	var parse_error: int = json.parse(text)
	if parse_error != OK:
		push_error("PuzzleLoader: JSON parse failed at line %d: %s" % [
			json.get_error_line(),
			json.get_error_message(),
		])
		return []

	var root: Variant = json.data
	if not (root is Dictionary):
		push_error("PuzzleLoader: Root JSON must be a dictionary.")
		return []

	var puzzles_variant: Variant = root.get("puzzles", [])
	if not (puzzles_variant is Array):
		push_error("PuzzleLoader: 'puzzles' must be an array.")
		return []

	var scenarios: Array = []
	for i in range(puzzles_variant.size()):
		var raw_entry: Variant = puzzles_variant[i]
		if not (raw_entry is Dictionary):
			push_error("PuzzleLoader: Puzzle entry at index %d is not a dictionary." % i)
			continue
		var scenario: Variant = _parse_scenario(raw_entry, i)
		if scenario != null:
			scenarios.append(scenario)
	return scenarios


func _parse_scenario(raw: Dictionary, index: int) -> Variant:
	var id: String = str(raw.get("id", "")).strip_edges()
	if id.is_empty():
		push_error("PuzzleLoader: Puzzle at index %d is missing 'id'." % index)
		return null

	var scenario = PUZZLE_SCENARIO_SCRIPT.new()
	scenario.id = id
	scenario.difficulty = maxi(1, int(raw.get("difficulty", 1)))
	scenario.llm_gold = maxi(0, int(raw.get("llm_gold", Shop.STARTING_GOLD)))
	scenario.opponent_gold = maxi(0, int(raw.get("opponent_gold", Shop.STARTING_GOLD)))
	scenario.llm_shop_types = _parse_shop_types(raw.get("llm_shop", []), index, "llm_shop")
	scenario.opponent_shop_types = _parse_shop_types(
		raw.get("opponent_shop", []), index, "opponent_shop"
	)
	scenario.opponent_placements = _parse_opponent_placements(
		raw.get("opponent_placements", []), index
	)

	if scenario.llm_shop_types.is_empty():
		push_error("PuzzleLoader: Puzzle '%s' has empty llm_shop." % scenario.id)
		return null
	if scenario.opponent_shop_types.is_empty():
		push_error("PuzzleLoader: Puzzle '%s' has empty opponent_shop." % scenario.id)
		return null

	return scenario


func _parse_shop_types(raw_types: Variant, puzzle_index: int, field_name: String) -> Array[UnitData.UnitType]:
	if not (raw_types is Array):
		push_error("PuzzleLoader: Puzzle index %d field '%s' must be an array." % [
			puzzle_index, field_name
		])
		return []

	var parsed: Array[UnitData.UnitType] = []
	for raw_type in raw_types:
		var type_label: String = str(raw_type).to_upper().strip_edges()
		if not _is_valid_type_label(type_label):
			push_error("PuzzleLoader: Invalid unit type '%s' in field '%s' (puzzle index %d)." % [
				type_label, field_name, puzzle_index
			])
			continue
		parsed.append(UnitData.type_from_string(type_label))
	return parsed


func _parse_opponent_placements(raw_placements: Variant, puzzle_index: int) -> Array[Dictionary]:
	if not (raw_placements is Array):
		push_error("PuzzleLoader: Puzzle index %d field 'opponent_placements' must be an array." % puzzle_index)
		return []

	var placements: Array[Dictionary] = []
	for i in range(raw_placements.size()):
		var item: Variant = raw_placements[i]
		if not (item is Dictionary):
			push_error("PuzzleLoader: Opponent placement %d for puzzle index %d is not a dictionary." % [
				i, puzzle_index
			])
			continue

		var type_label: String = str(item.get("type", "")).to_upper().strip_edges()
		if not _is_valid_type_label(type_label):
			push_error("PuzzleLoader: Invalid placement type '%s' at puzzle index %d entry %d." % [
				type_label, puzzle_index, i
			])
			continue

		var row: int = int(item.get("row", -1))
		var col: int = int(item.get("col", -1))
		var position := Vector2i(row, col)
		if not _is_valid_opponent_position(position):
			push_error("PuzzleLoader: Invalid opponent placement (%d, %d) at puzzle index %d entry %d." % [
				row, col, puzzle_index, i
			])
			continue

		placements.append({
			"unit_type": UnitData.type_from_string(type_label),
			"position": position,
		})
	return placements


func _is_valid_type_label(type_label: String) -> bool:
	return type_label in ["A", "B", "C", "D"]


func _is_valid_opponent_position(pos: Vector2i) -> bool:
	if pos.x < 0 or pos.x >= GridConstants.ROWS:
		return false
	if pos.y < 0 or pos.y >= GridConstants.COLS:
		return false
	return pos.x in GridConstants.HUMAN_ROWS
