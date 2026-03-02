class_name GameBoard
extends Node2D
## 4x3 autochess grid. Manages unit placement and board state.

signal cell_clicked(grid_position: Vector2i)
signal board_ready

const ROWS: int = 4
const COLS: int = 3
const LLM_ROWS: Array[int] = [0, 1]
const HUMAN_ROWS: Array[int] = [2, 3]
const CELL_SIZE: int = 80
const CELL_SPACING: int = 90

var _units: Dictionary = {}  # Vector2i -> Unit
var _placement_counter: int = 0

@export var board_offset: Vector2 = Vector2(100, 60)


func _ready() -> void:
	pass


func initialize() -> void:
	_clear_board()
	_placement_counter = 0
	board_ready.emit()


func place_unit(type: Unit.UnitType, unit_owner: Unit.Owner, pos: Vector2i) -> bool:
	if not is_position_valid_for(unit_owner, pos):
		return false
	if _units.has(pos):
		return false

	var unit := Unit.new()
	unit.setup(type, unit_owner, pos, _placement_counter)
	unit.position = grid_to_world(pos)
	_units[pos] = unit
	_placement_counter += 1
	add_child(unit)
	# Move unit above cell buttons visually
	unit.z_index = 1
	return true


func remove_unit(pos: Vector2i) -> void:
	if not _units.has(pos):
		return
	var unit: Unit = _units[pos]
	_units.erase(pos)
	unit.queue_free()


func move_unit(from: Vector2i, to: Vector2i) -> void:
	if not _units.has(from):
		return
	var unit: Unit = _units[from]
	_units.erase(from)
	unit.grid_position = to
	unit.position = grid_to_world(to)
	_units[to] = unit


func get_snapshot() -> Dictionary:
	var snapshot: Dictionary = {}
	for pos: Vector2i in _units:
		var unit: Unit = _units[pos]
		snapshot[pos] = {
			"unit_type": unit.unit_type,
			"owner": unit.unit_owner,
			"placement_order": unit.placement_order,
		}
	return snapshot


func apply_battle_step(step_result: Dictionary) -> void:
	if step_result["removal"] != null:
		remove_unit(step_result["removal"])
	if step_result["self_removal"] != null:
		remove_unit(step_result["self_removal"])
	if step_result["move"] != null:
		var move_data: Dictionary = step_result["move"]
		move_unit(move_data["from"], move_data["to"])


func is_position_valid_for(unit_owner: Unit.Owner, pos: Vector2i) -> bool:
	if pos.x < 0 or pos.x >= ROWS or pos.y < 0 or pos.y >= COLS:
		return false
	if unit_owner == Unit.Owner.LLM:
		return pos.x in LLM_ROWS
	else:
		return pos.x in HUMAN_ROWS


func get_empty_positions_for(unit_owner: Unit.Owner) -> Array[Vector2i]:
	var positions: Array[Vector2i] = []
	var rows: Array[int] = LLM_ROWS if unit_owner == Unit.Owner.LLM else HUMAN_ROWS
	for row in rows:
		for col in range(COLS):
			var pos := Vector2i(row, col)
			if not _units.has(pos):
				positions.append(pos)
	return positions


func has_units_for(unit_owner: Unit.Owner) -> bool:
	for pos: Vector2i in _units:
		if _units[pos].unit_owner == unit_owner:
			return true
	return false


func grid_to_world(grid_pos: Vector2i) -> Vector2:
	return Vector2(
		board_offset.x + grid_pos.y * CELL_SPACING,
		board_offset.y + grid_pos.x * CELL_SPACING
	)


# --- Private ---

func _clear_board() -> void:
	for pos: Vector2i in _units:
		_units[pos].queue_free()
	_units.clear()
