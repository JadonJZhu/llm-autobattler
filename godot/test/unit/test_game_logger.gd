extends GutTest
## Covers what a logged attempt has to state for a reader to make sense of it on
## its own: the score fields a battle ended with reach the game_over entry, every
## entry names the attempt it belongs to, an attempt's prep count is checkable
## against what that attempt states, every LLM prep placement names which agent
## picked the square, and every entry names what produced the run.
##
## What a run has to do to put that last one in the log is not here. It happens
## once, at the scene start, and test_game_controller.gd drives that.
##
## Expected field names are spelled out here rather than read from GameLogger, so
## these count against what a log entry has to state and not against whatever the
## logger happens to define.

const SCORE_FIELDS: Array[String] = [
	"llm_score",
	"human_score",
	"llm_remaining",
	"human_remaining",
	"llm_escaped",
	"human_escaped",
]

const SAMPLE_SCORE: Dictionary = {
	"llm_score": 3,
	"human_score": 1,
	"llm_remaining": 2,
	"human_remaining": 0,
	"llm_escaped": 1,
	"human_escaped": 1,
}

const ABSENT: String = "<absent>"


func _mark() -> int:
	## The autoloaded logger never clears its entries, so a test reads only the
	## entries it appended itself.
	return GameLogger.get_entries().size()


func _entries_since(mark: int) -> Array:
	return GameLogger.get_entries().slice(mark)


func _last_entry() -> Dictionary:
	var entries: Array = GameLogger.get_entries()
	return entries[entries.size() - 1]


func _end_a_game(score_data: Dictionary, winner: String, prep_turns: int,
		battle_steps: int) -> void:
	## The order TurnManager._end_game uses: the replay is finalized before the
	## result is logged.
	GameLogger.record_battle_start("board")
	GameLogger.set_current_game_score_data(score_data)
	GameLogger.finalize_game_replay(winner)
	GameLogger.log_game_result(winner, -1, -1, prep_turns, battle_steps)


# =============================================================================
# A. Score fields reach the game_over entry
# =============================================================================

func test_game_over_entry_carries_the_scores_the_battle_ended_with():
	_end_a_game(SAMPLE_SCORE, "LLM", 8, 10)
	var entry: Dictionary = _last_entry()
	assert_eq(entry.get("event", ABSENT), "game_over")
	for field in SCORE_FIELDS:
		assert_eq(entry.get(field, ABSENT), SAMPLE_SCORE[field],
			"game_over entry should carry the battle's %s" % field)


func test_replay_history_carries_the_scores_the_battle_ended_with():
	_end_a_game(SAMPLE_SCORE, "LLM", 8, 10)
	var replay: Dictionary = GameLogger.get_previous_game_replay()
	for field in SCORE_FIELDS:
		assert_eq(replay.get(field, ABSENT), SAMPLE_SCORE[field],
			"replay should carry the battle's %s" % field)


func test_battle_start_clears_the_previous_battles_scores():
	## Otherwise a battle that ends without reporting a score would log the
	## previous battle's numbers as its own.
	_end_a_game(SAMPLE_SCORE, "LLM", 8, 10)
	GameLogger.record_battle_start("next board")
	GameLogger.log_game_result("Tie", -1, -1, 4, 5)
	var entry: Dictionary = _last_entry()
	for field in SCORE_FIELDS:
		assert_eq(entry.get(field, ABSENT), 0,
			"%s should be 0 for a battle that reported no score" % field)


# =============================================================================
# B. Every entry names the attempt it belongs to
# =============================================================================

func test_prep_placement_names_its_puzzle_config_and_attempt():
	GameLogger.begin_puzzle_attempt("7", "I1_E0_R1", 3, false)
	GameLogger.log_llm_prep_placement(1, "B", Vector2i(0, 2), 2, LogConstants.Chooser.MODEL)
	var entry: Dictionary = _last_entry()
	assert_eq(entry.get("play_mode", ABSENT), "puzzle")
	assert_eq(entry.get("puzzle_id", ABSENT), "7")
	assert_eq(entry.get("config", ABSENT), "I1_E0_R1")
	assert_eq(entry.get("attempt", ABSENT), 3)
	assert_eq(entry.get("unit_type", ABSENT), "B",
		"the placement itself should still be logged")


func test_attempt_start_entry_marks_the_boundary():
	var mark: int = _mark()
	GameLogger.begin_puzzle_attempt("2", "I0_E0_R0", 1, false)
	var entries: Array = _entries_since(mark)
	assert_eq(entries.size(), 1, "beginning an attempt should log one boundary entry")
	if entries.size() != 1:
		return
	assert_eq(entries[0].get("event", ABSENT), "attempt_start")
	assert_eq(entries[0].get("puzzle_id", ABSENT), "2")
	assert_eq(entries[0].get("config", ABSENT), "I0_E0_R0")
	assert_eq(entries[0].get("attempt", ABSENT), 1)


func test_battle_and_game_over_entries_name_the_attempt():
	GameLogger.begin_puzzle_attempt("5", "I1_E1_R1", 2, false)
	GameLogger.log_battle_step(1, "LLM", "unit moved")
	var battle_entry: Dictionary = _last_entry()
	_end_a_game(SAMPLE_SCORE, "LLM", 8, 10)
	var game_over_entry: Dictionary = _last_entry()
	for entry in [battle_entry, game_over_entry]:
		assert_eq(entry.get("puzzle_id", ABSENT), "5")
		assert_eq(entry.get("config", ABSENT), "I1_E1_R1")
		assert_eq(entry.get("attempt", ABSENT), 2)


func test_beginning_the_next_attempt_changes_the_identity():
	GameLogger.begin_puzzle_attempt("5", "I1_E1_R1", 1, false)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	assert_eq(_last_entry().get("attempt", ABSENT), 1)
	GameLogger.begin_puzzle_attempt("5", "I1_E1_R1", 2, false)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	assert_eq(_last_entry().get("attempt", ABSENT), 2)


func test_free_play_entries_say_so_rather_than_omitting_identity():
	GameLogger.begin_puzzle_attempt("5", "I1_E1_R1", 1, false)
	GameLogger.begin_free_play_game()
	GameLogger.log_llm_prep_placement(1, "C", Vector2i(1, 1), 1, LogConstants.Chooser.MODEL)
	var entry: Dictionary = _last_entry()
	assert_eq(entry.get("play_mode", ABSENT), "free_play")
	assert_false(entry.has("puzzle_id"),
		"a free-play entry must not claim a puzzle id")
	assert_false(entry.has("attempt"),
		"a free-play entry must not claim an attempt number")


func test_entries_name_the_stopping_rule_the_attempt_was_played_under():
	## A count of attempts means one thing when a puzzle stops at its first solve
	## and another when it plays its whole cap, so an entry that does not say
	## which cannot be counted.
	GameLogger.begin_puzzle_attempt("6", "I0_E0_R0", 2, true)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	assert_eq(_last_entry().get("play_all_attempts", ABSENT), true)
	GameLogger.begin_puzzle_attempt("6", "I0_E0_R0", 3, false)
	GameLogger.log_battle_step(1, "LLM", "unit moved")
	assert_eq(_last_entry().get("play_all_attempts", ABSENT), false)


func test_free_play_entries_claim_no_stopping_rule():
	GameLogger.begin_puzzle_attempt("6", "I0_E0_R0", 1, true)
	GameLogger.begin_free_play_game()
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	assert_false(_last_entry().has("play_all_attempts"),
		"a free-play entry belongs to no puzzle and so to no stopping rule")


func test_a_logged_entry_cannot_overwrite_its_own_identity():
	GameLogger.begin_puzzle_attempt("9", "I0_E0_R0", 4, false)
	GameLogger.log_turn(1, {"phase": "prep", "puzzle_id": "impostor", "attempt": 99})
	var entry: Dictionary = _last_entry()
	assert_eq(entry.get("puzzle_id", ABSENT), "9")
	assert_eq(entry.get("attempt", ABSENT), 4)


# =============================================================================
# C. The attempt's prep count is checkable against what the attempt states
# =============================================================================

func test_prep_entries_of_an_attempt_can_be_counted_against_its_stated_total():
	var mark: int = _mark()
	GameLogger.begin_puzzle_attempt("3", "I0_E0_R0", 1, false)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	GameLogger.log_human_prep_placement(2, "A", Vector2i(2, 0), 2)
	GameLogger.log_llm_prep_placement(3, "B", Vector2i(1, 1), 1, LogConstants.Chooser.MODEL)
	_end_a_game(SAMPLE_SCORE, "LLM", 3, 6)

	var prep_count: int = 0
	var stated_total: int = -1
	for entry in _entries_since(mark):
		if entry.get("puzzle_id", ABSENT) != "3" or entry.get("attempt", -1) != 1:
			continue
		if entry.get("phase", "") == "prep":
			prep_count += 1
		elif entry.get("event", "") == "game_over":
			stated_total = int(entry.get("total_prep_turns", -1))
	assert_eq(prep_count, 3, "all three placements should be attributed to attempt 1")
	assert_eq(stated_total, prep_count,
		"the attempt's game_over entry should state how many prep turns it had")


# =============================================================================
# D. Every LLM prep placement names the agent that picked it
# =============================================================================

func test_an_llm_placement_the_model_made_says_model():
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	assert_eq(_last_entry().get("chooser", ABSENT), "model")


func test_an_llm_placement_the_random_fallback_made_says_fallback():
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.FALLBACK)
	assert_eq(_last_entry().get("chooser", ABSENT), "fallback")


func test_a_human_placement_claims_no_chooser():
	## The opponent's squares are replayed from the puzzle rather than chosen, so
	## an entry for one must not carry a value a reader could count as an agent's.
	GameLogger.log_human_prep_placement(1, "A", Vector2i(2, 0), 2)
	assert_false(_last_entry().has("chooser"),
		"a human placement was not chosen by an agent and must say nothing")


func test_a_reader_can_split_an_attempts_llm_placements_by_chooser():
	## The measurement this exists for: what share of an attempt's placements the
	## model actually made. A reader gets that only if every LLM prep entry
	## states a chooser, so this counts the ones that do against the ones there are.
	var mark: int = _mark()
	GameLogger.begin_puzzle_attempt("3", "I0_E0_R0", 1, false)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	GameLogger.log_human_prep_placement(2, "A", Vector2i(2, 0), 2)
	GameLogger.log_llm_prep_placement(3, "B", Vector2i(0, 1), 1, LogConstants.Chooser.FALLBACK)
	GameLogger.log_llm_prep_placement(4, "C", Vector2i(1, 1), 0, LogConstants.Chooser.MODEL)

	var llm_preps: int = 0
	var by_chooser: Dictionary = {}
	for entry in _entries_since(mark):
		if entry.get("phase", "") != "prep" or entry.get("actor", "") != "llm":
			continue
		llm_preps += 1
		var stated: String = str(entry.get("chooser", ABSENT))
		by_chooser[stated] = int(by_chooser.get(stated, 0)) + 1

	assert_eq(llm_preps, 3)
	assert_eq(by_chooser.get(ABSENT, 0), 0,
		"every LLM prep entry has to state a chooser or the split is unknowable")
	assert_eq(by_chooser.get("model", 0), 2)
	assert_eq(by_chooser.get("fallback", 0), 1)


# =============================================================================
# E. Every entry names what produced the run
# =============================================================================

func _identity_of_a_client_configured_with(api_key: String, model: String) -> String:
	## What a client says produced its answers under that environment. Both
	## values are read once, when the node enters the tree, so they are set
	## before that and put back afterwards.
	var had_key: bool = OS.has_environment("LLM_API_KEY")
	var had_model: bool = OS.has_environment("LLM_API_MODEL")
	var previous_key: String = OS.get_environment("LLM_API_KEY")
	var previous_model: String = OS.get_environment("LLM_API_MODEL")

	OS.set_environment("LLM_API_KEY", api_key)
	OS.set_environment("LLM_API_MODEL", model)
	var identity: String = add_child_autofree(LlmHttpBase.new()).model_identity()

	if had_key:
		OS.set_environment("LLM_API_KEY", previous_key)
	else:
		OS.unset_environment("LLM_API_KEY")
	if had_model:
		OS.set_environment("LLM_API_MODEL", previous_model)
	else:
		OS.unset_environment("LLM_API_MODEL")
	return identity


func test_a_client_holding_a_key_names_the_model_it_sends_to():
	assert_eq(
		_identity_of_a_client_configured_with("test-key", "some-model-2026"),
		"some-model-2026",
		"a run made through this client was produced by the model it sends to"
	)


func test_a_client_holding_no_key_names_no_model_rather_than_the_default():
	## Without a key nothing is sent anywhere and every LLM placement comes from
	## the random fallback, so the model the client would otherwise have used is
	## the one thing its run must not be recorded under.
	var identity: String = _identity_of_a_client_configured_with("", "some-model-2026")
	assert_eq(identity, LlmHttpBase.NO_MODEL)
	assert_ne(identity, "some-model-2026",
		"a keyless run reached no model and must not be recorded under one")
	assert_ne(identity, LlmHttpBase.DEFAULT_API_MODEL,
		"a keyless run reached no model and must not be recorded under one")


func test_every_entry_of_a_run_names_the_model_it_recorded():
	## Per entry rather than once per file: a reader of a single entry has to be
	## able to say what made it without joining it to anything else.
	var mark: int = _mark()
	GameLogger.record_model("some-model-2026")
	GameLogger.begin_puzzle_attempt("4", "I1_E1_R1", 1, false)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	GameLogger.log_human_prep_placement(2, "A", Vector2i(2, 0), 2)
	GameLogger.log_battle_step(1, "LLM", "unit moved")
	_end_a_game(SAMPLE_SCORE, "LLM", 2, 1)
	GameLogger.begin_free_play_game()

	var entries: Array = _entries_since(mark)
	assert_eq(entries.size(), 6, "every entry the run logged is under test")
	for entry in entries:
		assert_eq(entry.get("model", ABSENT), "some-model-2026",
			"an entry that does not name the model cannot be attributed to one")


func test_a_keyless_run_records_that_no_model_was_used():
	## The state a log must never leave open: a run nothing produced has to say
	## so, because a missing field reads as a model whose name went astray.
	GameLogger.record_model(
		_identity_of_a_client_configured_with("", "some-model-2026")
	)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.FALLBACK)
	var entry: Dictionary = _last_entry()
	assert_true(entry.has("model"), "an absent model field would read as some model")
	assert_eq(entry.get("model", ABSENT), LlmHttpBase.NO_MODEL)


func test_a_run_that_named_no_model_claims_neither_a_model_nor_the_absence_of_one():
	## Nothing in the project starts a run without naming its producer, so this
	## is the state of entries logged by something that never did. It is a third
	## answer on purpose: reading it as either of the other two would be a claim
	## about a run that made none.
	GameLogger.record_model(GameLogger.MODEL_UNRECORDED)
	GameLogger.log_battle_step(1, "LLM", "unit moved")
	var stated: String = str(_last_entry().get("model", ABSENT))
	assert_eq(stated, GameLogger.MODEL_UNRECORDED)
	assert_ne(stated, LlmHttpBase.NO_MODEL,
		"a run that said nothing is not a run that said no model was used")
