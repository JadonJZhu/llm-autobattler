class_name Unit
extends Node2D
## A single unit on the autochess board. Holds type, owner, position, and visuals.

# --- Enums ---

enum UnitType { A, B, C, D }
enum Owner { LLM, HUMAN }

# --- Constants ---

const TYPE_LABELS: Dictionary = {
	UnitType.A: "A",
	UnitType.B: "B",
	UnitType.C: "C",
	UnitType.D: "D",
}

const UNIT_COSTS: Dictionary = {
	UnitType.A: 1,
	UnitType.B: 1,
	UnitType.C: 1,
	UnitType.D: 2,
}

const OWNER_COLORS: Dictionary = {
	Owner.LLM: Color(0.3, 0.5, 0.9),
	Owner.HUMAN: Color(0.9, 0.4, 0.3),
}

const TYPE_COLORS: Dictionary = {
	UnitType.A: Color(0.2, 0.7, 0.4),    # Green
	UnitType.B: Color(0.6, 0.3, 0.8),    # Purple
	UnitType.C: Color(0.9, 0.65, 0.2),   # Amber
	UnitType.D: Color(0.85, 0.25, 0.35), # Crimson
}

const UNIT_SIZE: int = 80
const OWNER_BORDER_WIDTH: int = 3

# --- State ---

var unit_type: UnitType
var unit_owner: Owner
var grid_position: Vector2i
var placement_order: int

# --- Visual nodes ---

var _background: Panel
var _label: Label

# --- Public ---

func setup(type: UnitType, unit_owner: Owner, pos: Vector2i, order: int) -> void:
	unit_type = type
	self.unit_owner = unit_owner
	grid_position = pos
	placement_order = order
	_build_visuals()


static func type_from_string(s: String) -> UnitType:
	match s.to_upper():
		"A": return UnitType.A
		"B": return UnitType.B
		"C": return UnitType.C
		"D": return UnitType.D
		_:
			push_error("Unknown unit type string: %s" % s)
			return UnitType.A


static func cost_of(type: UnitType) -> int:
	return UNIT_COSTS[type]


# --- Visuals ---

func _build_visuals() -> void:
	_background = Panel.new()
	_background.size = Vector2(UNIT_SIZE, UNIT_SIZE)
	var style := StyleBoxFlat.new()
	style.bg_color = TYPE_COLORS[unit_type]
	style.border_color = OWNER_COLORS[unit_owner]
	style.border_width_bottom = OWNER_BORDER_WIDTH
	style.border_width_top = OWNER_BORDER_WIDTH
	style.border_width_left = OWNER_BORDER_WIDTH
	style.border_width_right = OWNER_BORDER_WIDTH
	_background.add_theme_stylebox_override("panel", style)
	add_child(_background)

	_label = Label.new()
	_label.text = TYPE_LABELS[unit_type]
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_label.size = Vector2(UNIT_SIZE, UNIT_SIZE)
	_label.add_theme_font_size_override("font_size", 32)
	_label.add_theme_color_override("font_color", Color.WHITE)
	add_child(_label)


func _update_visuals() -> void:
	if _background:
		var style: StyleBoxFlat = _background.get_theme_stylebox("panel") as StyleBoxFlat
		if style:
			style.bg_color = TYPE_COLORS[unit_type]
			style.border_color = OWNER_COLORS[unit_owner]
	if _label:
		_label.text = TYPE_LABELS[unit_type]
