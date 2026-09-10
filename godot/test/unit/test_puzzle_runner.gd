extends GutTest
## PuzzleRunner holds the only copy of the puzzle id, config label and attempt
## number, so these cover that it puts all three into the game log on every
## attempt, not only the first. Everything is read back out of the log, because
## the log file is the only thing a later reader gets.

const ABSENT: String = "<absent>"


func _mark() -> int:
	return GameLogger.get_entries().size()


func _entries_since(mark: int) -> Array:
	return GameLogger.get_entries().slice(mark)


func _last_entry() -> Dictionary:
	var entries: Array = GameLogger.get_entries()
	return entries[entries.size() - 1]


func _make_scenario(scenario_id: String) -> PuzzleScenario:
	var scenario := PuzzleScenario.new()
	scenario.id = scenario_id
	scenario.difficulty = 2
	return scenario


func _make_runner(scenario_id: String, attempt_limit: int,
		play_every_attempt: bool = false) -> PuzzleRunner:
	var runner: PuzzleRunner = autofree(PuzzleRunner.new())
	var config := LlmModeConfig.new()
	config.instructions_enabled = true
	config.examples_enabled = false
	config.reflection_enabled = true
	runner.start_puzzle(
		_make_scenario(scenario_id), config, attempt_limit, play_every_attempt
	)
	return runner


func _collect_summary(runner: PuzzleRunner) -> Array[Dictionary]:
	## The summary is emitted once, when the puzzle ends, and is not readable off
	## the runner afterwards, so a test that asserts on it has to hold the signal.
	var summaries: Array[Dictionary] = []
	runner.puzzle_completed.connect(func(summary): summaries.append(summary))
	return summaries


func _losing_score() -> Dictionary:
	return {
		"llm_score": 0,
		"human_score": 2,
		"llm_remaining": 0,
		"human_remaining": 2,
		"llm_escaped": 0,
		"human_escaped": 0,
	}


func _winning_score() -> Dictionary:
	return {
		"llm_score": 3,
		"human_score": 0,
		"llm_remaining": 3,
		"human_remaining": 0,
		"llm_escaped": 0,
		"human_escaped": 0,
	}


func _attempt_numbers(summary: Dictionary) -> Array:
	var numbers: Array = []
	for result in summary.get("attempt_scores", []):
		numbers.append(result.get("attempt", -1))
	return numbers


func test_starting_a_puzzle_names_the_first_attempt_in_the_log():
	var mark: int = _mark()
	_make_runner("4", 3)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	var entry: Dictionary = _last_entry()
	assert_eq(entry.get("play_mode", ABSENT), "puzzle")
	assert_eq(entry.get("puzzle_id", ABSENT), "4")
	assert_eq(entry.get("config", ABSENT), "I1_E0_R1")
	assert_eq(entry.get("attempt", ABSENT), 1)
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 1, "starting a puzzle should open exactly one attempt")


func test_each_further_attempt_renames_the_log_before_it_is_played():
	var runner: PuzzleRunner = _make_runner("4", 3)
	var mark: int = _mark()
	var continued: bool = runner.record_attempt_result(
		UnitData.Owner.HUMAN, _losing_score(), 9
	)
	assert_true(continued, "a lost attempt below the limit should continue")
	assert_eq(runner.current_attempt, 2)
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 1, "continuing should open exactly one new attempt")
	if boundaries.is_empty():
		return
	assert_eq(boundaries[0].get("attempt", ABSENT), 2,
		"the log should name attempt 2 before attempt 2 places anything")
	assert_eq(boundaries[0].get("puzzle_id", ABSENT), "4")


func test_placements_logged_after_a_restart_belong_to_the_new_attempt():
	var runner: PuzzleRunner = _make_runner("4", 3)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	var first: Dictionary = _last_entry()
	runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)
	GameLogger.log_llm_prep_placement(1, "A", Vector2i(0, 0), 2, LogConstants.Chooser.MODEL)
	var second: Dictionary = _last_entry()
	assert_eq(first.get("attempt", ABSENT), 1)
	assert_eq(second.get("attempt", ABSENT), 2)
	assert_eq(first.get("puzzle_id", ABSENT), second.get("puzzle_id", "<other>"),
		"both attempts belong to the same puzzle")


func test_a_finished_puzzle_does_not_open_a_further_attempt():
	var runner: PuzzleRunner = _make_runner("4", 1)
	var mark: int = _mark()
	var continued: bool = runner.record_attempt_result(
		UnitData.Owner.HUMAN, _losing_score(), 9
	)
	assert_false(continued, "the attempt limit should end the puzzle")
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 0, "no attempt 2 should be opened in the log")


# --- Fixed attempts: every attempt is played whatever its outcome ---


func test_the_default_stops_at_the_first_solve():
	var runner: PuzzleRunner = _make_runner("4", 3)
	var summaries: Array[Dictionary] = _collect_summary(runner)
	var mark: int = _mark()
	var continued: bool = runner.record_attempt_result(
		UnitData.Owner.LLM, _winning_score(), 6
	)
	assert_false(continued, "a solve should end the puzzle by default")
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 0, "no attempt 2 should be opened in the log")
	assert_eq(summaries.size(), 1)
	if summaries.is_empty():
		return
	assert_eq(_attempt_numbers(summaries[0]), [1],
		"a puzzle solved on attempt 1 should record only attempt 1")


func test_the_log_says_which_stopping_rule_each_attempt_was_played_under():
	## The results file records this and the game log is read without it, so an
	## attempt that does not carry the rule cannot say what a count of attempts
	## across puzzles means.
	var mark: int = _mark()
	_make_runner("4", 3)
	_make_runner("5", 3, true)
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 2)
	if boundaries.size() != 2:
		return
	assert_eq(boundaries[0].get("play_all_attempts", ABSENT), false,
		"a puzzle that stops at its first solve should say so")
	assert_eq(boundaries[1].get("play_all_attempts", ABSENT), true,
		"a puzzle that plays its whole cap should say so")


func test_a_further_attempt_carries_the_same_stopping_rule():
	var runner: PuzzleRunner = _make_runner("4", 3, true)
	var mark: int = _mark()
	runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 6)
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 1)
	if boundaries.is_empty():
		return
	assert_eq(boundaries[0].get("play_all_attempts", ABSENT), true)


func test_a_fixed_attempts_run_plays_on_after_a_solve():
	var runner: PuzzleRunner = _make_runner("4", 3, true)
	var mark: int = _mark()
	var continued: bool = runner.record_attempt_result(
		UnitData.Owner.LLM, _winning_score(), 6
	)
	assert_true(continued, "a solve below the cap should not end a fixed-attempts run")
	assert_eq(runner.current_attempt, 2)
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 1, "continuing should open exactly one new attempt")
	if boundaries.is_empty():
		return
	assert_eq(boundaries[0].get("attempt", ABSENT), 2)
	assert_eq(boundaries[0].get("puzzle_id", ABSENT), "4")


func test_a_fixed_attempts_run_records_every_attempt_of_its_cap():
	var runner: PuzzleRunner = _make_runner("4", 3, true)
	var summaries: Array[Dictionary] = _collect_summary(runner)
	var mark: int = _mark()
	assert_true(runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 6))
	assert_true(runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9))
	assert_false(runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 7),
		"the cap should end the puzzle even though the last attempt solved it")
	var boundaries: Array = _entries_since(mark).filter(
		func(e): return e.get("event", "") == "attempt_start"
	)
	assert_eq(boundaries.size(), 2, "attempts 2 and 3 should each be named in the log")
	assert_eq(summaries.size(), 1)
	if summaries.is_empty():
		return
	assert_eq(_attempt_numbers(summaries[0]), [1, 2, 3],
		"all three attempts should reach the results file, in order")


func test_a_fixed_attempts_summary_counts_the_first_solve():
	var runner: PuzzleRunner = _make_runner("4", 3, true)
	var summaries: Array[Dictionary] = _collect_summary(runner)
	runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)
	runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 6)
	runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)
	assert_eq(summaries.size(), 1)
	if summaries.is_empty():
		return
	assert_true(bool(summaries[0].get("solved", false)),
		"a puzzle solved on attempt 2 is solved, whatever attempt 3 did")
	assert_eq(summaries[0].get("attempts_needed", ABSENT), 2)
	assert_eq(_attempt_numbers(summaries[0]), [1, 2, 3])


func test_the_default_summary_is_what_it_was_for_a_late_solve():
	var runner: PuzzleRunner = _make_runner("4", 3)
	var summaries: Array[Dictionary] = _collect_summary(runner)
	runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)
	runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 6)
	assert_eq(summaries.size(), 1)
	if summaries.is_empty():
		return
	assert_true(bool(summaries[0].get("solved", false)))
	assert_eq(summaries[0].get("attempts_needed", ABSENT), 2)
	assert_eq(summaries[0].get("max_attempts", ABSENT), 3)
	assert_eq(summaries[0].get("puzzle_id", ABSENT), "4")
	assert_eq(summaries[0].get("config", ABSENT), "I1_E0_R1")
	assert_eq(summaries[0].get("difficulty", ABSENT), 2)
	assert_eq(_attempt_numbers(summaries[0]), [1, 2])


func test_the_default_summary_is_what_it_was_when_the_cap_runs_out():
	var runner: PuzzleRunner = _make_runner("4", 2)
	var summaries: Array[Dictionary] = _collect_summary(runner)
	runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)
	runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)
	assert_eq(summaries.size(), 1)
	if summaries.is_empty():
		return
	assert_false(bool(summaries[0].get("solved", true)))
	assert_eq(summaries[0].get("attempts_needed", ABSENT), 2,
		"an unsolved puzzle still reports the cap as attempts needed")
	assert_eq(_attempt_numbers(summaries[0]), [1, 2])


func test_an_attempt_record_has_the_same_shape_in_both_modes():
	## The log and the results file are read per attempt, so a mode that changed
	## which fields an attempt carries would be a different measurement, not the
	## same one taken more often.
	var default_runner: PuzzleRunner = _make_runner("4", 2)
	var default_summaries: Array[Dictionary] = _collect_summary(default_runner)
	default_runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 6)

	var fixed_runner: PuzzleRunner = _make_runner("4", 2, true)
	var fixed_summaries: Array[Dictionary] = _collect_summary(fixed_runner)
	fixed_runner.record_attempt_result(UnitData.Owner.LLM, _winning_score(), 6)
	fixed_runner.record_attempt_result(UnitData.Owner.HUMAN, _losing_score(), 9)

	assert_eq(default_summaries.size(), 1)
	assert_eq(fixed_summaries.size(), 1)
	if default_summaries.is_empty() or fixed_summaries.is_empty():
		return
	var default_keys: Array = default_summaries[0]["attempt_scores"][0].keys()
	default_keys.sort()
	for result in fixed_summaries[0]["attempt_scores"]:
		var fixed_keys: Array = result.keys()
		fixed_keys.sort()
		assert_eq(fixed_keys, default_keys,
			"every fixed-attempts record should carry the fields today's record carries")
	assert_eq(default_summaries[0].keys(), fixed_summaries[0].keys(),
		"both modes should emit the same summary fields")
