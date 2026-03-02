class_name Unit
extends Node2D
## A single unit view node on the board.
## Unit enums/costs/colors live in UnitData.

const UNIT_SIZE: int = 80
const OWNER_BORDER_WIDTH: int = 3

# --- State ---

var unit_type: UnitData.UnitType
var unit_owner: UnitData.Owner
var grid_position: Vector2i
var placement_order: int

# --- Visual nodes ---

var _background: Panel
var _label: Label

# --- Public ---

func setup(type: UnitData.UnitType, owner_type: UnitData.Owner, pos: Vector2i, order: int) -> void:
	unit_type = type
	unit_owner = owner_type
	grid_position = pos
	placement_order = order
	_build_visuals()


# --- Visuals ---

func _build_visuals() -> void:
	_background = Panel.new()
	_background.size = Vector2(UNIT_SIZE, UNIT_SIZE)
	var style: StyleBoxFlat = StyleUtils.create_flat_style(
		UnitData.TYPE_COLORS[unit_type],
		UnitData.OWNER_COLORS[unit_owner],
		OWNER_BORDER_WIDTH
	)
	_background.add_theme_stylebox_override("panel", style)
	add_child(_background)

	_label = Label.new()
	_label.text = UnitData.TYPE_LABELS[unit_type]
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_label.size = Vector2(UNIT_SIZE, UNIT_SIZE)
	_label.add_theme_font_size_override("font_size", 32)
	_label.add_theme_color_override("font_color", Color.WHITE)
	add_child(_label)
