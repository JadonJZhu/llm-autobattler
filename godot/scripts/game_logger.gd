extends Node
## Autoloaded singleton for logging game turns, LLM reasoning, and moves.
## Writes JSON logs to user://game_logs/.

const LOG_CONSTANTS = preload("res://scripts/log_constants.gd")
const MAX_GAME_HISTORY: int = 10

## The six numbers a battle ends with. Named once so the game_over entry and the
## replay history cannot drift apart on which fields they carry.
const _SCORE_FIELDS: Array[String] = [
	"llm_score",
	"human_score",
	"llm_remaining",
	"human_remaining",
	"llm_escaped",
	"human_escaped",
]

## The producer stamped on entries logged by a run that never named one. It reads
## as neither a model nor "no model was used", because a run that did not say
## which it was gives no ground to claim either.
const MODEL_UNRECORDED: String = "unrecorded (the run never named its model)"

## What one call's entry states in place of a usage block when the response
## carried none. A zero would read as a call that consumed nothing, which is a
## different claim from the response never having said what it consumed.
const USAGE_UNSTATED: String = "unstated (the response carried no usage block)"

## Stamped on every entry logged outside a puzzle attempt. It names the mode
## rather than leaving the identity fields off, so a free-play entry can never be
## mistaken for a puzzle placement whose identity went missing.
const _FREE_PLAY_IDENTITY: Dictionary = {"play_mode": "free_play"}

var _log_entries: Array[Dictionary] = []
var _session_id: String = ""
var _model: String = MODEL_UNRECORDED
var _attempt_identity: Dictionary = _FREE_PLAY_IDENTITY.duplicate()

## How many API calls this run recorded, and how many of those came back
## without stating what they consumed. The second is what keeps the totals
## honest: a call missing from the counts below is a bill this run cannot see,
## so a total carrying any of them is a floor rather than the whole cost.
var _api_calls: int = 0
var _api_calls_without_usage: int = 0

## What this run has consumed, in the four counts a token price is charged
## against: input at the full rate, input served from a cache at a fraction of
## that rate, input written to a cache at a premium over it, and output. The
## cached count is kept apart from the input count rather than folded into it,
## because whether caching engages at all is the open question these numbers
## have to be able to answer. Both request formats are read into these names, so
## a total does not depend on which provider produced it.
var _usage_tokens: Dictionary = {
	"uncached_input": 0,
	"cached_input": 0,
	"cache_write_input": 0,
	"output": 0,
}

var _current_battle_start_board: String = ""
var _current_battle_steps: Array[String] = []
var _previous_game_replay: Dictionary = {}
var _current_game_score_data: Dictionary = {}
var _game_history: Array[Dictionary] = []
var _reasoning_history: Array[String] = []
var _current_game_reasoning: Array[String] = []
## How many of the finalized games in _game_history a placement prompt may be
## built from. The reflection channel reads _game_history directly and is not
## bounded by this, which is what lets attempts be independent of each other's
## replays while reflection still has something to reflect on.
var _placement_lookback_games: int = 0


func _ready() -> void:
	_session_id = _generate_session_id()
	DirAccess.make_dir_recursive_absolute(LOG_CONSTANTS.LOG_DIRECTORY)


func log_turn(turn_number: int, turn_data: Dictionary) -> void:
	var entry: Dictionary = {
		"session_id": _session_id,
		"model": _model,
		"turn_number": turn_number,
		"timestamp": Time.get_datetime_string_from_system(),
	}
	# Identity first, then the caller's data. merge() leaves existing keys alone,
	# so no caller can overwrite which attempt its own entry belongs to.
	entry.merge(_attempt_identity)
	entry.merge(turn_data)
	_log_entries.append(entry)


func record_model(model_identity: String) -> void:
	## Names what produced this run's answers, on every entry that follows.
	##
	## Nothing else in the file says it. Runs were matched to the results file
	## written beside them by the two carrying the same modification time, which
	## is not a join a grid of several models can be read by and not one anything
	## reproduces. It is stamped per entry rather than once at the head of the
	## file for the reason the attempt identity is: every reader of this file
	## reads entries, and an entry that has to be joined to a record elsewhere in
	## the file to say what made it is that same positional join again. A run
	## played with no key carries LlmHttpBase.NO_MODEL, which says so outright;
	## nothing here invents a name for a run that gave none.
	_model = model_identity


func log_api_call(client_name: String, api_format: String, usage: Dictionary,
		tokens: Dictionary) -> void:
	## Records one call to the model and what it consumed.
	##
	## Usage is per call, and every other entry in this file is per placement,
	## per battle step or per game, so a call gets an entry of its own. Hanging
	## the count off the placement it produced would drop the calls that produce
	## no placement, and those are not a rounding error: every reflection call is
	## one, and so is every call whose answer could not be applied, and the
	## reflection prompt is the largest thing this project sends.
	##
	## The provider's own usage object is carried through unchanged, so a total
	## can be checked against what actually came back rather than believed.
	## `tokens` is that same object read into the four counts a price is charged
	## against, which is what the run total sums, and which is what makes a total
	## mean one thing across both request formats.
	##
	## Both are empty exactly when the response stated no usage. That call still
	## happened and still cost something, so it is counted and marked rather than
	## dropped or added in as zero: a total that quietly swallowed it would read
	## as a complete bill.
	_api_calls += 1
	var fields: Dictionary = {
		"event": "api_call",
		"client": client_name,
		"api_format": api_format,
	}
	if usage.is_empty():
		_api_calls_without_usage += 1
		fields["usage"] = USAGE_UNSTATED
	else:
		fields["usage"] = usage.duplicate(true)
		fields["tokens"] = tokens.duplicate()
		for count_name in _usage_tokens:
			_usage_tokens[count_name] = int(_usage_tokens[count_name]) + int(
				tokens.get(count_name, 0)
			)
	log_turn(0, fields)


func usage_total() -> Dictionary:
	## What this run has consumed so far, as whatever is pricing it reads it.
	##
	## It names the model because a price is per model: a token count that does
	## not say what produced it cannot be multiplied by anything. A run that held
	## no API key sent nothing, so it reads as its own model identity with zero
	## calls and four zero counts, and that is not the same artifact as one
	## carrying no total at all, which says nothing about what it spent.
	return {
		"model": _model,
		"calls": _api_calls,
		"calls_without_usage": _api_calls_without_usage,
		"tokens": _usage_tokens.duplicate(),
	}


func begin_puzzle_attempt(puzzle_id: String, config_label: String,
		attempt_number: int, plays_every_attempt: bool,
		carries_attempt_history: bool) -> void:
	## Names the puzzle attempt every following entry belongs to, and marks its
	## boundary in the log.
	##
	## One session writes one log file holding every attempt of every puzzle of
	## every config, and nothing else in that file names them. Without this the
	## only way to attribute a placement is to count game_over entries and index
	## into the separate ablation results file, which is a positional join
	## between two files and goes wrong silently the first time an attempt ends
	## without writing what the other file expects.
	##
	## The boundary entry is what makes an attempt that logged nothing else
	## visible, rather than indistinguishable from an attempt that never ran. It
	## reaches disk when the attempt's battle ends and when the run ends, so an
	## attempt a run stopped part way through is still on disk, as an attempt
	## that reached no result. A process killed by a signal writes nothing at
	## all, because nothing of this runs before it dies.
	##
	## plays_every_attempt is the stopping rule this attempt was played under,
	## and it is part of the attempt's identity rather than a detail of the run
	## because it decides what a count of attempts means. Under stop-on-solve a
	## puzzle contributes attempts until it wins, so how many it contributes is
	## decided by the outcome being measured. The ablation results file records
	## the same value, and a reader of the game log has that file neither by name
	## nor by path, so recording it in only one of them leaves the reader that
	## draws per-attempt statistics unable to say what its own rows are.
	##
	## carries_attempt_history is the other thing that decides what a count of
	## attempts means. False is one independent trial: this attempt's placement
	## prompts carry no replay of any earlier attempt of the same puzzle, so with
	## reflection off three wins out of ten is ten independent draws. With
	## reflection on they are independent in what they replay only, because
	## reflection keeps a look-back across attempts and its text reaches the
	## placement prompt. True is the regime where the attempts saw each other's
	## replays outright, under which the same three wins are one sequence the
	## agent could have learned along. It is stamped on every entry for the same
	## reason the stopping rule is: a reader of this file has no other file to
	## join against, and the two regimes produce numbers that do not mean the
	## same thing.
	if not carries_attempt_history:
		# A new independent trial. The replays stay in _game_history, because the
		# reflection channel keeps its own look-back across attempts; only the
		# window the placement prompt is built from closes here.
		_placement_lookback_games = 0
	_attempt_identity = {
		"play_mode": "puzzle",
		"puzzle_id": puzzle_id,
		"config": config_label,
		"attempt": attempt_number,
		"play_all_attempts": plays_every_attempt,
		"carry_attempt_history": carries_attempt_history,
	}
	log_turn(0, {"event": "attempt_start"})


func begin_free_play_game() -> void:
	## Marks the start of a game that belongs to no puzzle attempt, and clears any
	## identity a preceding ablation left behind. Without the clear, a free-play
	## game started after an ablation run finishes would log its placements under
	## the last attempt of the last puzzle.
	_attempt_identity = _FREE_PLAY_IDENTITY.duplicate()
	log_turn(0, {"event": "attempt_start"})


func log_llm_prep_placement(turn_number: int, unit_type: String, pos: Vector2i,
		gold_remaining: int, chooser: LOG_CONSTANTS.Chooser) -> void:
	## Records an LLM prep placement and which agent picked it.
	##
	## The chooser is required because the two agents that place for the LLM
	## side score differently: a random fallback square counted as the model's
	## makes a per-placement measurement report a blend of the two. Nothing
	## below the controller knows which route a placement came from, so this
	## takes the answer rather than guessing at it, and the enum leaves no
	## value for a caller to fall into by saying nothing.
	var fields: Dictionary = _prep_placement_fields("llm", unit_type, pos, gold_remaining)
	fields["chooser"] = LOG_CONSTANTS.CHOOSER_LABELS[chooser]
	log_turn(turn_number, fields)


func log_human_prep_placement(turn_number: int, unit_type: String, pos: Vector2i,
		gold_remaining: int) -> void:
	## Records a human-side prep placement, which carries no chooser: the square
	## comes from a person clicking or from the puzzle's scripted opponent
	## replaying a fixed queue, and neither is an agent choosing.
	log_turn(turn_number, _prep_placement_fields("human", unit_type, pos, gold_remaining))


func _prep_placement_fields(unit_owner: String, unit_type: String, pos: Vector2i,
		gold_remaining: int) -> Dictionary:
	return {
		"phase": "prep",
		"actor": unit_owner,
		"unit_type": unit_type,
		"position": {"row": pos.x, "col": pos.y},
		"gold_remaining": gold_remaining,
	}


func log_battle_step(step_number: int, active_owner: String, events: String) -> void:
	var has_escape: bool = events.find("escape") != -1
	log_turn(step_number, {
		"phase": "battle",
		"active_owner": active_owner,
		"events": events,
		"had_escape": has_escape,
	})
	_current_battle_steps.append(events)


func set_current_game_score_data(score_data: Dictionary) -> void:
	_current_game_score_data = score_data.duplicate()


func _score_fields() -> Dictionary:
	var fields: Dictionary = {}
	for field in _SCORE_FIELDS:
		fields[field] = int(_current_game_score_data.get(field, 0))
	return fields


func log_game_result(winner: String, final_score: int = -1, total_turns: int = -1,
		total_prep_turns: int = -1, total_battle_steps: int = -1) -> void:
	var entry: Dictionary = {
		"event": "game_over",
		"winner": winner,
	}
	entry.merge(_score_fields())
	if final_score >= 0:
		entry["final_score"] = final_score
	if total_turns >= 0:
		entry["total_turns"] = total_turns
	if total_prep_turns >= 0:
		entry["total_prep_turns"] = total_prep_turns
	if total_battle_steps >= 0:
		entry["total_battle_steps"] = total_battle_steps
	log_turn(max(total_turns, total_battle_steps), entry)


func record_battle_start(serialized_board: String) -> void:
	_current_battle_start_board = serialized_board
	_current_battle_steps.clear()
	# The score data belongs to the battle now beginning, so a battle start is the
	# one moment it is truthfully empty. Clearing it here rather than after the
	# game ends is what keeps finalize_game_replay and log_game_result from
	# depending on which of them the caller runs first.
	_current_game_score_data = {}


func finalize_game_replay(outcome: String) -> void:
	_previous_game_replay = {
		"start_board": _current_battle_start_board,
		"battle_steps": _current_battle_steps.duplicate(),
		"outcome": outcome,
	}
	_previous_game_replay.merge(_score_fields())

	# Append to rolling game history
	_game_history.append(_previous_game_replay.duplicate())
	if _game_history.size() > MAX_GAME_HISTORY:
		_game_history.pop_front()
	_placement_lookback_games += 1

	# Store accumulated reasoning for this game and reset
	if not _current_game_reasoning.is_empty():
		_reasoning_history.append("\n".join(_current_game_reasoning))
	_current_game_reasoning.clear()

	_current_battle_start_board = ""
	_current_battle_steps.clear()


func get_previous_game_replay() -> Dictionary:
	return _previous_game_replay


func get_game_history(count: int = -1) -> Array[Dictionary]:
	if count < 0 or count >= _game_history.size():
		return _game_history.duplicate()
	return _game_history.slice(_game_history.size() - count) as Array[Dictionary]


func get_placement_history() -> Array[Dictionary]:
	## The replays a placement prompt may be built from. What bounds this window
	## is the attempt boundary rather than a count: outside a puzzle nothing
	## closes it, so it is the whole retained history and is wider than the
	## look-back the reflection channel reads. Under independent attempts it
	## closes at every attempt start, so an attempt's first placement sees
	## nothing at all, because the attempt it follows is outside the window.
	return get_game_history(_placement_lookback_games)


func get_game_count() -> int:
	return _game_history.size()


func clear_history() -> void:
	_game_history.clear()
	_placement_lookback_games = 0
	_reasoning_history.clear()
	_current_game_reasoning.clear()
	_previous_game_replay = {}


func log_llm_reasoning(text: String) -> void:
	_current_game_reasoning.append(text)


func get_recent_reasoning(count: int = -1) -> Array[String]:
	if count < 0 or count >= _reasoning_history.size():
		return _reasoning_history.duplicate()
	return _reasoning_history.slice(_reasoning_history.size() - count) as Array[String]


func save_log() -> void:
	var file_path: String = LOG_CONSTANTS.LOG_DIRECTORY + "game_" + _session_id + ".json"
	var file := FileAccess.open(file_path, FileAccess.WRITE)
	if file == null:
		push_error("GameLogger: Failed to open log file: " + file_path)
		return
	file.store_string(JSON.stringify(_log_entries, "\t"))
	file.close()
	print("GameLogger: Saved log to " + file_path)


func get_entries() -> Array[Dictionary]:
	return _log_entries


func _generate_session_id() -> String:
	var datetime: Dictionary = Time.get_datetime_dict_from_system()
	var milliseconds: int = int(Time.get_ticks_msec() % 1000)
	return "%04d%02d%02d_%02d%02d%02d_%03d" % [
		datetime["year"], datetime["month"], datetime["day"],
		datetime["hour"], datetime["minute"], datetime["second"],
		milliseconds,
	]
