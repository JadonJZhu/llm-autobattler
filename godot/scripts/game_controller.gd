extends Node2D
## Root controller for the autochess game scene.
## Wires together GameBoard, BoardUI, TurnManager, LlmClient, and ShopUI.
## Experiment logic is handled by puzzle runners.

# --- Scene references ---

@onready var game_board: GameBoard = $GameBoard
@onready var turn_manager: TurnManager = $TurnManager
@onready var board_ui: BoardUI = $GameBoard/BoardUI
@onready var shop_ui: ShopUI = $UI/ShopUI
@onready var main_ui: MainUI = $UI/MainUI

# --- State ---

const REFLECTION_GAME_INTERVAL: int = 2
const REASONING_SUMMARY_MAX_CHARS: int = 275
const DEFAULT_PUZZLE_PATH: String = "res://puzzles/puzzle_suite.json"
const ABLATION_MAX_API_ERRORS: int = 5
const ABLATION_RETRY_BASE_DELAY_SECONDS: float = 2.0
const ABLATION_RETRY_MAX_DELAY_SECONDS: float = 30.0
const ABLATION_RETRY_JITTER_SECONDS: float = 0.75
const CLI_MINI_CONFIG_LABELS: Array[String] = ["I0_E0_R0", "I1_E1_R1"]
const PUZZLE_LOADER_SCRIPT = preload("res://scripts/puzzle_loader.gd")
const PUZZLE_RUNNER_SCRIPT = preload("res://scripts/puzzle_runner.gd")
const ABLATION_RUNNER_SCRIPT = preload("res://scripts/ablation_runner.gd")
const PUZZLE_LOGGER_SCRIPT = preload("res://scripts/puzzle_logger.gd")

var _llm_shop: Shop
var _human_shop: Shop
var _game_is_over: bool = false
var _instructions_menu: InstructionsMenu
var _llm_fallback: LlmFallback = LlmFallback.new()
var _mode_config: LlmModeConfig = LlmModeConfig.new()
var _reflection_client: ReflectionClient
var _games_since_reflection: int = 0
var _awaiting_reflection: bool = false
var _puzzle_loader = PUZZLE_LOADER_SCRIPT.new()
var _puzzle_runner: Node
var _ablation_runner: Node
var _puzzle_logger = PUZZLE_LOGGER_SCRIPT.new()
var _puzzle_mode_enabled: bool = false
var _mini_ablation_active: bool = false
var _active_puzzle_scenario = null
var _opponent_placements_queue: Array[Dictionary] = []
var _ablation_api_error_count: int = 0
var _ablation_retry_rng: RandomNumberGenerator = RandomNumberGenerator.new()
var _ablation_retry_pending: bool = false
var _cli_ablation_mode: bool = false
var _cli_output_prefix: String = ""


func _ready() -> void:
	_ablation_retry_rng.randomize()
	_setup_reflection_client()
	_setup_puzzle_system()
	_connect_signals()
	_setup_instructions_menu()
	LlmClient.set_mode_config(_mode_config)

	var cli_args: Dictionary = _parse_cli_args()
	if bool(cli_args.get("ablation", false)) or bool(cli_args.get("mini_ablation", false)):
		_start_cli_ablation(cli_args)
		return

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
	if _puzzle_mode_enabled and _puzzle_runner != null and _puzzle_runner.is_running():
		_llm_shop = _build_fixed_shop(
			_active_puzzle_scenario.llm_shop_types,
			_active_puzzle_scenario.llm_gold
		)
		_human_shop = _build_fixed_shop(
			_active_puzzle_scenario.opponent_shop_types,
			_active_puzzle_scenario.opponent_gold
		)
		_opponent_placements_queue = _puzzle_runner.get_opponent_queue_snapshot()
	else:
		_llm_shop = Shop.create_randomized()
		_human_shop = Shop.create_randomized()
		_opponent_placements_queue.clear()

	game_board.initialize()
	board_ui.clear()
	board_ui.initialize()
	turn_manager.initialize(game_board, _llm_shop, _human_shop)
	turn_manager.set_scripted_human_done(
		_puzzle_mode_enabled
		and _puzzle_runner != null
		and _puzzle_runner.is_running()
		and _opponent_placements_queue.is_empty()
	)

	shop_ui.setup(_llm_shop, _human_shop)
	shop_ui.clear_reasoning_summary()
	shop_ui.update_turn_label(turn_manager.get_current_phase_label())
	_refresh_shop_ui()
	# In fallback mode, LLM placement can complete synchronously during initialize().
	# Only show thinking text if it is still the LLM's prep turn.
	if (
		turn_manager.phase == TurnManager.GamePhase.PREP
		and turn_manager.prep_turn == TurnManager.PrepTurn.LLM
	):
		if _puzzle_mode_enabled and _puzzle_runner != null and _puzzle_runner.is_running():
			shop_ui.update_status(
				"Puzzle %s (attempt %d/%d) started. LLM is thinking..." % [
					_active_puzzle_scenario.id,
					_puzzle_runner.current_attempt,
					_puzzle_runner.max_attempts,
				]
			)
		else:
			shop_ui.update_status("Game started! LLM places first. LLM is thinking...")


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
	elif turn == TurnManager.PrepTurn.HUMAN:
		if _puzzle_mode_enabled and _puzzle_runner != null and _puzzle_runner.is_running():
			_apply_scripted_opponent_turn()


func _trigger_llm_turn() -> void:
	if LlmClient.has_api_key():
		shop_ui.clear_reasoning_summary()
		shop_ui.update_status("LLM is thinking...")
		LlmClient.request_llm_prep(
			game_board, _llm_shop, _human_shop,
			turn_manager.turn_number, GameLogger.get_game_history()
		)
	else:
		_apply_fallback_llm_prep()


func _on_llm_prep_response_received(unit_type: UnitData.UnitType, grid_pos: Vector2i) -> void:
	if _is_ablation_running():
		_ablation_api_error_count = 0
		_ablation_retry_pending = false

	var success: bool = turn_manager.apply_llm_prep_placement(unit_type, grid_pos)
	if not success:
		push_warning("LLM placement failed for %s at %s. Falling back to random." % [
			UnitData.TYPE_LABELS[unit_type], str(grid_pos)
		])
		_apply_fallback_llm_prep()
		return
	_refresh_shop_ui()


func _on_llm_request_failed(error_message: String, is_api_error: bool, error_meta: Dictionary = {}) -> void:
	push_error("LLM request failed: " + error_message)
	if _is_ablation_running() and is_api_error:
		_ablation_api_error_count += 1
		if _ablation_api_error_count >= ABLATION_MAX_API_ERRORS:
			var failure_reason: String = (
				"Ablation terminated after %d consecutive LLM API errors. Last error: %s"
				% [ABLATION_MAX_API_ERRORS, error_message]
			)
			shop_ui.update_status(
				"Ablation API error %d/%d. Terminating run." % [
					_ablation_api_error_count, ABLATION_MAX_API_ERRORS
				]
			)
			_terminate_ablation_due_to_api_failure(failure_reason)
			return

		var delay_seconds: float = _compute_ablation_retry_delay_seconds(error_meta)
		shop_ui.update_status(
			"LLM API error during ablation (%d/%d). Retrying in %.1fs..." % [
				_ablation_api_error_count, ABLATION_MAX_API_ERRORS, delay_seconds
			]
		)
		_schedule_ablation_retry(delay_seconds)
		return

	shop_ui.update_status("LLM error. Using random placement.")
	_apply_fallback_llm_prep()


func _on_llm_reasoning_captured(reasoning_text: String) -> void:
	GameLogger.log_llm_reasoning(reasoning_text)
	shop_ui.show_reasoning_summary(_extract_reasoning_summary(reasoning_text))


func _extract_reasoning_summary(reasoning_text: String) -> String:
	var paragraphs: PackedStringArray = reasoning_text.split("\n\n")
	for i in range(paragraphs.size() - 1, -1, -1):
		var candidate: String = _sanitize_reasoning_text(paragraphs[i])
		if candidate.length() > 10:
			return _truncate_reasoning_summary(candidate)
	return _truncate_reasoning_summary(_sanitize_reasoning_text(reasoning_text))


func _sanitize_reasoning_text(text: String) -> String:
	var cleaned: String = text.strip_edges()
	cleaned = cleaned.replace("**", "")
	cleaned = cleaned.replace("__", "")
	cleaned = cleaned.replace("`", "")
	cleaned = cleaned.replace("#", "")
	cleaned = cleaned.replace("\n", " ")
	while cleaned.contains("  "):
		cleaned = cleaned.replace("  ", " ")
	if cleaned.begins_with("- "):
		cleaned = cleaned.substr(2)
	return cleaned


func _truncate_reasoning_summary(text: String) -> String:
	if text.length() <= REASONING_SUMMARY_MAX_CHARS:
		return text
	return "%s..." % text.left(REASONING_SUMMARY_MAX_CHARS - 3)


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

	if _puzzle_mode_enabled and _puzzle_runner != null and _puzzle_runner.is_running():
		var should_continue: bool = _puzzle_runner.record_attempt_result(
			winner,
			score_data,
			turn_manager.battle_step_number
		)
		if should_continue:
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


func _apply_scripted_opponent_turn() -> void:
	if _puzzle_runner == null:
		return

	var placement: Dictionary = _puzzle_runner.consume_next_opponent_placement()
	_opponent_placements_queue = _puzzle_runner.get_opponent_queue_snapshot()
	turn_manager.set_scripted_human_done(_opponent_placements_queue.is_empty())
	if placement.is_empty():
		shop_ui.update_status("Scripted opponent has no remaining placements. Skipping turn.")
		turn_manager.skip_prep_turn()
		_refresh_shop_ui()
		return

	var success: bool = turn_manager.apply_human_prep_placement(
		placement["unit_type"],
		placement["position"]
	)
	if not success:
		push_warning("Scripted opponent placement failed at %s. Skipping." % str(placement["position"]))
		turn_manager.skip_prep_turn()
	_refresh_shop_ui()


func _build_fixed_shop(types: Array[UnitData.UnitType], starting_gold: int) -> Shop:
	var shop := Shop.new()
	shop.available_types.assign(types)
	shop.gold = maxi(0, starting_gold)
	return shop


# --- Puzzle Ablation Mode ---


func _setup_puzzle_system() -> void:
	_puzzle_runner = PUZZLE_RUNNER_SCRIPT.new()
	_puzzle_runner.attempt_started.connect(_on_puzzle_attempt_started)
	_puzzle_runner.attempt_completed.connect(_on_puzzle_attempt_completed)
	_puzzle_runner.puzzle_completed.connect(_on_puzzle_completed)
	add_child(_puzzle_runner)

	_ablation_runner = ABLATION_RUNNER_SCRIPT.new()
	_ablation_runner.puzzle_requested.connect(_on_ablation_puzzle_requested)
	_ablation_runner.ablation_progress.connect(_on_ablation_progress)
	_ablation_runner.ablation_completed.connect(_on_ablation_completed)
	add_child(_ablation_runner)


func start_ablation(max_attempts_per_puzzle: int = 10,
		puzzle_path: String = DEFAULT_PUZZLE_PATH, configs: Array = []) -> void:
	var puzzles: Array = _puzzle_loader.load_puzzles(puzzle_path)
	if puzzles.is_empty():
		shop_ui.update_status("No puzzles loaded. Check puzzle_suite.json.")
		return

	_mini_ablation_active = false
	_puzzle_mode_enabled = true
	_ablation_api_error_count = 0
	_ablation_retry_pending = false
	turn_manager.set_autoplay(true)
	turn_manager.battle_step_delay_seconds = 0.0
	shop_ui.disable_all_shop_buttons()
	var started: bool = _ablation_runner.start(puzzles, max_attempts_per_puzzle, configs)
	if not started:
		_puzzle_mode_enabled = false


func start_mini_ablation(max_attempts_per_puzzle: int = 3,
		puzzle_path: String = DEFAULT_PUZZLE_PATH, configs: Array = []) -> void:
	var puzzles: Array = _puzzle_loader.load_puzzles(puzzle_path)
	if puzzles.is_empty():
		shop_ui.update_status("No puzzles loaded. Check puzzle_suite.json.")
		return

	var subset: Array = _build_mini_puzzle_subset(puzzles)
	if subset.is_empty():
		shop_ui.update_status("Mini ablation could not build a puzzle subset.")
		return

	var mini_configs: Array = _build_mini_mode_configs()
	if not configs.is_empty():
		mini_configs = configs
	_mini_ablation_active = true
	_puzzle_mode_enabled = true
	_ablation_api_error_count = 0
	_ablation_retry_pending = false
	turn_manager.set_autoplay(true)
	turn_manager.battle_step_delay_seconds = 0.0
	shop_ui.disable_all_shop_buttons()
	var started: bool = _ablation_runner.start(subset, max_attempts_per_puzzle, mini_configs)
	if not started:
		_puzzle_mode_enabled = false
		_mini_ablation_active = false


func stop_ablation() -> void:
	_puzzle_mode_enabled = false
	_mini_ablation_active = false
	_ablation_api_error_count = 0
	_ablation_retry_pending = false
	if _ablation_runner != null:
		_ablation_runner.stop()
	if _puzzle_runner != null:
		_puzzle_runner.stop()
	_active_puzzle_scenario = null
	_opponent_placements_queue.clear()


func _on_ablation_puzzle_requested(config: LlmModeConfig, scenario,
		max_attempts: int) -> void:
	_mode_config = config
	LlmClient.set_mode_config(config)
	LlmClient.set_reflection_feedback("")
	_games_since_reflection = 0
	_active_puzzle_scenario = scenario
	_puzzle_runner.start_puzzle(scenario, config, max_attempts)


func _on_puzzle_attempt_started(scenario_id: String, attempt_number: int, max_attempts: int) -> void:
	shop_ui.update_status(
		"Puzzle %s attempt %d/%d (%s)" % [
			scenario_id,
			attempt_number,
			max_attempts,
			_mode_config.get_label(),
		]
	)
	_start_game()


func _on_puzzle_attempt_completed(result: Dictionary) -> void:
	shop_ui.update_status(
		"Puzzle %s attempt %d complete: %s | score %d-%d" % [
			str(result.get("scenario_id", "")),
			int(result.get("attempt", 0)),
			str(result.get("winner", "")),
			int(result.get("llm_score", 0)),
			int(result.get("opponent_score", 0)),
		]
	)


func _on_puzzle_completed(summary: Dictionary) -> void:
	if _ablation_runner != null and _ablation_runner.is_running():
		_ablation_runner.record_puzzle_summary(summary)
		return

	shop_ui.update_status(
		"Puzzle complete (%s): solved=%s attempts=%d/%d" % [
			str(summary.get("puzzle_id", "")),
			str(summary.get("solved", false)),
			int(summary.get("attempts_needed", 0)),
			int(summary.get("max_attempts", 0)),
		]
	)


func _on_ablation_progress(config_label: String, puzzle_id: String,
		completed: int, total: int) -> void:
	shop_ui.update_status(
		"Ablation progress %d/%d | %s | %s" % [completed, total, config_label, puzzle_id]
	)


func _on_ablation_completed(results: Dictionary) -> void:
	var is_mini_run: bool = _mini_ablation_active
	var terminated_early: bool = bool(results.get("terminated_early", false))
	var termination_reason: String = str(results.get("termination_reason", ""))
	_puzzle_mode_enabled = false
	_mini_ablation_active = false
	_ablation_api_error_count = 0
	_ablation_retry_pending = false
	if _ablation_runner != null:
		_ablation_runner.stop()
	if _puzzle_runner != null:
		_puzzle_runner.stop()
	_active_puzzle_scenario = null
	_opponent_placements_queue.clear()
	var filename_prefix: String = _cli_output_prefix
	if filename_prefix.is_empty():
		filename_prefix = "mini_ablation" if is_mini_run else "ablation"
	var run_label: String = "Mini ablation" if is_mini_run else "Ablation"
	var log_path: String = _puzzle_logger.save_ablation_results(results, filename_prefix)
	if terminated_early:
		shop_ui.update_status(
			"%s terminated early: %s. Partial results saved to %s" % [
				run_label, termination_reason, log_path
			]
		)
	else:
		shop_ui.update_status(
			"%s complete. Results saved to %s" % [run_label, log_path]
		)
	if _cli_ablation_mode:
		var absolute_log_path: String = ""
		if not log_path.is_empty():
			absolute_log_path = ProjectSettings.globalize_path(log_path)
		print("ABLATION_OUTPUT_PATH:%s" % absolute_log_path)
		var exit_code: int = 1 if terminated_early or absolute_log_path.is_empty() else 0
		get_tree().quit(exit_code)


func _build_mini_puzzle_subset(puzzles: Array) -> Array:
	var subset: Array = []
	var seen_difficulties: Dictionary = {}
	for scenario in puzzles:
		var difficulty: int = int(scenario.difficulty)
		if seen_difficulties.has(difficulty):
			continue
		seen_difficulties[difficulty] = true
		subset.append(scenario)
	return subset


func _build_mini_mode_configs() -> Array:
	var baseline := LlmModeConfig.new()
	baseline.instructions_enabled = false
	baseline.examples_enabled = false
	baseline.reflection_enabled = false

	var full := LlmModeConfig.new()
	full.instructions_enabled = true
	full.examples_enabled = true
	full.reflection_enabled = true

	return [baseline, full]


func _parse_cli_args() -> Dictionary:
	var parsed: Dictionary = {
		"ablation": false,
		"mini_ablation": false,
		"config": "",
		"max_attempts": 10,
		"puzzle_path": DEFAULT_PUZZLE_PATH,
		"output_prefix": "",
	}
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var i: int = 0
	while i < args.size():
		var arg: String = args[i]
		match arg:
			"--ablation":
				parsed["ablation"] = true
			"--mini-ablation":
				parsed["mini_ablation"] = true
			"--config":
				if i + 1 < args.size():
					parsed["config"] = String(args[i + 1]).strip_edges()
					i += 1
			"--max-attempts":
				if i + 1 < args.size():
					var attempt_text: String = String(args[i + 1]).strip_edges()
					if attempt_text.is_valid_int():
						parsed["max_attempts"] = maxi(1, int(attempt_text))
					else:
						push_warning("Invalid --max-attempts value: %s (using default 10)." % attempt_text)
					i += 1
			"--puzzle-path":
				if i + 1 < args.size():
					parsed["puzzle_path"] = String(args[i + 1]).strip_edges()
					i += 1
			"--output-prefix":
				if i + 1 < args.size():
					parsed["output_prefix"] = String(args[i + 1]).strip_edges()
					i += 1
		i += 1
	return parsed


func _start_cli_ablation(cli_args: Dictionary) -> void:
	_cli_ablation_mode = true
	_cli_output_prefix = str(cli_args.get("output_prefix", ""))

	var run_mini: bool = bool(cli_args.get("mini_ablation", false))
	var run_full: bool = bool(cli_args.get("ablation", false))
	if run_mini and run_full:
		push_warning("Both --ablation and --mini-ablation were passed; defaulting to --mini-ablation.")
		run_full = false

	var config_label: String = str(cli_args.get("config", "")).strip_edges()
	var filtered_configs: Array = []
	if not config_label.is_empty():
		var config: LlmModeConfig = _build_config_from_label(config_label)
		if config == null:
			push_error("Invalid --config label: %s" % config_label)
			get_tree().quit(1)
			return
		if run_mini and not CLI_MINI_CONFIG_LABELS.has(config_label):
			push_error("Mini ablation only supports configs: %s" % ", ".join(CLI_MINI_CONFIG_LABELS))
			get_tree().quit(1)
			return
		filtered_configs.append(config)

	var max_attempts: int = int(cli_args.get("max_attempts", 10))
	var puzzle_path: String = str(cli_args.get("puzzle_path", DEFAULT_PUZZLE_PATH))
	if run_mini:
		start_mini_ablation(max_attempts, puzzle_path, filtered_configs)
	else:
		start_ablation(max_attempts, puzzle_path, filtered_configs)

	if not _is_ablation_running():
		push_error("CLI ablation failed to start.")
		get_tree().quit(1)


func _build_config_from_label(label: String) -> LlmModeConfig:
	var parts: PackedStringArray = label.strip_edges().split("_")
	if parts.size() != 3:
		return null
	if not parts[0].begins_with("I") or not parts[1].begins_with("E") or not parts[2].begins_with("R"):
		return null
	var i_text: String = parts[0].substr(1)
	var e_text: String = parts[1].substr(1)
	var r_text: String = parts[2].substr(1)
	if not i_text.is_valid_int() or not e_text.is_valid_int() or not r_text.is_valid_int():
		return null
	var i_value: int = int(i_text)
	var e_value: int = int(e_text)
	var r_value: int = int(r_text)
	if i_value < 0 or i_value > 1:
		return null
	if e_value < 0 or e_value > 1:
		return null
	if r_value < 0 or r_value > 1:
		return null
	var config := LlmModeConfig.new()
	config.instructions_enabled = i_value == 1
	config.examples_enabled = e_value == 1
	config.reflection_enabled = r_value == 1
	return config


func _is_ablation_running() -> bool:
	return _ablation_runner != null and _ablation_runner.is_running()


func _terminate_ablation_due_to_api_failure(reason: String) -> void:
	_ablation_retry_pending = false
	if _puzzle_runner != null:
		_puzzle_runner.stop()
	if _ablation_runner != null and _ablation_runner.is_running():
		_ablation_runner.terminate_with_failure(reason)


func _compute_ablation_retry_delay_seconds(error_meta: Dictionary) -> float:
	var retry_after: float = maxf(0.0, float(error_meta.get("retry_after_seconds", 0.0)))
	var exponential: float = ABLATION_RETRY_BASE_DELAY_SECONDS * pow(2.0, float(_ablation_api_error_count - 1))
	var jitter: float = _ablation_retry_rng.randf_range(0.0, ABLATION_RETRY_JITTER_SECONDS)
	var delay_seconds: float = maxf(retry_after, exponential + jitter)
	return minf(ABLATION_RETRY_MAX_DELAY_SECONDS, delay_seconds)


func _schedule_ablation_retry(delay_seconds: float) -> void:
	if _ablation_retry_pending:
		return
	_ablation_retry_pending = true
	var wait_seconds: float = maxf(0.0, delay_seconds)
	var timer: SceneTreeTimer = get_tree().create_timer(wait_seconds)
	timer.timeout.connect(_on_ablation_retry_timeout)


func _on_ablation_retry_timeout() -> void:
	_ablation_retry_pending = false
	if not _is_ablation_running():
		return
	if turn_manager.phase != TurnManager.GamePhase.PREP:
		return
	if turn_manager.prep_turn != TurnManager.PrepTurn.LLM:
		return
	_trigger_llm_turn()
