extends Node2D
## Root controller for the autochess game scene.
## Wires together GameBoard, BoardUI, TurnManager, LlmClient, and ShopUI.
## Experiment logic is delegated to ExperimentCoordinator.

# --- Scene references ---

@onready var game_board: GameBoard = $GameBoard
@onready var turn_manager: TurnManager = $TurnManager
@onready var board_ui: BoardUI = $GameBoard/BoardUI
@onready var shop_ui: ShopUI = $UI/ShopUI
@onready var main_ui: MainUI = $UI/MainUI

# --- State ---

const REFLECTION_GAME_INTERVAL: int = 5

var _llm_shop: Shop
var _human_shop: Shop
var _game_is_over: bool = false
var _instructions_menu: InstructionsMenu
var _llm_fallback: LlmFallback = LlmFallback.new()
var _mode_config: LlmModeConfig = LlmModeConfig.new()
var _reflection_client: ReflectionClient
var _games_since_reflection: int = 0
var _awaiting_reflection: bool = false
var _experiment_coordinator: ExperimentCoordinator


func _ready() -> void:
	_setup_reflection_client()
	_setup_experiment_coordinator()
	_connect_signals()
	_setup_instructions_menu()
	LlmClient.set_mode_config(_mode_config)
	_start_game()


func _connect_signals() -> void:
	turn_manager.phase_changed.connect(_on_phase_changed)
	turn_manager.prep_turn_changed.connect(_on_prep_turn_changed)
	turn_manager.human_unit_selected.connect(_on_human_unit_selected)
	turn_manager.prep_placement_made.connect(_on_prep_placement_made)
	turn_manager.battle_step_completed.connect(_on_battle_step_completed)
	turn_manager.game_over.connect(_on_game_over)
	turn_manager.status_updated.connect(_on_status_updated)
	turn_manager.autoplay_toggled.connect(_on_autoplay_toggled)
	LlmClient.llm_prep_response_received.connect(_on_llm_prep_response_received)
	LlmClient.llm_request_failed.connect(_on_llm_request_failed)
	LlmClient.llm_reasoning_captured.connect(_on_llm_reasoning_captured)
	shop_ui.shop_button_pressed.connect(_on_shop_button_pressed)
	main_ui.autoplay_toggle_pressed.connect(_on_autoplay_toggle_pressed)
	main_ui.mode_config_changed.connect(_on_mode_config_changed)


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
	elif turn == TurnManager.PrepTurn.HUMAN and _experiment_coordinator.experiment_mode:
		_experiment_coordinator.trigger_human_llm_turn(
			game_board, _human_shop, turn_manager.turn_number
		)


func _trigger_llm_turn() -> void:
	if LlmClient.has_api_key():
		shop_ui.update_status("LLM is thinking...")
		LlmClient.request_llm_prep(
			game_board, _llm_shop,
			turn_manager.turn_number, GameLogger.get_game_history()
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


func _on_llm_reasoning_captured(reasoning_text: String) -> void:
	GameLogger.log_llm_reasoning(reasoning_text)


func _apply_fallback_llm_prep() -> void:
	var fallback: Dictionary = _llm_fallback.pick_random_placement(game_board, _llm_shop)
	if fallback.is_empty():
		push_warning("LLM has no affordable units or space. Skipping turn.")
		shop_ui.update_status("LLM has no valid moves. Skipping.")
		turn_manager.skip_prep_turn()
		_refresh_shop_ui()
		return

	var success: bool = turn_manager.apply_llm_prep_placement(
		fallback["unit_type"],
		fallback["position"]
	)
	if not success:
		push_warning("Random LLM placement failed. Skipping turn.")
		turn_manager.skip_prep_turn()
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
	var in_manual_battle: bool = (
		new_phase == TurnManager.GamePhase.BATTLE
		and not turn_manager.autoplay_enabled
	)
	main_ui.show_manual_hint(in_manual_battle)


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

	if _experiment_coordinator.is_experiment_running():
		var still_running: bool = _experiment_coordinator.record_game_result(
			winner_text, score_data, turn_manager.battle_step_number
		)
		if still_running:
			_restart_game()
		return

	var llm_score: int = int(score_data.get("llm_score", 0))
	var llm_remaining: int = int(score_data.get("llm_remaining", 0))
	var llm_escaped: int = int(score_data.get("llm_escaped", 0))
	var human_score: int = int(score_data.get("human_score", 0))
	var human_remaining: int = int(score_data.get("human_remaining", 0))
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


func _on_autoplay_toggle_pressed() -> void:
	turn_manager.set_autoplay(not turn_manager.autoplay_enabled)


func _on_autoplay_toggled(is_autoplay: bool) -> void:
	main_ui.update_autoplay_button(is_autoplay)
	var in_manual_battle: bool = (
		not is_autoplay
		and turn_manager.phase == TurnManager.GamePhase.BATTLE
	)
	main_ui.show_manual_hint(in_manual_battle)


func _setup_instructions_menu() -> void:
	_instructions_menu = InstructionsMenu.new()
	$UI.add_child(_instructions_menu)


func _unhandled_input(event: InputEvent) -> void:
	if _instructions_menu.is_open():
		return
	if (
		not _game_is_over
		and turn_manager.phase == TurnManager.GamePhase.BATTLE
		and not turn_manager.autoplay_enabled
	):
		if event is InputEventMouseButton and event.pressed:
			turn_manager.advance_manual_step()
			return
	if not _game_is_over:
		return
	if event is InputEventMouseButton and event.pressed:
		_restart_game()
	elif event is InputEventKey and event.pressed:
		_restart_game()


func _restart_game() -> void:
	_games_since_reflection += 1

	if (
		_mode_config.reflection_enabled
		and _games_since_reflection >= REFLECTION_GAME_INTERVAL
		and _reflection_client.has_api_key()
	):
		_awaiting_reflection = true
		shop_ui.update_status("Reflection helper is analyzing...")
		_reflection_client.request_reflection(
			GameLogger.get_game_history(REFLECTION_GAME_INTERVAL),
			GameLogger.get_recent_reasoning(REFLECTION_GAME_INTERVAL)
		)
		return

	_start_game()


func _setup_reflection_client() -> void:
	_reflection_client = ReflectionClient.new()
	_reflection_client.reflection_response_received.connect(_on_reflection_response_received)
	_reflection_client.reflection_request_failed.connect(_on_reflection_request_failed)
	add_child(_reflection_client)


func _on_reflection_response_received(feedback: String) -> void:
	LlmClient.set_reflection_feedback(feedback)
	_games_since_reflection = 0
	if _awaiting_reflection:
		_awaiting_reflection = false
		_start_game()


func _on_reflection_request_failed(error: String) -> void:
	push_warning("Reflection request failed: " + error)
	if _awaiting_reflection:
		_awaiting_reflection = false
		_start_game()


func _on_mode_config_changed(config: LlmModeConfig) -> void:
	_mode_config = config
	LlmClient.set_mode_config(config)


# --- Experiment Mode ---


func _setup_experiment_coordinator() -> void:
	_experiment_coordinator = ExperimentCoordinator.new()
	_experiment_coordinator.experiment_status_updated.connect(_on_experiment_status)
	_experiment_coordinator.experiment_ended.connect(_on_experiment_ended)
	_experiment_coordinator.human_llm_placement_ready.connect(_on_human_llm_placement_ready)
	_experiment_coordinator.human_llm_placement_failed.connect(_on_human_llm_placement_failed)
	add_child(_experiment_coordinator)


func start_experiment(llm_cfg: LlmModeConfig, human_cfg: LlmModeConfig,
		num_games: int = 30) -> void:
	_mode_config = llm_cfg
	LlmClient.set_mode_config(llm_cfg)
	_experiment_coordinator.start_experiment(llm_cfg, human_cfg, num_games)
	turn_manager.set_autoplay(true)
	shop_ui.disable_all_shop_buttons()
	_start_game()


func stop_experiment() -> void:
	_experiment_coordinator.stop_experiment()


func _on_experiment_status(message: String) -> void:
	shop_ui.update_status(message)


func _on_experiment_ended(results: Dictionary) -> void:
	shop_ui.update_status(
		"Experiment complete! LLM wins: %d | Human wins: %d | Ties: %d" % [
			results.get("llm_wins", 0),
			results.get("human_wins", 0),
			results.get("ties", 0),
		]
	)
	print("Experiment results: ", results)


func _on_human_llm_placement_ready(unit_type: UnitData.UnitType, grid_pos: Vector2i) -> void:
	var success: bool = turn_manager.apply_human_prep_placement(unit_type, grid_pos)
	if not success:
		push_warning("Human LLM placement failed for %s at %s. Falling back." % [
			UnitData.TYPE_LABELS[unit_type], str(grid_pos)
		])
		turn_manager.skip_prep_turn()
	_refresh_shop_ui()


func _on_human_llm_placement_failed() -> void:
	turn_manager.skip_prep_turn()
	_refresh_shop_ui()
