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
