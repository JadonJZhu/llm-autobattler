class_name Tile
extends Node2D
## Represents a single tile on the game board.
## Handles arrow direction, tile type, locked state, and visual updates.

signal tile_clicked(grid_position: Vector2i)

enum TileType { ARROW, DESTINATION_X, DESTINATION_Y, EMPTY }
enum Direction { UP, RIGHT, DOWN, LEFT }

const DIRECTION_LABELS: Dictionary = {
	Direction.UP: "^",
	Direction.RIGHT: ">",
	Direction.DOWN: "v",
	Direction.LEFT: "<",
}

const DIRECTION_ROTATIONS: Dictionary = {
	Direction.UP: 0.0,
	Direction.RIGHT: 90.0,
	Direction.DOWN: 180.0,
	Direction.LEFT: 270.0,
}

@export var tile_type: TileType = TileType.ARROW:
	set(value):
		tile_type = value
		if _background != null:
			_update_visuals()
@export var direction: Direction = Direction.UP:
	set(value):
		direction = value
		if _background != null:
			_update_visuals()

var grid_position: Vector2i = Vector2i.ZERO
var is_locked: bool = false
var correct_direction: Direction = Direction.UP

var _arrow_label: Label
var _background: ColorRect
var _lock_indicator: ColorRect


func _ready() -> void:
	_build_visuals()
	_update_visuals()


func _build_visuals() -> void:
	_background = ColorRect.new()
	_background.size = Vector2(64, 64)
	_background.position = Vector2(-32, -32)
	_background.color = Color(0.2, 0.2, 0.2)
	add_child(_background)

	_arrow_label = Label.new()
	_arrow_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_arrow_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_arrow_label.size = Vector2(64, 64)
	_arrow_label.position = Vector2(-32, -32)
	_arrow_label.add_theme_font_size_override("font_size", 32)
	add_child(_arrow_label)

	_lock_indicator = ColorRect.new()
	_lock_indicator.size = Vector2(12, 12)
	_lock_indicator.position = Vector2(20, -32)
	_lock_indicator.color = Color(0.9, 0.2, 0.2)
	_lock_indicator.visible = false
	add_child(_lock_indicator)

	var click_area := Button.new()
	click_area.flat = true
	click_area.size = Vector2(64, 64)
	click_area.position = Vector2(-32, -32)
	click_area.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	click_area.pressed.connect(_on_clicked)
	add_child(click_area)


func _update_visuals() -> void:
	match tile_type:
		TileType.ARROW:
			_arrow_label.text = DIRECTION_LABELS[direction]
			_background.color = Color(0.15, 0.15, 0.25) if not is_locked else Color(0.25, 0.12, 0.12)
		TileType.DESTINATION_X:
			_arrow_label.text = "X"
			_background.color = Color(0.1, 0.35, 0.1)
		TileType.DESTINATION_Y:
			_arrow_label.text = "Y"
			_background.color = Color(0.35, 0.25, 0.1)
		TileType.EMPTY:
			_arrow_label.text = ""
			_background.color = Color(0.1, 0.1, 0.1)

	_lock_indicator.visible = is_locked


func flip_direction() -> void:
	if tile_type != TileType.ARROW:
		return
	match direction:
		Direction.UP:
			direction = Direction.DOWN
		Direction.DOWN:
			direction = Direction.UP
		Direction.LEFT:
			direction = Direction.RIGHT
		Direction.RIGHT:
			direction = Direction.LEFT
	_update_visuals()


func set_direction(new_direction: Direction) -> void:
	direction = new_direction
	_update_visuals()


func set_locked(locked: bool) -> void:
	is_locked = locked
	_update_visuals()


func is_correct() -> bool:
	if tile_type != TileType.ARROW:
		return true
	return direction == correct_direction


func get_serialized_label() -> String:
	match tile_type:
		TileType.DESTINATION_X:
			return "X"
		TileType.DESTINATION_Y:
			return "Y"
		TileType.ARROW:
			var lock_suffix: String = "L" if is_locked else ""
			return DIRECTION_LABELS[direction] + lock_suffix
		TileType.EMPTY:
			return "."
	return "?"


func _on_clicked() -> void:
	tile_clicked.emit(grid_position)
