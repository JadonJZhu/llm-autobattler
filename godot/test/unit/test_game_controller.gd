extends GutTest
## GameController is the only place that knows which agent picked a square:
## TurnManager is handed the answer and LlmFallback is never asked. So the
## routing between the controller's two placement paths is the whole of what
## makes a per-placement measurement a measurement of the model, and these drive
## the real scene and read the chooser back out of the log rather than off the
## argument the controller passed.
##
## The scene is instantiated with no API key loaded, which is the state every
## fallback path here needs and is also how the random-agent baseline runs.
##
## The scene start is also where the log is told what produced the run, and it is
## the only place that happens, so that is driven here too.

const SCENE := preload("res://scenes/game_board.tscn")
const ABSENT: String = "<absent>"

## Left in the logger before the scene starts. It is not a value any run writes,
## so an entry carrying it is an entry the run never named a producer for.
const NEVER_WRITTEN_BY_A_RUN: String = "<no run recorded this>"

var _controller
var _entries_before_the_run: int


func before_each():
	GameLogger.record_model(NEVER_WRITTEN_BY_A_RUN)
	_entries_before_the_run = GameLogger.get_entries().size()
	_controller = add_child_autofree(SCENE.instantiate())


func _llm_prep_entries() -> Array:
	var found: Array = []
	for entry in GameLogger.get_entries():
		if entry.get("phase", "") == "prep" and entry.get("actor", "") == "llm":
			found.append(entry)
	return found


func _last_llm_prep() -> Dictionary:
	var entries: Array = _llm_prep_entries()
	return entries[entries.size() - 1] if not entries.is_empty() else {}


func _hand_the_turn_back_to_the_llm() -> void:
	## A placement ends the LLM's prep turn, so a test making a second one has to
	## put the turn back rather than depend on what the first one left.
	_controller.turn_manager.phase = TurnManager.GamePhase.PREP
	_controller.turn_manager.prep_turn = TurnManager.PrepTurn.LLM


func _an_affordable_llm_type() -> UnitData.UnitType:
	for type in _controller._llm_shop.available_types:
		if _controller._llm_shop.can_afford(type):
			return type
	fail_test("the LLM shop should still afford something")
	return UnitData.UnitType.A


func _an_occupied_square() -> Vector2i:
	var taken: Array = _controller.game_board.get_snapshot().keys()
	assert_false(taken.is_empty(), "the keyless start should have placed a unit")
	return taken[0]


func test_the_first_placement_of_a_keyless_game_is_logged_as_the_fallbacks():
	## With no API key the controller never asks the model at all, so every
	## placement in such a run is the random baseline's. This is the run that
	## produces the no-model logs the oracle reports as 0% model.
	assert_false(LlmClient.has_api_key(),
		"this suite needs a keyless client or it is testing the wrong path")
	assert_eq(_last_llm_prep().get("chooser", ABSENT), "fallback")


func test_an_answer_from_the_model_is_logged_as_the_models():
	_hand_the_turn_back_to_the_llm()
	var empty: Array[Vector2i] = _controller.game_board.get_empty_positions_for(
		UnitData.Owner.LLM
	)
	var before: int = _llm_prep_entries().size()

	_controller._on_llm_prep_response_received(_an_affordable_llm_type(), empty[0])

	assert_eq(_llm_prep_entries().size(), before + 1, "the answer should have been placed")
	assert_eq(_last_llm_prep().get("chooser", ABSENT), "model")


func test_an_answer_the_game_cannot_apply_is_logged_as_the_fallbacks():
	## The fault this field exists for. The model answers, the answer names a
	## square already holding a unit, TurnManager refuses it and the controller
	## places a random square instead. What reaches the log is the fallback's
	## placement, and logging it as the model's is what charges a coin's regret
	## to the model.
	_hand_the_turn_back_to_the_llm()
	var occupied: Vector2i = _an_occupied_square()
	var before: int = _llm_prep_entries().size()

	_controller._on_llm_prep_response_received(_an_affordable_llm_type(), occupied)

	assert_eq(_llm_prep_entries().size(), before + 1,
		"the fallback should have placed once for the answer that failed")
	var entry: Dictionary = _last_llm_prep()
	assert_eq(entry.get("chooser", ABSENT), "fallback")
	assert_ne(
		Vector2i(int(entry["position"]["row"]), int(entry["position"]["col"])),
		occupied,
		"the square the model named was refused, so the log must not state it"
	)
	assert_push_error("TurnManager: Cell already occupied at %s" % str(occupied))


func test_a_placement_made_after_a_request_failed_is_logged_as_the_fallbacks():
	## The other route into the fallback: the request never produced an answer at
	## all, so nothing here is the model's.
	_hand_the_turn_back_to_the_llm()
	var before: int = _llm_prep_entries().size()

	_controller._on_llm_request_failed("Failed to parse PLACE command.", false, {})

	assert_eq(_llm_prep_entries().size(), before + 1)
	assert_eq(_last_llm_prep().get("chooser", ABSENT), "fallback")
	assert_push_error("LLM request failed: Failed to parse PLACE command.")


func test_the_run_the_scene_starts_names_what_produced_it_in_the_log():
	## Nothing under the scene puts the producer in the log: the client is asked
	## and the logger is told once, at the scene start, and every entry after
	## that carries the answer. So this is what fails if the two are never
	## connected, and the entries are read out of the log rather than off the
	## value the controller passed.
	##
	## This suite runs keyless, so what the run has to record is that no model
	## was used. A keyless run is exactly the one that must not be recorded under
	## a model name, since every LLM placement in it came from the fallback.
	assert_false(LlmClient.has_api_key(),
		"this suite needs a keyless client or it is testing the wrong path")

	var entries: Array = GameLogger.get_entries().slice(_entries_before_the_run)
	assert_false(entries.is_empty(), "the scene start should have logged its opening game")
	var producers: Dictionary = {}
	for entry in entries:
		producers[entry.get("model", ABSENT)] = true
	assert_eq(producers.keys(), [LlmHttpBase.NO_MODEL],
		"every entry a real run logged has to name that run's producer, and this run had none")


# =============================================================================
# A later attempt is asked from an empty window
# =============================================================================
#
# Wins out of N is N independent draws only if the prompt attempt k+1 answers
# carries nothing of attempt k. The controller settles that in exactly one
# place, by choosing which of the logger's two windows it hands the client, so
# these drive that choice through the real client rather than reading back the
# window function the test would have picked itself.
#
# The chain is the real one: a battle ends, the runner opens the next attempt,
# the controller restarts into it and asks for a placement. The client is given
# a key, so it takes the model path instead of the fallback, and a request node
# that is left outside the scene tree, so every send is refused before a socket
# is opened. Nothing leaves this machine and no API is reached. Each refusal
# raises an error, and the tests account for those rather than leave them to
# fail on something that is not about the prompt.

const NOT_A_KEY: String = "no request built with this key is ever sent"
const ATTEMPT_ONE_BOARD: String = "ATTEMPT-ONE-BOARD-MARKER"
const REFUSED_SEND: String = "ERR_UNCONFIGURED"
const REFUSED_SEND_REPORTED: String = "HTTPRequest.request() failed"


class CapturingPromptBuilder:
	extends LlmPromptBuilder
	## Records the replay window behind every placement prompt it is asked for.
	var windows: Array[Array] = []

	func build_user_message(board: GameBoard, llm_shop: Shop, enemy_shop: Shop,
			turn_number: int, game_history: Array[Dictionary],
			config: LlmModeConfig) -> String:
		windows.append(game_history.duplicate())
		return super.build_user_message(
			board, llm_shop, enemy_shop, turn_number, game_history, config
		)


var _builder: CapturingPromptBuilder
var _real_http_request: HTTPRequest
var _client_was_borrowed: bool = false


func after_each():
	if not _client_was_borrowed:
		return
	LlmClient._api_key = ""
	LlmClient._is_requesting = false
	LlmClient._http_request = _real_http_request
	LlmClient.set_prompt_builder(LlmPromptBuilder.new())
	_client_was_borrowed = false


func _make_the_client_build_prompts_it_cannot_send() -> void:
	_builder = CapturingPromptBuilder.new()
	LlmClient.set_prompt_builder(_builder)
	LlmClient._api_key = NOT_A_KEY
	_real_http_request = LlmClient._http_request
	LlmClient._http_request = autofree(HTTPRequest.new())
	_client_was_borrowed = true


func _account_for_the_refused_sends() -> void:
	## Every error one of these tests raises is a send the unparented request
	## node refused, plus the controller reporting it. They are the price of
	## driving the model path offline and they say nothing about the prompt, so
	## they are accounted for here and anything else still fails the test.
	var errors: Array = get_errors()
	assert_false(errors.is_empty(), "the client should have tried to send")
	for err in errors:
		if err.contains_text(REFUSED_SEND) or err.contains_text(REFUSED_SEND_REPORTED):
			err.handled = true
		else:
			fail_test("an error that is not a refused send: %s" % err.to_s())


func _lose_attempt_one_of_a_puzzle(carry_attempt_history: bool) -> int:
	## Plays a three-attempt puzzle as far as losing attempt 1, which leaves the
	## controller opened into attempt 2 and already asked for its first
	## placement. Returns the index in the builder's windows at which attempt 2's
	## prompts begin.
	var config := LlmModeConfig.new()
	config.instructions_enabled = false
	config.examples_enabled = false
	config.reflection_enabled = false
	var scenario := PuzzleScenario.new()
	scenario.id = "independence"
	scenario.difficulty = 1
	scenario.llm_shop_types = [UnitData.UnitType.A, UnitData.UnitType.B]
	scenario.opponent_shop_types = [UnitData.UnitType.A, UnitData.UnitType.B]

	_controller._mode_config = config
	LlmClient.set_mode_config(config)
	_controller._puzzle_mode_enabled = true
	_controller._active_puzzle_scenario = scenario
	GameLogger.clear_history()
	_controller._puzzle_runner.start_puzzle(scenario, config, 3, true, carry_attempt_history)

	var windows_before_attempt_two: int = _builder.windows.size()
	GameLogger.record_battle_start(ATTEMPT_ONE_BOARD)
	_controller.turn_manager._end_game({
		"is_finished": true,
		"winner": UnitData.Owner.HUMAN,
		"llm_score": 0,
		"human_score": 3,
		"llm_remaining": 0,
		"human_remaining": 2,
		"llm_escaped": 0,
		"human_escaped": 0,
	})
	return windows_before_attempt_two


func test_a_later_independent_attempt_is_asked_from_an_empty_window():
	_make_the_client_build_prompts_it_cannot_send()

	var first: int = _lose_attempt_one_of_a_puzzle(false)
	_account_for_the_refused_sends()

	assert_eq(_controller._puzzle_runner.current_attempt, 2,
		"the lost attempt should have opened attempt 2")
	assert_gt(_builder.windows.size(), first,
		"attempt 2 should have asked the model for a placement")
	if _builder.windows.size() <= first:
		return
	assert_eq(_builder.windows[first].size(), 0,
		"attempt 2's placement must be built from a window holding no earlier attempt")


func test_a_later_carrying_attempt_is_asked_from_the_earlier_attempts_replay():
	## The counterpart, and what stops the assertion above from passing on a
	## window that comes back empty whatever the regime. This is the regime the
	## published attempt counts were measured under.
	_make_the_client_build_prompts_it_cannot_send()

	var first: int = _lose_attempt_one_of_a_puzzle(true)
	_account_for_the_refused_sends()

	assert_gt(_builder.windows.size(), first,
		"attempt 2 should have asked the model for a placement")
	if _builder.windows.size() <= first:
		return
	assert_eq(_builder.windows[first].size(), 1,
		"the carry-history regime must still show attempt 2 what attempt 1 played")
	if _builder.windows[first].is_empty():
		return
	assert_eq(str(_builder.windows[first][0].get("start_board", "")), ATTEMPT_ONE_BOARD)
