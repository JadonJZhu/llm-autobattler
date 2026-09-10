extends GutTest
## TurnManager sits between the controller that knows which agent picked a
## square and the log a reader gets. These drive real placements through it and
## read the result back out of the log, so they count against what the log
## states rather than against what TurnManager was handed.

const ABSENT: String = "<absent>"

var _board: GameBoard
var _turn_manager: TurnManager
var _llm_shop: Shop
var _human_shop: Shop


func before_each():
	_board = add_child_autofree(GameBoard.new())
	_board.initialize()
	_llm_shop = _make_shop()
	_human_shop = _make_shop()
	_turn_manager = add_child_autofree(TurnManager.new())
	_turn_manager.initialize(_board, _llm_shop, _human_shop)


func _make_shop() -> Shop:
	var shop := Shop.new()
	shop.available_types.assign([
		UnitData.UnitType.A, UnitData.UnitType.B, UnitData.UnitType.C
	])
	shop.gold = 3
	return shop


func _last_entry() -> Dictionary:
	var entries: Array = GameLogger.get_entries()
	return entries[entries.size() - 1]


func _place_for_llm(type: UnitData.UnitType, pos: Vector2i,
		chooser: LogConstants.Chooser) -> Dictionary:
	## Placements alternate sides, so a test placing twice for the LLM hands the
	## turn back first rather than depending on what the previous one left.
	_turn_manager.prep_turn = TurnManager.PrepTurn.LLM
	assert_true(_turn_manager.apply_llm_prep_placement(type, pos, chooser),
		"the placement under test should have been applied")
	return _last_entry()


func test_a_placement_the_model_made_reaches_the_log_as_model():
	var entry: Dictionary = _place_for_llm(
		UnitData.UnitType.A, Vector2i(0, 0), LogConstants.Chooser.MODEL
	)
	assert_eq(entry.get("actor", ABSENT), "llm")
	assert_eq(entry.get("chooser", ABSENT), "model")


func test_a_placement_the_random_fallback_made_reaches_the_log_as_fallback():
	var entry: Dictionary = _place_for_llm(
		UnitData.UnitType.A, Vector2i(0, 0), LogConstants.Chooser.FALLBACK
	)
	assert_eq(entry.get("actor", ABSENT), "llm")
	assert_eq(entry.get("chooser", ABSENT), "fallback")


func test_the_two_choosers_are_not_confused_within_one_game():
	var model_entry: Dictionary = _place_for_llm(
		UnitData.UnitType.A, Vector2i(0, 0), LogConstants.Chooser.MODEL
	)
	var fallback_entry: Dictionary = _place_for_llm(
		UnitData.UnitType.B, Vector2i(0, 1), LogConstants.Chooser.FALLBACK
	)
	assert_eq(model_entry.get("chooser", ABSENT), "model")
	assert_eq(fallback_entry.get("chooser", ABSENT), "fallback")


func test_the_scripted_opponents_placement_claims_no_chooser():
	_turn_manager.prep_turn = TurnManager.PrepTurn.HUMAN
	assert_true(_turn_manager.apply_human_prep_placement(
		UnitData.UnitType.A, Vector2i(2, 0)
	))
	var entry: Dictionary = _last_entry()
	assert_eq(entry.get("actor", ABSENT), "human")
	assert_false(entry.has("chooser"),
		"the opponent's square was not chosen by an agent and must say nothing")
