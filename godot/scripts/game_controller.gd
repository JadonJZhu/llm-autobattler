extends Node2D
## Root controller for the game scene.
## Wires together GameBoard, TurnManager, LlmClient, and UI elements.
## Uses Claude API when an API key is available, otherwise falls back to random simulation.

@onready var game_board: GameBoard = $GameBoard
@onready var turn_manager: TurnManager = $TurnManager
@onready var score_label: Label = $UI/ScoreLabel
@onready var turn_label: Label = $UI/TurnLabel
@onready var status_label: Label = $UI/StatusLabel


func _ready() -> void:
	_connect_signals()
	_start_game()


func _connect_signals() -> void:
	turn_manager.score_updated.connect(_on_score_updated)
	turn_manager.turn_changed.connect(_on_turn_changed)
	turn_manager.game_won.connect(_on_game_won)
	turn_manager.llm_turn_started.connect(_on_llm_turn_started)
	LlmClient.llm_response_received.connect(_on_llm_response_received)
	LlmClient.llm_request_failed.connect(_on_llm_request_failed)


func _start_game() -> void:
	var board_data: Dictionary = GameBoard.create_simple_board_data()
	game_board.initialize_board(board_data)
	turn_manager.initialize(game_board)
	_update_status("Game started. LLM turn first.")
	turn_manager.start_llm_turn()


func _on_score_updated(score: int, max_score: int) -> void:
	score_label.text = "Score: %d / %d" % [score, max_score]


func _on_turn_changed(current_turn: TurnManager.TurnPhase) -> void:
	turn_label.text = turn_manager.get_current_turn_label()


func _on_game_won(final_score: int) -> void:
	_update_status("LLM wins! Final score: %d" % final_score)
	GameLogger.log_game_result("llm", final_score, turn_manager.turn_number)
	GameLogger.save_log()


func _on_llm_turn_started() -> void:
	if LlmClient.has_api_key():
		_update_status("LLM is thinking...")
		LlmClient.request_llm_turn(game_board, turn_manager.turn_number, GameLogger.get_entries())
	else:
		_simulate_llm_turn()


func _on_llm_response_received(flip_pos: Vector2i, lock_pos: Vector2i, thinking_text: String) -> void:
	var flip_success: bool = turn_manager.apply_llm_flip(flip_pos)
	if not flip_success:
		push_warning("LLM flip failed at (%d, %d). Falling back to random." % [flip_pos.y, flip_pos.x])
		_simulate_llm_turn()
		return

	var lock_success: bool = turn_manager.apply_llm_lock(lock_pos)
	if not lock_success:
		push_warning("LLM lock failed at (%d, %d)." % [lock_pos.y, lock_pos.x])

	var score: int = game_board.get_correctness_score()
	GameLogger.log_llm_turn(
		turn_manager.turn_number, flip_pos, lock_pos, score,
		thinking_text.left(2000)
	)

	var serialized: String = BoardSerializer.serialize(game_board)
	print("Board state:\n" + serialized)
	var lock_tile: Tile = game_board.get_tile(lock_pos)
	var lock_action: String = "locked" if lock_tile.is_locked else "unlocked"
	_update_status("LLM flipped (%d,%d), %s (%d,%d). Score: %d. Your turn!" % [
		flip_pos.y, flip_pos.x, lock_action, lock_pos.y, lock_pos.x, score
	])


func _on_llm_request_failed(error_message: String) -> void:
	push_error("LLM request failed: " + error_message)
	_update_status("LLM error. Using random move.")
	_simulate_llm_turn()


func _simulate_llm_turn() -> void:
	var flip_pos: Vector2i = _pick_random_arrow_position()
	var lock_pos: Vector2i = _pick_random_arrow_position_for_lock(flip_pos)

	var flip_success: bool = turn_manager.apply_llm_flip(flip_pos)
	if not flip_success:
		_update_status("LLM flip failed at (%d, %d)" % [flip_pos.x, flip_pos.y])
		return

	var lock_success: bool = turn_manager.apply_llm_lock(lock_pos)
	if not lock_success:
		_update_status("LLM lock toggle failed at (%d, %d)" % [lock_pos.x, lock_pos.y])
		return

	var score: int = game_board.get_correctness_score()
	GameLogger.log_llm_turn(
		turn_manager.turn_number, flip_pos, lock_pos, score, "random simulation"
	)

	var serialized: String = BoardSerializer.serialize(game_board)
	print("Board state:\n" + serialized)
	var lock_tile: Tile = game_board.get_tile(lock_pos)
	var lock_action: String = "locked" if lock_tile.is_locked else "unlocked"
	_update_status("LLM flipped (%d,%d), %s (%d,%d). Your turn!" % [
		flip_pos.x, flip_pos.y, lock_action, lock_pos.x, lock_pos.y
	])


func _pick_random_arrow_position() -> Vector2i:
	var arrow_positions: Array[Vector2i] = []
	for pos: Vector2i in game_board.tiles:
		var tile: Tile = game_board.tiles[pos]
		if tile.tile_type == Tile.TileType.ARROW and not tile.is_locked:
			arrow_positions.append(pos)
	if arrow_positions.is_empty():
		return Vector2i(-1, -1)
	return arrow_positions[randi() % arrow_positions.size()]


func _pick_random_arrow_position_for_lock(exclude: Vector2i) -> Vector2i:
	var arrow_positions: Array[Vector2i] = []
	for pos: Vector2i in game_board.tiles:
		var tile: Tile = game_board.tiles[pos]
		if tile.tile_type == Tile.TileType.ARROW and pos != exclude:
			arrow_positions.append(pos)
	if arrow_positions.is_empty():
		return Vector2i(-1, -1)
	return arrow_positions[randi() % arrow_positions.size()]


func _update_status(text: String) -> void:
	status_label.text = text
