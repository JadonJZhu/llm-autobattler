extends GutTest

var builder: LlmPromptBuilder


func before_each():
	builder = LlmPromptBuilder.new()


# =============================================================================
# A. build_system_prompt
# =============================================================================

func test_system_prompt_always_includes_api_and_format():
	var config := LlmModeConfig.new()
	config.instructions_enabled = false
	config.examples_enabled = false
	config.reflection_enabled = false
	var prompt := builder.build_system_prompt(config)
	assert_string_contains(prompt, "4x3 autochess", "API section should always be included")
	assert_string_contains(prompt, "RESPONSE FORMAT", "Response format should always be included")
	assert_string_contains(prompt, "PLACE:", "Format section should describe PLACE command")


func test_system_prompt_with_instructions_enabled():
	var config := LlmModeConfig.new()
	config.instructions_enabled = true
	config.examples_enabled = false
	config.reflection_enabled = false
	var prompt := builder.build_system_prompt(config)
	assert_string_contains(prompt, "BATTLE MECHANICS", "Rules section should be included")
	assert_string_contains(prompt, "STRATEGY TIPS")


func test_system_prompt_with_examples_enabled():
	var config := LlmModeConfig.new()
	config.instructions_enabled = false
	config.examples_enabled = true
	config.reflection_enabled = false
	var prompt := builder.build_system_prompt(config)
	assert_string_contains(prompt, "EXAMPLES", "Examples section should be included")


func test_system_prompt_with_reflection_enabled_and_feedback():
	var config := LlmModeConfig.new()
	config.instructions_enabled = false
	config.examples_enabled = false
	config.reflection_enabled = true
	var feedback := "You should place more D units to counter the opponent's A units."
	var prompt := builder.build_system_prompt(config, feedback)
	assert_string_contains(prompt, "REFLECTION FROM PREVIOUS GAMES")
	assert_string_contains(prompt, feedback, "Feedback text should appear in prompt")


func test_system_prompt_reflection_enabled_but_empty_feedback():
	var config := LlmModeConfig.new()
	config.instructions_enabled = false
	config.examples_enabled = false
	config.reflection_enabled = true
	var prompt := builder.build_system_prompt(config, "")
	assert_does_not_have(prompt, "REFLECTION FROM PREVIOUS GAMES",
		"Reflection section should not appear with empty feedback")


# =============================================================================
# B. format_game_replay
# =============================================================================

func test_format_game_replay_basic():
	var replay: Dictionary = {
		"start_board": "some board text",
		"battle_steps": ["A attacks B", "C advances"],
		"outcome": "LLM",
		"llm_score": 3,
		"human_score": 1,
	}
	var output := builder.format_game_replay(replay, 1)
	assert_string_contains(output, "Game 1 Replay")
	assert_string_contains(output, "some board text")
	assert_string_contains(output, "1. A attacks B")
	assert_string_contains(output, "2. C advances")
	assert_string_contains(output, "LLM wins")
	assert_string_contains(output, "LLM 3 vs Opponent 1")


func test_format_game_replay_with_game_number():
	var replay: Dictionary = { "outcome": "Human", "llm_score": 0, "human_score": 2 }
	var output := builder.format_game_replay(replay, 3)
	assert_string_contains(output, "Game 3 Replay")


func test_format_game_replay_empty_battle_steps():
	var replay: Dictionary = {
		"start_board": "board",
		"battle_steps": [],
		"outcome": "Tie",
		"llm_score": 0,
		"human_score": 0,
	}
	var output := builder.format_game_replay(replay)
	assert_ne(output, "", "Output should not be empty")
	assert_string_contains(output, "Outcome: Tie")
	# Should not contain "Battle trace:" when steps are empty
	assert_does_not_have(output, "Battle trace:")


# --- Helper for negative assertions ---

func assert_does_not_have(text: String, substring: String, msg: String = ""):
	var message := msg if not msg.is_empty() else "Expected text to NOT contain '%s'" % substring
	assert_false(text.find(substring) >= 0, message)
