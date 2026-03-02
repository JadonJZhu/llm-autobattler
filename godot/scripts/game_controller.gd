extends Node2D
## Root controller for the autochess game scene.
## Wires together GameBoard, BoardUI, TurnManager, LlmClient, and ShopUI.

# --- Scene references ---

@onready var game_board: GameBoard = $GameBoard
@onready var turn_manager: TurnManager = $TurnManager
@onready var board_ui: BoardUI = $GameBoard/BoardUI
@onready var shop_ui: ShopUI = $UI/ShopUI

# --- State ---

var _llm_shop: Shop
var _human_shop: Shop
var _game_is_over: bool = false
var _instructions_menu: InstructionsMenu
var _llm_fallback: LlmFallback = LlmFallback.new()


func _ready() -> void:
	_connect_signals()
	_setup_instructions_menu()
	_start_game()


func _connect_signals() -> void:
	turn_manager.phase_changed.connect(_on_phase_changed)
	turn_manager.prep_turn_changed.connect(_on_prep_turn_changed)
	turn_manager.human_unit_selected.connect(_on_human_unit_selected)
	turn_manager.prep_placement_made.connect(_on_prep_placement_made)
	turn_manager.battle_step_completed.connect(_on_battle_step_completed)
	turn_manager.game_over.connect(_on_game_over)
	turn_manager.status_updated.connect(_on_status_updated)
	LlmClient.llm_prep_response_received.connect(_on_llm_prep_response_received)
	LlmClient.llm_request_failed.connect(_on_llm_request_failed)
	shop_ui.shop_button_pressed.connect(_on_shop_button_pressed)


# --- Game Flow ---

func _start_game() -> void:
	_game_is_over = false
	_llm_shop = Shop.create_randomized()
	_human_shop = Shop.create_randomized()

	game_board.initialize()
	board_ui.clear()
	board_ui.initialize()
	turn_manager.initialize(game_board, _llm_shop, _human_shop)

	shop_ui.setup(_llm_shop, _human_shop)
	shop_ui.update_turn_label(turn_manager.get_current_phase_label())
	_refresh_shop_ui()
	shop_ui.update_status("Game started! LLM places first.")

	# LLM goes first — trigger immediately
	_trigger_llm_turn()


func _on_shop_button_pressed(type: UnitData.UnitType) -> void:
	turn_manager.select_unit_for_placement(type)


func _on_human_unit_selected(type: UnitData.UnitType) -> void:
	shop_ui.set_selected_human_unit(type)


func _on_prep_placement_made(unit_owner: UnitData.Owner, _unit_type: UnitData.UnitType, _pos: Vector2i) -> void:
	if unit_owner == UnitData.Owner.HUMAN:
		shop_ui.clear_human_selection()


func _on_prep_turn_changed(turn: TurnManager.PrepTurn) -> void:
	shop_ui.update_turn_label(turn_manager.get_current_phase_label())
	_refresh_shop_ui()

	if turn == TurnManager.PrepTurn.LLM:
		_trigger_llm_turn()


func _trigger_llm_turn() -> void:
	if LlmClient.has_api_key():
		shop_ui.update_status("LLM is thinking...")
		LlmClient.request_llm_prep(
			game_board, _llm_shop,
			turn_manager.turn_number, GameLogger.get_previous_game_replay()
		)
	else:
		_apply_fallback_llm_prep()


func _on_llm_prep_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i) -> void:
	var success: bool = turn_manager.apply_llm_prep_placement(unit_type, grid_pos)
	if not success:
		push_warning("LLM placement failed for %s at %s. Falling back to random." % [
			UnitData.TYPE_LABELS[unit_type], str(grid_pos)
		])
		_apply_fallback_llm_prep()
		return
	_refresh_shop_ui()


func _on_llm_request_failed(error_message: String) -> void:
	push_error("LLM request failed: " + error_message)
	shop_ui.update_status("LLM error. Using random placement.")
	_apply_fallback_llm_prep()


func _apply_fallback_llm_prep() -> void:
	var fallback: Dictionary = _llm_fallback.pick_random_placement(game_board, _llm_shop)
	if fallback.is_empty():
		push_warning("LLM has no affordable units. Skipping.")
		return

	var success: bool = turn_manager.apply_llm_prep_placement(
		fallback["unit_type"],
		fallback["position"]
	)
	if not success:
		push_warning("Random LLM placement failed.")
	_refresh_shop_ui()


func _refresh_shop_ui() -> void:
	shop_ui.update_gold_labels(_llm_shop, _human_shop)
	var is_human_prep: bool = (
		turn_manager.phase == TurnManager.GamePhase.PREP
		and turn_manager.prep_turn == TurnManager.PrepTurn.HUMAN
	)
	shop_ui.update_human_shop_buttons(is_human_prep, _human_shop)


func _on_phase_changed(new_phase: TurnManager.GamePhase) -> void:
	shop_ui.update_turn_label(turn_manager.get_current_phase_label())
	if new_phase == TurnManager.GamePhase.BATTLE or new_phase == TurnManager.GamePhase.GAME_OVER:
		shop_ui.disable_all_shop_buttons()


func _on_battle_step_completed(step_result: Dictionary) -> void:
	var event_text: String = step_result.get("event", "")
	shop_ui.update_status("Battle: %s" % event_text)
	shop_ui.update_turn_label(turn_manager.get_current_phase_label())


func _on_game_over(winner, score_data: Dictionary) -> void:
	_game_is_over = true
	var winner_text: String
	if winner == null:
		winner_text = "It's a tie!"
	elif winner == UnitData.Owner.LLM:
		winner_text = "LLM wins!"
	else:
		winner_text = "Human wins!"
	var llm_score: int = int(score_data.get("llm_score", 0))
	var human_score: int = int(score_data.get("human_score", 0))
	var llm_remaining: int = int(score_data.get("llm_remaining", 0))
	var human_remaining: int = int(score_data.get("human_remaining", 0))
	var llm_escaped: int = int(score_data.get("llm_escaped", 0))
	var human_escaped: int = int(score_data.get("human_escaped", 0))
	shop_ui.update_status(
		"%s LLM: %d pts (%d remaining + %d escaped) — Human: %d pts (%d remaining + %d escaped). Click anywhere to restart." % [
			winner_text,
			llm_score, llm_remaining, llm_escaped,
			human_score, human_remaining, human_escaped,
		]
	)


func _on_status_updated(message: String) -> void:
	shop_ui.update_status(message)
	shop_ui.update_gold_labels(_llm_shop, _human_shop)


func _setup_instructions_menu() -> void:
	_instructions_menu = InstructionsMenu.new()
	$UI.add_child(_instructions_menu)


func _unhandled_input(event: InputEvent) -> void:
	if _instructions_menu.is_open():
		return
	if not _game_is_over:
		return
	if event is InputEventMouseButton and event.pressed:
		_restart_game()
	elif event is InputEventKey and event.pressed:
		_restart_game()


func _restart_game() -> void:
	_start_game()
