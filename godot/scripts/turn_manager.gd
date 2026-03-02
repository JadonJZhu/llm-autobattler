class_name TurnManager
extends Node
## Central orchestrator for both the preparation and battle phases.

# --- Enums ---

enum GamePhase { PREP, BATTLE, GAME_OVER }
enum PrepTurn { HUMAN, LLM }

# --- Signals ---

signal phase_changed(phase: GamePhase)
signal prep_turn_changed(turn: PrepTurn)
signal human_unit_selected(unit_type: Unit.UnitType)
signal prep_placement_made(unit_owner: Unit.Owner, unit_type: Unit.UnitType, pos: Vector2i)
signal battle_step_completed(step_result: Dictionary)
signal game_over(winner, score_data: Dictionary)  # Unit.Owner or null for tie
signal status_updated(message: String)

# --- Exports ---

@export var battle_step_delay_seconds: float = 0.8

# --- State ---

var phase: GamePhase = GamePhase.PREP
var prep_turn: PrepTurn = PrepTurn.LLM
var turn_number: int = 0
var battle_step_number: int = 0

var _board: GameBoard
var _llm_shop: Shop
var _human_shop: Shop
var _battle_engine: BattleEngine
var _battle_snapshot: Dictionary
var _battle_active_owner: Unit.Owner
var _battle_timer: Timer
var _selected_unit_type: Unit.UnitType = Unit.UnitType.A
var _has_selection: bool = false


# --- Initialization ---

func initialize(board: GameBoard, llm_shop: Shop, human_shop: Shop) -> void:
	_board = board
	_llm_shop = llm_shop
	_human_shop = human_shop
	_battle_engine = BattleEngine.new()

	if not _board.cell_clicked.is_connected(_on_cell_clicked):
		_board.cell_clicked.connect(_on_cell_clicked)

	phase = GamePhase.PREP
	prep_turn = PrepTurn.LLM
	turn_number = 0
	battle_step_number = 0
	_has_selection = false

	# Create battle timer
	if _battle_timer:
		_battle_timer.queue_free()
	_battle_timer = Timer.new()
	_battle_timer.one_shot = true
	_battle_timer.wait_time = battle_step_delay_seconds
	_battle_timer.timeout.connect(_on_battle_timer_timeout)
	add_child(_battle_timer)

	phase_changed.emit(phase)
	prep_turn_changed.emit(prep_turn)


# --- Prep Phase: Human ---

func select_unit_for_placement(type: Unit.UnitType) -> void:
	if phase != GamePhase.PREP or prep_turn != PrepTurn.HUMAN:
		return
	if not _human_shop.can_afford(type):
		status_updated.emit("Cannot afford unit type %s" % Unit.TYPE_LABELS[type])
		return
	_selected_unit_type = type
	_has_selection = true
	human_unit_selected.emit(type)
	status_updated.emit("Selected %s — click a cell to place" % Unit.TYPE_LABELS[type])


func _on_cell_clicked(pos: Vector2i) -> void:
	if phase != GamePhase.PREP or prep_turn != PrepTurn.HUMAN:
		return
	if not _has_selection:
		status_updated.emit("Select a unit type from the shop first")
		return
	if not _board.is_position_valid_for(Unit.Owner.HUMAN, pos):
		status_updated.emit("You can only place units on your side (rows 2-3)")
		return
	if _board.get_snapshot().has(pos):
		status_updated.emit("Cell already occupied")
		return

	# Purchase and place
	if not _human_shop.purchase(_selected_unit_type):
		status_updated.emit("Cannot afford that unit")
		return

	_board.place_unit(_selected_unit_type, Unit.Owner.HUMAN, pos)
	turn_number += 1
	_has_selection = false

	var type_label: String = Unit.TYPE_LABELS[_selected_unit_type]
	status_updated.emit("Human placed %s at (%d, %d) | Gold: %d" % [
		type_label, pos.x, pos.y, _human_shop.gold
	])

	GameLogger.log_prep_placement(turn_number, "human", type_label, pos, _human_shop.gold)
	prep_placement_made.emit(Unit.Owner.HUMAN, _selected_unit_type, pos)

	_check_prep_over()


# --- Prep Phase: LLM ---

func apply_llm_prep_placement(type: Unit.UnitType, pos: Vector2i) -> bool:
	if phase != GamePhase.PREP or prep_turn != PrepTurn.LLM:
		return false
	if not _board.is_position_valid_for(Unit.Owner.LLM, pos):
		push_error("TurnManager: Invalid LLM placement position: %s" % str(pos))
		return false
	if not _llm_shop.can_afford(type):
		push_error("TurnManager: LLM cannot afford unit type: %s" % Unit.TYPE_LABELS[type])
		return false

	_llm_shop.purchase(type)
	_board.place_unit(type, Unit.Owner.LLM, pos)
	turn_number += 1

	var type_label: String = Unit.TYPE_LABELS[type]
	status_updated.emit("LLM placed %s at (%d, %d) | Gold: %d" % [
		type_label, pos.x, pos.y, _llm_shop.gold
	])

	GameLogger.log_prep_placement(turn_number, "llm", type_label, pos, _llm_shop.gold)
	prep_placement_made.emit(Unit.Owner.LLM, type, pos)

	_check_prep_over()
	return true


func _check_prep_over() -> void:
	var llm_can_buy: bool = _llm_shop.can_afford_any()
	var human_can_buy: bool = _human_shop.can_afford_any()

	# Also check if there are empty positions
	var llm_has_space: bool = not _board.get_empty_positions_for(Unit.Owner.LLM).is_empty()
	var human_has_space: bool = not _board.get_empty_positions_for(Unit.Owner.HUMAN).is_empty()

	var llm_done: bool = not llm_can_buy or not llm_has_space
	var human_done: bool = not human_can_buy or not human_has_space

	if llm_done and human_done:
		_start_battle()
		return

	# Switch turns
	if prep_turn == PrepTurn.LLM:
		if human_done:
			# Human is done, LLM goes again
			prep_turn = PrepTurn.LLM
		else:
			prep_turn = PrepTurn.HUMAN
	else:
		if llm_done:
			# LLM is done, human goes again
			prep_turn = PrepTurn.HUMAN
		else:
			prep_turn = PrepTurn.LLM

	prep_turn_changed.emit(prep_turn)


# --- Battle Phase ---

func _start_battle() -> void:
	phase = GamePhase.BATTLE
	battle_step_number = 0
	_battle_snapshot = _board.get_snapshot()
	_battle_active_owner = Unit.Owner.LLM  # LLM always goes first
	GameLogger.record_battle_start(BoardSerializer.serialize_snapshot(_battle_snapshot))

	status_updated.emit("Battle begins! LLM moves first.")
	phase_changed.emit(phase)

	# Start the first battle step after a delay
	_battle_timer.start()


func _on_battle_timer_timeout() -> void:
	if phase != GamePhase.BATTLE:
		return

	battle_step_number += 1
	var step_result: Dictionary = _battle_engine.execute_step(
		_battle_snapshot, _battle_active_owner
	)

	# Apply visual changes to the board
	_board.apply_battle_step(step_result)

	var owner_label: String = "LLM" if _battle_active_owner == Unit.Owner.LLM else "Human"
	GameLogger.log_battle_step(battle_step_number, owner_label, step_result["event"])

	battle_step_completed.emit(step_result)

	if step_result["is_finished"]:
		_end_game(step_result)
		return

	# Toggle active owner
	if _battle_active_owner == Unit.Owner.LLM:
		_battle_active_owner = Unit.Owner.HUMAN
	else:
		_battle_active_owner = Unit.Owner.LLM

	# Schedule next step
	_battle_timer.start()


func _end_game(step_result: Dictionary) -> void:
	phase = GamePhase.GAME_OVER
	var winner = step_result.get("winner", null)

	var winner_label: String
	if winner == null:
		winner_label = "Tie"
	elif winner == Unit.Owner.LLM:
		winner_label = "LLM"
	else:
		winner_label = "Human"

	var score_data: Dictionary = {
		"llm_score": int(step_result.get("llm_score", 0)),
		"human_score": int(step_result.get("human_score", 0)),
		"llm_remaining": int(step_result.get("llm_remaining", 0)),
		"human_remaining": int(step_result.get("human_remaining", 0)),
		"llm_escaped": int(step_result.get("llm_escaped", 0)),
		"human_escaped": int(step_result.get("human_escaped", 0)),
	}

	GameLogger.set_current_game_score_data(score_data)
	GameLogger.finalize_game_replay(winner_label)
	GameLogger.log_game_result(
		winner_label,
		-1,
		-1,
		turn_number,
		battle_step_number
	)
	GameLogger.save_log()

	status_updated.emit(
		"Game Over! %s | LLM %d (%d remaining + %d escaped) vs Human %d (%d remaining + %d escaped)" % [
			winner_label,
			score_data["llm_score"], score_data["llm_remaining"], score_data["llm_escaped"],
			score_data["human_score"], score_data["human_remaining"], score_data["human_escaped"],
		]
	)
	phase_changed.emit(phase)
	game_over.emit(winner, score_data)


# --- Utility ---

func get_current_phase_label() -> String:
	match phase:
		GamePhase.PREP:
			var turn_label: String = "LLM" if prep_turn == PrepTurn.LLM else "Human"
			return "Prep Phase — %s's turn" % turn_label
		GamePhase.BATTLE:
			return "Battle Phase — Step %d" % battle_step_number
		GamePhase.GAME_OVER:
			return "Game Over"
	return "Unknown"
