extends GutTest
## What a run has to record for its own artifacts to say what it cost.
##
## The count exists in one place and for one moment: the usage block of the
## response. So these drive real clients through a real response and read what
## reached the record, rather than checking that a function returns what it was
## handed.
##
## Field names and the four counts are spelled out here rather than read off
## GameLogger, so these count against what a record has to state and not against
## whatever the logger happens to define.

const ABSENT: String = "<absent>"

## The four counts a token price is charged against.
const TOKEN_FIELDS: Array[String] = [
	"uncached_input",
	"cached_input",
	"cache_write_input",
	"output",
]

## A response in each format, with a usage block as that provider states it.
## Every number differs from every other so that a count read out of the wrong
## field cannot pass, and each carries a field nothing here maps, which has to
## survive into the record anyway.
##
## The counts are written as floats because that is what the record holds: Godot
## parses every JSON number into a float, so a count that left the provider as an
## integer arrives as one of these.
const ANTHROPIC_USAGE: Dictionary = {
	"input_tokens": 1200.0,
	"output_tokens": 340.0,
	"cache_creation_input_tokens": 2048.0,
	"cache_read_input_tokens": 9000.0,
	"service_tier": "standard",
}

const OPENAI_USAGE: Dictionary = {
	"prompt_tokens": 1200.0,
	"completion_tokens": 340.0,
	"total_tokens": 1540.0,
	"prompt_tokens_details": {
		"cached_tokens": 1024.0,
		"cache_write_tokens": 100.0,
		"audio_tokens": 0.0,
	},
}


class _FakeClient extends LlmHttpBase:
	## Keeps the whole of the base's response handling and drops the answer:
	## what is under test is what a call records about itself, not what a
	## subclass does with the text that came back.
	func _on_api_response_parsed(_response_text: String) -> void:
		pass

	func _get_client_name() -> String:
		return "TestClient"


func _client_speaking(api_format: String):
	## A client configured for one request format, with no API key. Both are read
	## once, when the node enters the tree, so they are set before that and put
	## back afterwards. The key is forced empty rather than assumed absent: a
	## client holding one would send these responses' requests to a real endpoint.
	var had_format: bool = OS.has_environment("LLM_API_FORMAT")
	var had_key: bool = OS.has_environment("LLM_API_KEY")
	var previous_format: String = OS.get_environment("LLM_API_FORMAT")
	var previous_key: String = OS.get_environment("LLM_API_KEY")

	OS.set_environment("LLM_API_FORMAT", api_format)
	OS.set_environment("LLM_API_KEY", "")
	var client = add_child_autofree(_FakeClient.new())

	if had_format:
		OS.set_environment("LLM_API_FORMAT", previous_format)
	else:
		OS.unset_environment("LLM_API_FORMAT")
	if had_key:
		OS.set_environment("LLM_API_KEY", previous_key)
	else:
		OS.unset_environment("LLM_API_KEY")
	assert_push_warning("No API key found",
		"the client has to say it holds no key, or these responses went somewhere real")
	return client


func _deliver(client, response: Dictionary) -> void:
	## The response the provider sent, arriving the way one really arrives.
	client._on_request_completed(
		HTTPRequest.RESULT_SUCCESS,
		200,
		PackedStringArray(),
		JSON.stringify(response).to_utf8_buffer()
	)


func _mark() -> int:
	## The autoloaded logger never clears its entries, so a test reads only the
	## entries it caused itself.
	return GameLogger.get_entries().size()


func _calls_since(mark: int) -> Array:
	var found: Array = []
	for entry in GameLogger.get_entries().slice(mark):
		if entry.get("event", "") == "api_call":
			found.append(entry)
	return found


func _one_call_since(mark: int) -> Dictionary:
	var found: Array = _calls_since(mark)
	assert_eq(found.size(), 1, "one response is one recorded call")
	return found[0] if found.size() == 1 else {}


func _totals() -> Dictionary:
	return GameLogger.usage_total().get("tokens", {})


# =============================================================================
# A. A response that states its usage is recorded whole, in both formats
# =============================================================================

func test_an_anthropic_call_records_its_usage_block_field_for_field():
	var mark: int = _mark()
	_deliver(_client_speaking("anthropic"), {"usage": ANTHROPIC_USAGE, "content": []})

	var entry: Dictionary = _one_call_since(mark)
	assert_eq(entry.get("client", ABSENT), "TestClient",
		"a total that cannot be split by caller cannot separate reflection from placement")
	assert_eq(entry.get("api_format", ABSENT), "anthropic",
		"the recorded usage field names mean nothing without the format that named them")

	var recorded: Dictionary = entry.get("usage", {})
	for field in ANTHROPIC_USAGE:
		assert_eq(recorded.get(field, ABSENT), ANTHROPIC_USAGE[field],
			"the response stated %s and the record has to keep it" % field)
	assert_eq(recorded.size(), ANTHROPIC_USAGE.size(),
		"the usage block is kept whole, including the fields nothing here reads")


func test_an_anthropic_call_reads_its_usage_into_the_counts_a_price_is_charged_against():
	var mark: int = _mark()
	_deliver(_client_speaking("anthropic"), {"usage": ANTHROPIC_USAGE, "content": []})

	var counts: Dictionary = _one_call_since(mark).get("tokens", {})
	assert_eq(counts.get("uncached_input", ABSENT), 1200)
	assert_eq(counts.get("cached_input", ABSENT), 9000)
	assert_eq(counts.get("cache_write_input", ABSENT), 2048)
	assert_eq(counts.get("output", ABSENT), 340)


func test_an_openai_call_records_its_usage_block_field_for_field():
	var mark: int = _mark()
	_deliver(_client_speaking("openai"), {"usage": OPENAI_USAGE, "choices": []})

	var entry: Dictionary = _one_call_since(mark)
	assert_eq(entry.get("api_format", ABSENT), "openai")

	var recorded: Dictionary = entry.get("usage", {})
	assert_eq(recorded.get("prompt_tokens", ABSENT), 1200.0)
	assert_eq(recorded.get("completion_tokens", ABSENT), 340.0)
	assert_eq(recorded.get("total_tokens", ABSENT), 1540.0)
	assert_eq(recorded.size(), OPENAI_USAGE.size(),
		"the usage block is kept whole")

	var details: Dictionary = recorded.get("prompt_tokens_details", {})
	for field in OPENAI_USAGE["prompt_tokens_details"]:
		assert_eq(details.get(field, ABSENT), OPENAI_USAGE["prompt_tokens_details"][field],
			"the nested breakdown states %s and the record has to keep it" % field)


func test_an_openai_call_takes_both_cache_counts_out_of_the_prompt_they_sat_in():
	## The one place the two formats genuinely disagree. openai's prompt_tokens
	## already contains both the tokens read from a cache and the tokens written
	## to one; anthropic states its two cache counts alongside input_tokens
	## instead. Every token left in uncached_input is charged at the full rate
	## and both cache counts are charged again at their own rates, so a token
	## left in that never came out of it is a token billed twice.
	var mark: int = _mark()
	_deliver(_client_speaking("openai"), {"usage": OPENAI_USAGE, "choices": []})

	var counts: Dictionary = _one_call_since(mark).get("tokens", {})
	assert_eq(counts.get("uncached_input", ABSENT), 76,
		"the full rate is charged on the prompt less what was read from and written to cache")
	assert_ne(counts.get("uncached_input", ABSENT), 1200,
		"the whole prompt count includes tokens that were served from a cache")
	assert_ne(counts.get("uncached_input", ABSENT), 176,
		"taking only the read part out bills the written part at the full rate and again as a write")
	assert_eq(counts.get("cached_input", ABSENT), 1024,
		"the cached count is its own field, which is how a run answers whether caching engaged")
	assert_eq(counts.get("cache_write_input", ABSENT), 100)
	assert_eq(counts.get("output", ABSENT), 340)


# =============================================================================
# B. A response that states no usage is recorded as unstated, never as zero
# =============================================================================

func test_a_response_with_no_usage_block_is_recorded_as_unstated():
	var mark: int = _mark()
	var totals_before: Dictionary = _totals()
	var calls_before: int = int(GameLogger.usage_total().get("calls", 0))
	_deliver(_client_speaking("anthropic"), {"content": []})

	var entry: Dictionary = _one_call_since(mark)
	assert_eq(entry.get("usage", ABSENT), GameLogger.USAGE_UNSTATED,
		"a response that said nothing about what it cost has to say so")
	assert_false(entry.has("tokens"),
		"four zeroes would read as a call that consumed nothing")

	var total: Dictionary = GameLogger.usage_total()
	assert_eq(int(total.get("calls", 0)), calls_before + 1,
		"the call happened and was paid for whatever the response omitted")
	for field in TOKEN_FIELDS:
		assert_eq(int(_totals().get(field, -1)), int(totals_before.get(field, -1)),
			"nothing was stated, so nothing may be added to %s" % field)


func test_a_call_that_stated_no_usage_is_counted_where_a_total_can_see_it():
	## Otherwise the total reads as the whole bill while a call is missing from it.
	var without_before: int = int(GameLogger.usage_total().get("calls_without_usage", 0))
	_deliver(_client_speaking("anthropic"), {"content": []})
	assert_eq(int(GameLogger.usage_total().get("calls_without_usage", 0)), without_before + 1)

	_deliver(_client_speaking("anthropic"), {"usage": ANTHROPIC_USAGE, "content": []})
	assert_eq(int(GameLogger.usage_total().get("calls_without_usage", 0)), without_before + 1,
		"a call that stated its usage is not one of the calls that did not")


# =============================================================================
# C. The run total is the calls, added up
# =============================================================================

func test_the_run_total_adds_up_the_calls_it_recorded():
	var before: Dictionary = _totals().duplicate()
	var calls_before: int = int(GameLogger.usage_total().get("calls", 0))
	var client = _client_speaking("anthropic")
	_deliver(client, {"usage": ANTHROPIC_USAGE, "content": []})
	_deliver(client, {"usage": ANTHROPIC_USAGE, "content": []})

	var after: Dictionary = _totals()
	assert_eq(int(GameLogger.usage_total().get("calls", 0)), calls_before + 2)
	assert_eq(int(after.get("uncached_input", 0)) - int(before.get("uncached_input", 0)), 2400)
	assert_eq(int(after.get("cached_input", 0)) - int(before.get("cached_input", 0)), 18000)
	assert_eq(int(after.get("cache_write_input", 0)) - int(before.get("cache_write_input", 0)), 4096)
	assert_eq(int(after.get("output", 0)) - int(before.get("output", 0)), 680)


func test_a_call_states_the_same_counts_the_total_carries():
	## The total is a sum of these, so a count named differently in the two
	## places is a count that silently never reaches the sum.
	var mark: int = _mark()
	_deliver(_client_speaking("anthropic"), {"usage": ANTHROPIC_USAGE, "content": []})

	var counts: Dictionary = _one_call_since(mark).get("tokens", {})
	var totals: Dictionary = _totals()
	for field in TOKEN_FIELDS:
		assert_true(counts.has(field), "a call has to state %s" % field)
		assert_true(totals.has(field), "the total has to carry %s" % field)
	assert_eq(counts.size(), TOKEN_FIELDS.size())
	assert_eq(totals.size(), TOKEN_FIELDS.size())


# =============================================================================
# D. A run that sent nothing says so, and does not read as a run that measured
#    nothing
# =============================================================================

func test_a_run_that_recorded_no_call_states_zero_rather_than_nothing():
	## The random arm. It holds no key, sends nothing and costs nothing, and the
	## thing it must not look like is a run of a model that happened to be free
	## or a run that never counted. A fresh logger is the state such a run's
	## record is in, because the autoloaded one carries this whole suite's calls.
	var logger = add_child_autofree(preload("res://scripts/game_logger.gd").new())
	logger.record_model(LlmHttpBase.NO_MODEL)

	var total: Dictionary = logger.usage_total()
	assert_eq(total.get("calls", ABSENT), 0, "no key means no call was ever sent")
	assert_eq(total.get("calls_without_usage", ABSENT), 0)
	assert_eq(total.get("model", ABSENT), LlmHttpBase.NO_MODEL,
		"the arm that spent nothing has to name itself, or its zero reads as a free model")
	assert_ne(total.get("model", ABSENT), GameLogger.MODEL_UNRECORDED)

	var counts: Dictionary = total.get("tokens", {})
	for field in TOKEN_FIELDS:
		assert_eq(counts.get(field, ABSENT), 0,
			"%s is zero and stated, not absent" % field)


func test_a_client_holding_no_key_records_no_call_at_all():
	## Zero is what the counts say because nothing was sent, not because
	## something was sent and came back empty.
	var mark: int = _mark()
	var calls_before: int = int(GameLogger.usage_total().get("calls", 0))

	var had_key: bool = OS.has_environment("LLM_API_KEY")
	var previous_key: String = OS.get_environment("LLM_API_KEY")
	OS.set_environment("LLM_API_KEY", "")
	var client = add_child_autofree(ReflectionClient.new())
	if had_key:
		OS.set_environment("LLM_API_KEY", previous_key)
	else:
		OS.unset_environment("LLM_API_KEY")
	assert_push_warning("No API key found",
		"a run that sent nothing has to be a run that could not send")

	var history: Array[Dictionary] = [{"outcome": "LLM", "start_board": "board"}]
	var reasoning: Array[String] = []
	client.request_reflection(history, reasoning)

	assert_eq(_calls_since(mark).size(), 0, "a keyless client sends nothing to record")
	assert_eq(int(GameLogger.usage_total().get("calls", 0)), calls_before)


# =============================================================================
# E. The results file states what the run spent
# =============================================================================

func test_the_results_file_states_the_run_total_beside_the_results():
	## A costing reads this file. Reading the total off the game log instead
	## means replaying every entry of every attempt to add four numbers up.
	var logger := PuzzleLogger.new()
	var path: String = logger.save_ablation_results({"results": []}, "test_token_usage")
	assert_false(path.is_empty(), "the results file was written")

	var file := FileAccess.open(path, FileAccess.READ)
	var payload = JSON.parse_string(file.get_as_text())
	file.close()
	DirAccess.remove_absolute(path)

	assert_true(payload is Dictionary, "the results file parses")
	var stated: Dictionary = (payload as Dictionary).get("usage", {})
	assert_false(stated.is_empty(),
		"a results file with no total cannot be priced without the game log")

	var expected: Dictionary = GameLogger.usage_total()
	assert_eq(stated.get("model", ABSENT), expected.get("model", ABSENT),
		"a token count that does not name its model cannot be multiplied by a price")
	assert_eq(int(stated.get("calls", -1)), int(expected.get("calls", -2)))
	assert_eq(int(stated.get("calls_without_usage", -1)),
		int(expected.get("calls_without_usage", -2)))
	var counts: Dictionary = stated.get("tokens", {})
	for field in TOKEN_FIELDS:
		assert_eq(int(counts.get(field, -1)), int(expected["tokens"].get(field, -2)),
			"the file states the run's %s" % field)
