class_name BoardUI
extends Node2D
## Owns cell button creation and visual styling for the game grid.
## Buttons are children of this node; presses re-emit game_board.cell_clicked.

const CELL_BORDER_WIDTH: int = 2

const LLM_CELL_BG: Color = Color(0.197, 0.0, 0.729, 0.85)
const LLM_CELL_BORDER: Color = Color(0.3, 0.4, 0.7)
const LLM_CELL_HOVER_BG: Color = Color(0.25, 0.3, 0.5, 0.9)
const HUMAN_CELL_BG: Color = Color(0.4, 0.2, 0.2, 0.85)
const HUMAN_CELL_BORDER: Color = Color(0.7, 0.35, 0.3)
const HUMAN_CELL_HOVER_BG: Color = Color(0.5, 0.25, 0.25, 0.9)

@export var game_board: GameBoard

var _cell_buttons: Dictionary = {}  # Vector2i -> Button


func initialize() -> void:
	_create_cell_buttons()


func clear() -> void:
	for pos: Vector2i in _cell_buttons:
		_cell_buttons[pos].queue_free()
	_cell_buttons.clear()


# --- Private ---

func _create_cell_buttons() -> void:
	for row in range(GameBoard.ROWS):
		var is_llm_row: bool = row in GameBoard.LLM_ROWS
		var bg_color: Color = LLM_CELL_BG if is_llm_row else HUMAN_CELL_BG
		var border_color: Color = LLM_CELL_BORDER if is_llm_row else HUMAN_CELL_BORDER
		var hover_bg_color: Color = LLM_CELL_HOVER_BG if is_llm_row else HUMAN_CELL_HOVER_BG

		for col in range(GameBoard.COLS):
			var pos := Vector2i(row, col)
			var button := Button.new()
			button.custom_minimum_size = Vector2(GameBoard.CELL_SIZE, GameBoard.CELL_SIZE)
			button.size = Vector2(GameBoard.CELL_SIZE, GameBoard.CELL_SIZE)
			button.position = game_board.grid_to_world(pos)

			var style: StyleBoxFlat = StyleUtils.create_flat_style(
				bg_color,
				border_color,
				CELL_BORDER_WIDTH
			)
			button.add_theme_stylebox_override("normal", style)

			var hover_style: StyleBoxFlat = StyleUtils.create_flat_style(
				hover_bg_color,
				border_color,
				CELL_BORDER_WIDTH
			)
			button.add_theme_stylebox_override("hover", hover_style)

			button.pressed.connect(_on_cell_button_pressed.bind(pos))
			add_child(button)
			_cell_buttons[pos] = button


func _on_cell_button_pressed(pos: Vector2i) -> void:
	game_board.cell_clicked.emit(pos)
