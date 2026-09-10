class_name LogConstants
extends RefCounted

const LOG_DIRECTORY: String = "user://game_logs/"

## Which agent picked an LLM prep placement. Only the controller that received
## the placement knows this, so it is passed down rather than derived: MODEL is
## the model's own parsed answer, FALLBACK is LlmFallback.pick_random_placement,
## which runs whenever the model cannot be reached or its answer cannot be
## applied. There is no third value, so no layer can settle on one by omission.
enum Chooser { MODEL, FALLBACK }

const CHOOSER_LABELS: Dictionary = {
	Chooser.MODEL: "model",
	Chooser.FALLBACK: "fallback",
}
