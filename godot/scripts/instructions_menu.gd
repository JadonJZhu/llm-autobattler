class_name InstructionsMenu
extends Control
## Full-screen instructions overlay toggled by Esc or a help button.
## Add as a child of a CanvasLayer so it renders above the game.

const OVERLAY_COLOR: Color = Color(0.0, 0.0, 0.0, 0.75)
const PANEL_COLOR: Color = Color(0.12, 0.12, 0.15, 1.0)
const PANEL_BORDER_COLOR: Color = Color(0.4, 0.4, 0.5, 1.0)
const PANEL_SIZE: Vector2 = Vector2(700, 520)
const PANEL_CORNER_RADIUS: int = 12
const PANEL_BORDER_WIDTH: int = 2
const HELP_BUTTON_SIZE: Vector2 = Vector2(40, 40)

var _overlay: ColorRect
var _panel: PanelContainer
var _help_button: Button


func _ready() -> void:
	_build_help_button()
	_build_overlay()
	_overlay.visible = false


func toggle() -> void:
	if _overlay.visible:
		hide_menu()
	else:
		show_menu()


func show_menu() -> void:
	_overlay.visible = true


func hide_menu() -> void:
	_overlay.visible = false


func is_open() -> bool:
	return _overlay.visible


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		toggle()
		get_viewport().set_input_as_handled()
		return
	if _overlay.visible:
		get_viewport().set_input_as_handled()


# --- Help Button (always visible) ---

func _build_help_button() -> void:
	_help_button = Button.new()
	_help_button.text = "?"
	_help_button.custom_minimum_size = HELP_BUTTON_SIZE
	_help_button.position = Vector2(1230, 10)

	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.25, 0.25, 0.3, 0.9)
	style.corner_radius_top_left = 8
	style.corner_radius_top_right = 8
	style.corner_radius_bottom_left = 8
	style.corner_radius_bottom_right = 8
	_help_button.add_theme_stylebox_override("normal", style)

	var hover_style := StyleBoxFlat.new()
	hover_style.bg_color = Color(0.35, 0.35, 0.45, 0.9)
	hover_style.corner_radius_top_left = 8
	hover_style.corner_radius_top_right = 8
	hover_style.corner_radius_bottom_left = 8
	hover_style.corner_radius_bottom_right = 8
	_help_button.add_theme_stylebox_override("hover", hover_style)

	_help_button.add_theme_font_size_override("font_size", 22)
	_help_button.add_theme_color_override("font_color", Color.WHITE)
	_help_button.add_theme_color_override("font_hover_color", Color.WHITE)

	_help_button.pressed.connect(toggle)
	add_child(_help_button)


# --- Overlay ---

func _build_overlay() -> void:
	_overlay = ColorRect.new()
	_overlay.color = OVERLAY_COLOR
	_overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(_overlay)

	_build_panel()


func _build_panel() -> void:
	_panel = PanelContainer.new()
	_panel.custom_minimum_size = PANEL_SIZE
	_panel.position = Vector2(
		(1280.0 - PANEL_SIZE.x) / 2.0,
		(720.0 - PANEL_SIZE.y) / 2.0
	)

	var panel_style := StyleBoxFlat.new()
	panel_style.bg_color = PANEL_COLOR
	panel_style.border_color = PANEL_BORDER_COLOR
	panel_style.border_width_top = PANEL_BORDER_WIDTH
	panel_style.border_width_bottom = PANEL_BORDER_WIDTH
	panel_style.border_width_left = PANEL_BORDER_WIDTH
	panel_style.border_width_right = PANEL_BORDER_WIDTH
	panel_style.corner_radius_top_left = PANEL_CORNER_RADIUS
	panel_style.corner_radius_top_right = PANEL_CORNER_RADIUS
	panel_style.corner_radius_bottom_left = PANEL_CORNER_RADIUS
	panel_style.corner_radius_bottom_right = PANEL_CORNER_RADIUS
	panel_style.content_margin_top = 16
	panel_style.content_margin_bottom = 16
	panel_style.content_margin_left = 24
	panel_style.content_margin_right = 24
	_panel.add_theme_stylebox_override("panel", panel_style)
	_overlay.add_child(_panel)

	var margin := MarginContainer.new()
	_panel.add_child(margin)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 4)
	margin.add_child(vbox)

	_build_header(vbox)
	_build_body(vbox)


func _build_header(parent: VBoxContainer) -> void:
	var header_container := HBoxContainer.new()
	parent.add_child(header_container)

	var title := Label.new()
	title.text = "HOW TO PLAY"
	title.add_theme_font_size_override("font_size", 24)
	title.add_theme_color_override("font_color", Color.WHITE)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header_container.add_child(title)

	var close_button := Button.new()
	close_button.text = "X"
	close_button.custom_minimum_size = Vector2(36, 36)

	var close_style := StyleBoxFlat.new()
	close_style.bg_color = Color(0.5, 0.2, 0.2, 0.8)
	close_style.corner_radius_top_left = 6
	close_style.corner_radius_top_right = 6
	close_style.corner_radius_bottom_left = 6
	close_style.corner_radius_bottom_right = 6
	close_button.add_theme_stylebox_override("normal", close_style)

	var close_hover := StyleBoxFlat.new()
	close_hover.bg_color = Color(0.7, 0.25, 0.25, 0.9)
	close_hover.corner_radius_top_left = 6
	close_hover.corner_radius_top_right = 6
	close_hover.corner_radius_bottom_left = 6
	close_hover.corner_radius_bottom_right = 6
	close_button.add_theme_stylebox_override("hover", close_hover)

	close_button.add_theme_color_override("font_color", Color.WHITE)
	close_button.add_theme_color_override("font_hover_color", Color.WHITE)
	close_button.pressed.connect(hide_menu)
	header_container.add_child(close_button)

	var separator := HSeparator.new()
	separator.add_theme_constant_override("separation", 8)
	parent.add_child(separator)


func _build_body(parent: VBoxContainer) -> void:
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	parent.add_child(scroll)

	var body := RichTextLabel.new()
	body.bbcode_enabled = true
	body.fit_content = true
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_color_override("default_color", Color(0.85, 0.85, 0.9))
	body.add_theme_font_size_override("normal_font_size", 15)
	body.text = _get_instructions_bbcode()
	scroll.add_child(body)


func _get_instructions_bbcode() -> String:
	return """You are the [b]HUMAN[/b] player (bottom rows) competing against an [b]LLM[/b] (top rows) in a turn-based autochess battle.

[font_size=18][b]— PREPARATION PHASE —[/b][/font_size]
• Both players start with [b]3 gold[/b]
• You receive 3 random unit types to buy from your shop (bottom-right)
• Click a [b]shop button[/b] to select a unit, then click an [b]empty cell[/b] on your side (bottom 2 rows) to place it
• The LLM places units on its side (top 2 rows) automatically
• Prep ends when neither player can place more units

[font_size=18][b]— UNIT TYPES —[/b][/font_size]
• [color=green][b]A[/b][/color] (1g) — Attacks the enemy directly ahead; advances if no target
• [color=purple][b]B[/b][/color] (1g) — Attacks diagonally to the left; advances if no target
• [color=orange][b]C[/b][/color] (1g) — Attacks diagonally to the right; advances if no target
• [color=crimson][b]D[/b][/color] (2g) — Ranged: removes the closest enemy anywhere on the board

[font_size=18][b]— BATTLE PHASE —[/b][/font_size]
• Units fight automatically — no input needed
• Each side takes turns activating one unit at a time
• Priority order: A → B → C → D (ties broken by placement order)
• If the highest-priority unit is blocked, the next unit in priority tries instead
• Units that advance past the opponent's edge escape and earn 1 point

[font_size=18][b]— WINNING —[/b][/font_size]
• The battle ends when neither side can take any more actions
• Your score = units remaining on the board + units that escaped
• Highest score wins
• Equal scores = tie

[i]Press Esc or click the X to close this menu.[/i]"""
