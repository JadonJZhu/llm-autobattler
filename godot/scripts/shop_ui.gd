class_name ShopUI
extends Control
## Owns all shop UI: gold labels, shop buttons, turn label, and status label.
## Emits shop_button_pressed when the human player selects a unit to buy.

signal shop_button_pressed(unit_type: Unit.UnitType)

const UI_X_OFFSET: float = 700.0
const UI_WIDTH: float = 300.0
const LABEL_FONT_SIZE: int = 20
const SHOP_BUTTON_SIZE: Vector2 = Vector2(80, 40)
const SHOP_BUTTON_CORNER_RADIUS: int = 4
const SHOP_BUTTON_BORDER_WIDTH: int = 0

var _llm_gold_label: Label
var _llm_shop_container: HBoxContainer
var _human_gold_label: Label
var _human_shop_container: HBoxContainer
var _turn_label: Label
var _status_label: Label
var _human_shop_buttons: Array[Button] = []
var _llm_shop_buttons: Array[Button] = []


func _ready() -> void:
	_build_layout()


# --- Public API ---

func setup(llm_shop: Shop, human_shop: Shop) -> void:
	_build_human_shop_ui(human_shop)
	_build_llm_shop_ui(llm_shop)


func update_gold_labels(llm_shop: Shop, human_shop: Shop) -> void:
	_llm_gold_label.text = "LLM Gold: %d" % llm_shop.gold
	_human_gold_label.text = "Human Gold: %d" % human_shop.gold


func update_turn_label(text: String) -> void:
	_turn_label.text = text


func update_status(text: String) -> void:
	_status_label.text = text


func update_human_shop_buttons(is_human_prep: bool, human_shop: Shop) -> void:
	for i in range(_human_shop_buttons.size()):
		var type: Unit.UnitType = human_shop.available_types[i]
		_human_shop_buttons[i].disabled = not is_human_prep or not human_shop.can_afford(type)


func disable_all_shop_buttons() -> void:
	for button in _human_shop_buttons:
		button.disabled = true


# --- Private ---

func _build_layout() -> void:
	_llm_gold_label = _create_label(Vector2(UI_X_OFFSET, 10.0), LABEL_FONT_SIZE)
	add_child(_llm_gold_label)

	_llm_shop_container = HBoxContainer.new()
	_llm_shop_container.position = Vector2(UI_X_OFFSET, 40.0)
	add_child(_llm_shop_container)

	_turn_label = _create_label(Vector2(UI_X_OFFSET, 250.0), LABEL_FONT_SIZE)
	add_child(_turn_label)

	_status_label = _create_label(Vector2(UI_X_OFFSET, 290.0), 0)
	_status_label.custom_minimum_size = Vector2(560.0, 60.0)
	_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(_status_label)

	_human_gold_label = _create_label(Vector2(UI_X_OFFSET, 550.0), LABEL_FONT_SIZE)
	add_child(_human_gold_label)

	_human_shop_container = HBoxContainer.new()
	_human_shop_container.position = Vector2(UI_X_OFFSET, 580.0)
	add_child(_human_shop_container)


func _create_label(pos: Vector2, font_size: int) -> Label:
	var label := Label.new()
	label.position = pos
	label.size = Vector2(UI_WIDTH, 30.0)
	if font_size > 0:
		label.add_theme_font_size_override("font_size", font_size)
	return label


func _build_human_shop_ui(human_shop: Shop) -> void:
	for button in _human_shop_buttons:
		button.queue_free()
	_human_shop_buttons.clear()

	for type in human_shop.available_types:
		var button := _create_shop_button(type, Unit.Owner.HUMAN)
		button.pressed.connect(shop_button_pressed.emit.bind(type))
		_human_shop_container.add_child(button)
		_human_shop_buttons.append(button)


func _build_llm_shop_ui(llm_shop: Shop) -> void:
	for button in _llm_shop_buttons:
		button.queue_free()
	_llm_shop_buttons.clear()

	for type in llm_shop.available_types:
		var button := _create_shop_button(type, Unit.Owner.LLM)
		button.disabled = true
		_llm_shop_container.add_child(button)
		_llm_shop_buttons.append(button)


func _create_shop_button(type: Unit.UnitType, owner: Unit.Owner) -> Button:
	var label_text: String = Unit.TYPE_LABELS[type]
	var cost: int = Unit.UNIT_COSTS[type]
	var button := Button.new()
	button.text = "%s (%dg)" % [label_text, cost]
	button.custom_minimum_size = SHOP_BUTTON_SIZE

	var normal_style := StyleBoxFlat.new()
	normal_style.bg_color = Unit.TYPE_COLORS[type]
	normal_style.border_color = Unit.OWNER_COLORS[owner]
	_apply_shop_button_shape(normal_style)
	button.add_theme_stylebox_override("normal", normal_style)

	var hover_style := StyleBoxFlat.new()
	hover_style.bg_color = Unit.TYPE_COLORS[type].lightened(0.15)
	hover_style.border_color = Unit.OWNER_COLORS[owner].lightened(0.15)
	_apply_shop_button_shape(hover_style)
	button.add_theme_stylebox_override("hover", hover_style)

	var pressed_style := StyleBoxFlat.new()
	pressed_style.bg_color = Unit.TYPE_COLORS[type].darkened(0.15)
	pressed_style.border_color = Unit.OWNER_COLORS[owner]
	_apply_shop_button_shape(pressed_style)
	button.add_theme_stylebox_override("pressed", pressed_style)

	var disabled_style := StyleBoxFlat.new()
	disabled_style.bg_color = Unit.TYPE_COLORS[type].darkened(0.4)
	disabled_style.border_color = Color(0.3, 0.3, 0.3)
	_apply_shop_button_shape(disabled_style)
	button.add_theme_stylebox_override("disabled", disabled_style)

	button.add_theme_color_override("font_color", Color.WHITE)
	button.add_theme_color_override("font_hover_color", Color.WHITE)
	button.add_theme_color_override("font_pressed_color", Color.WHITE)
	button.add_theme_color_override("font_disabled_color", Color(0.7, 0.7, 0.7))

	return button


func _apply_shop_button_shape(style: StyleBoxFlat) -> void:
	style.border_width_bottom = SHOP_BUTTON_BORDER_WIDTH
	style.border_width_top = SHOP_BUTTON_BORDER_WIDTH
	style.border_width_left = SHOP_BUTTON_BORDER_WIDTH
	style.border_width_right = SHOP_BUTTON_BORDER_WIDTH
	style.corner_radius_top_left = SHOP_BUTTON_CORNER_RADIUS
	style.corner_radius_top_right = SHOP_BUTTON_CORNER_RADIUS
	style.corner_radius_bottom_left = SHOP_BUTTON_CORNER_RADIUS
	style.corner_radius_bottom_right = SHOP_BUTTON_CORNER_RADIUS
