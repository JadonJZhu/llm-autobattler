class_name MainUI
extends Control
## Owns top-level game UI elements that sit outside the shop panels.
## Currently manages the autoplay toggle button below the board grid.

signal autoplay_toggle_pressed()
signal mode_config_changed(config: LlmModeConfig)

const MODE_BUTTON_SIZE: Vector2 = Vector2(170, 36)
const BUTTON_H_PADDING: float = 12.0

const GRID_TOP_Y: float = 150.0  # board_offset.y default
const GRID_BOTTOM_Y: float = (
	GameBoard.CELL_SPACING * (GridConstants.ROWS - 1)
	+ GameBoard.CELL_SIZE
	+ GRID_TOP_Y
)
const GRID_CENTER_X: float = (
	165.0  # board_offset.x default
	+ (GameBoard.CELL_SPACING * (GridConstants.COLS - 1) + GameBoard.CELL_SIZE) / 2.0
)
const BELOW_GRID_PADDING: float = 15.0

var _autoplay_button: Button
var _manual_hint_label: Label
var _instructions_check: CheckButton
var _examples_check: CheckButton
var _reflection_check: CheckButton
var _mode_config: LlmModeConfig = LlmModeConfig.new()


func _ready() -> void:
	_build_autoplay_button()
	_build_manual_hint_label()
	_build_mode_toggles()


func update_autoplay_button(is_autoplay: bool) -> void:
	if not _autoplay_button:
		return
	_autoplay_button.text = "Toggle Progression: %s" % ("Autoplay" if is_autoplay else "Manual")


func show_manual_hint(hint_visible: bool) -> void:
	if _manual_hint_label:
		_manual_hint_label.visible = hint_visible


func _build_autoplay_button() -> void:
	_autoplay_button = Button.new()
	_autoplay_button.custom_minimum_size = MODE_BUTTON_SIZE
	_autoplay_button.position = Vector2(
		GRID_CENTER_X - MODE_BUTTON_SIZE.x / 2.0 - 30,
		GRID_BOTTOM_Y + BELOW_GRID_PADDING
	)
	_autoplay_button.pressed.connect(autoplay_toggle_pressed.emit)
	add_child(_autoplay_button)
	_apply_h_padding(_autoplay_button, BUTTON_H_PADDING)
	update_autoplay_button(true)


func _build_manual_hint_label() -> void:
	_manual_hint_label = Label.new()
	_manual_hint_label.text = "Click anywhere to progress the battle."
	_manual_hint_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_manual_hint_label.position = Vector2(
		GRID_CENTER_X - MODE_BUTTON_SIZE.x / 2.0 - 50,
		GRID_BOTTOM_Y + BELOW_GRID_PADDING + MODE_BUTTON_SIZE.y + 10.0
	)
	_manual_hint_label.custom_minimum_size = Vector2(MODE_BUTTON_SIZE.x, 0)
	_manual_hint_label.visible = false
	add_child(_manual_hint_label)


func _build_mode_toggles() -> void:
	var toggle_start_x: float = GRID_CENTER_X - MODE_BUTTON_SIZE.x / 2.0 - 30
	var toggle_start_y: float = GRID_TOP_Y - BELOW_GRID_PADDING - MODE_BUTTON_SIZE.y - 60
	var toggle_spacing: float = 30.0

	_instructions_check = CheckButton.new()
	_instructions_check.text = "Instructions"
	_instructions_check.button_pressed = true
	_instructions_check.position = Vector2(toggle_start_x, toggle_start_y)
	_instructions_check.toggled.connect(_on_instructions_toggled)
	add_child(_instructions_check)

	_examples_check = CheckButton.new()
	_examples_check.text = "Examples"
	_examples_check.button_pressed = false
	_examples_check.position = Vector2(toggle_start_x, toggle_start_y + toggle_spacing)
	_examples_check.toggled.connect(_on_examples_toggled)
	add_child(_examples_check)

	_reflection_check = CheckButton.new()
	_reflection_check.text = "Reflection"
	_reflection_check.button_pressed = false
	_reflection_check.position = Vector2(toggle_start_x, toggle_start_y + toggle_spacing * 2)
	_reflection_check.toggled.connect(_on_reflection_toggled)
	add_child(_reflection_check)


func _on_instructions_toggled(pressed: bool) -> void:
	_mode_config.instructions_enabled = pressed
	mode_config_changed.emit(_mode_config)


func _on_examples_toggled(pressed: bool) -> void:
	_mode_config.examples_enabled = pressed
	mode_config_changed.emit(_mode_config)


func _on_reflection_toggled(pressed: bool) -> void:
	_mode_config.reflection_enabled = pressed
	mode_config_changed.emit(_mode_config)


func _apply_h_padding(button: Button, padding: float) -> void:
	for state: String in ["normal", "hover", "pressed", "focus", "disabled"]:
		var style: StyleBox = button.get_theme_stylebox(state)
		if style is StyleBoxFlat:
			var padded: StyleBoxFlat = style.duplicate()
			padded.content_margin_left = padding
			padded.content_margin_right = padding
			button.add_theme_stylebox_override(state, padded)
