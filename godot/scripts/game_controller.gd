extends Node2D
## Root controller for the autochess game scene.
## Wires together GameBoard, BoardUI, TurnManager, LlmClient, and ShopUI.

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
var _experiment_runner: ExperimentRunner
var _human_llm_adapter: LlmPlayerAdapter
var experiment_mode: bool = false


func _ready() -> void:
	_setup_reflection_client()
	_setup_experiment_nodes()
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
	elif turn == TurnManager.PrepTurn.HUMAN and experiment_mode:
		_trigger_human_llm_turn()


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
	var llm_score: int = int(score_data.get("llm_score", 0))
	var human_score: int = int(score_data.get("human_score", 0))
	var llm_remaining: int = int(score_data.get("llm_remaining", 0))
	var human_remaining: int = int(score_data.get("human_remaining", 0))
	var llm_escaped: int = int(score_data.get("llm_escaped", 0))
	var human_escaped: int = int(score_data.get("human_escaped", 0))

	if experiment_mode and _experiment_runner.is_running():
		var outcome: Dictionary = score_data.duplicate()
		outcome["winner"] = winner_text
		outcome["battle_steps"] = turn_manager.battle_step_number
		_experiment_runner.record_game_result(outcome)
		GameLogger.log_experiment_game(
			_experiment_runner.current_game,
			_experiment_runner.llm_config.get_label(),
			_experiment_runner.human_config.get_label(),
			outcome
		)
		shop_ui.update_status(
			"[Experiment %s] %s | LLM %d — Human %d" % [
				_experiment_runner.get_progress(), winner_text,
				llm_score, human_score,
			]
		)
		if _experiment_runner.is_running():
			_restart_game()
		return

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


func _setup_experiment_nodes() -> void:
	_experiment_runner = ExperimentRunner.new()
	_experiment_runner.trial_completed.connect(_on_trial_completed)
	add_child(_experiment_runner)

	_human_llm_adapter = LlmPlayerAdapter.new()
	_human_llm_adapter.human_llm_response_received.connect(_on_human_llm_response_received)
	_human_llm_adapter.human_llm_request_failed.connect(_on_human_llm_request_failed)
	add_child(_human_llm_adapter)


func start_experiment(llm_cfg: LlmModeConfig, human_cfg: LlmModeConfig,
		num_games: int = 30) -> void:
	experiment_mode = true
	_mode_config = llm_cfg
	LlmClient.set_mode_config(llm_cfg)
	_human_llm_adapter.set_mode_config(human_cfg)
	GameLogger.clear_history()
	GameLogger.clear_experiment_results()
	_experiment_runner.start_trial(llm_cfg, human_cfg, num_games)
	turn_manager.set_autoplay(true)
	shop_ui.disable_all_shop_buttons()
	_start_game()


func stop_experiment() -> void:
	experiment_mode = false
	_experiment_runner.stop_trial()


func _trigger_human_llm_turn() -> void:
	if _human_llm_adapter.has_api_key():
		shop_ui.update_status("Human (LLM) is thinking...")
		_human_llm_adapter.request_human_llm_prep(
			game_board, _human_shop,
			turn_manager.turn_number, GameLogger.get_game_history()
		)
	else:
		_apply_fallback_human_llm_prep()


func _on_human_llm_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i) -> void:
	var success: bool = turn_manager.apply_human_prep_placement(unit_type, grid_pos)
	if not success:
		push_warning("Human LLM placement failed for %s at %s. Falling back to random." % [
			UnitData.TYPE_LABELS[unit_type], str(grid_pos)
		])
		_apply_fallback_human_llm_prep()
		return
	_refresh_shop_ui()


func _on_human_llm_request_failed(error_message: String) -> void:
	push_error("Human LLM request failed: " + error_message)
	shop_ui.update_status("Human LLM error. Using random placement.")
	_apply_fallback_human_llm_prep()


func _apply_fallback_human_llm_prep() -> void:
	var affordable_types: Array[UnitData.UnitType] = []
	for unit_type in _human_shop.available_types:
		if _human_shop.can_afford(unit_type):
			affordable_types.append(unit_type)
	if affordable_types.is_empty():
		push_warning("Human LLM has no affordable units. Skipping.")
		return

	var chosen_type: UnitData.UnitType = affordable_types[randi() % affordable_types.size()]
	var empty_positions: Array[Vector2i] = game_board.get_empty_positions_for(UnitData.Owner.HUMAN)
	if empty_positions.is_empty():
		push_warning("Human LLM has no empty positions. Skipping.")
		return

	var chosen_pos: Vector2i = empty_positions[randi() % empty_positions.size()]
	var success: bool = turn_manager.apply_human_prep_placement(chosen_type, chosen_pos)
	if not success:
		push_warning("Random human LLM placement failed.")
	_refresh_shop_ui()


func _on_trial_completed(results: Dictionary) -> void:
	experiment_mode = false
	var filename: String = "experiment_%s_vs_%s.json" % [
		results.get("llm_config_label", "unknown"),
		results.get("human_config_label", "unknown"),
	]
	GameLogger.save_experiment_log(filename)
	shop_ui.update_status(
		"Experiment complete! LLM wins: %d | Human wins: %d | Ties: %d" % [
			results.get("llm_wins", 0),
			results.get("human_wins", 0),
			results.get("ties", 0),
		]
	)
	print("Experiment results: ", results)
