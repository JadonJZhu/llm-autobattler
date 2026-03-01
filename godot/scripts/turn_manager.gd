class_name TurnManager
extends Node
## Manages turn alternation between the LLM and human player.
## Checks win condition after each turn.

signal turn_changed(current_turn: TurnPhase)
signal game_won(final_score: int)
signal llm_turn_started
signal human_turn_started
signal score_updated(score: int, max_score: int)

enum TurnPhase { LLM_FLIP, LLM_LOCK, HUMAN, GAME_OVER }

var current_turn: TurnPhase = TurnPhase.LLM_FLIP
var turn_number: int = 0
var _board: GameBoard


func initialize(board: GameBoard) -> void:
	_board = board
	_board.tile_clicked.connect(_on_tile_clicked)
	current_turn = TurnPhase.LLM_FLIP
	turn_number = 0
	_emit_score()


func start_llm_turn() -> void:
	current_turn = TurnPhase.LLM_FLIP
	turn_number += 1
	turn_changed.emit(current_turn)
	llm_turn_started.emit()


func apply_llm_flip(grid_pos: Vector2i) -> bool:
	if current_turn != TurnPhase.LLM_FLIP:
		return false
	var success: bool = _board.flip_tile(grid_pos)
	if success:
		current_turn = TurnPhase.LLM_LOCK
		turn_changed.emit(current_turn)
		_emit_score()
	return success


func apply_llm_lock(grid_pos: Vector2i) -> bool:
	if current_turn != TurnPhase.LLM_LOCK:
		return false
	var success: bool = _board.toggle_lock_tile(grid_pos)
	if success:
		if _check_win():
			return true
		current_turn = TurnPhase.HUMAN
		turn_changed.emit(current_turn)
		human_turn_started.emit()
	return success


func _on_tile_clicked(grid_pos: Vector2i) -> void:
	if current_turn != TurnPhase.HUMAN:
		return
	var tile: Tile = _board.get_tile(grid_pos)
	if tile == null or tile.is_locked or tile.tile_type != Tile.TileType.ARROW:
		return

	_board.flip_tile(grid_pos)
	_emit_score()

	if _check_win():
		return

	start_llm_turn()


func _check_win() -> bool:
	var score: int = _board.get_correctness_score()
	var max_score: int = _board.get_max_correctness_score()
	if score >= max_score:
		current_turn = TurnPhase.GAME_OVER
		turn_changed.emit(current_turn)
		game_won.emit(score)
		return true
	return false


func _emit_score() -> void:
	var score: int = _board.get_correctness_score()
	var max_score: int = _board.get_max_correctness_score()
	score_updated.emit(score, max_score)


func get_current_turn_label() -> String:
	match current_turn:
		TurnPhase.LLM_FLIP:
			return "LLM Turn (Flip)"
		TurnPhase.LLM_LOCK:
			return "LLM Turn (Lock)"
		TurnPhase.HUMAN:
			return "Human Turn"
		TurnPhase.GAME_OVER:
			return "Game Over"
	return "Unknown"
