class_name LlmModeConfig
extends RefCounted
## Pure data class holding the three mode toggles for LLM prompt composition.
## Each LLM player gets its own config instance.

var instructions_enabled: bool = true
var examples_enabled: bool = false
var reflection_enabled: bool = false


func get_label() -> String:
	return "I%d_E%d_R%d" % [
		int(instructions_enabled),
		int(examples_enabled),
		int(reflection_enabled),
	]
