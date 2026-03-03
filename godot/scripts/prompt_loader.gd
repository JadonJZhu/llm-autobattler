class_name PromptLoader
extends RefCounted
## Loads text prompts from res://prompts/ and caches them.

const PROMPTS_BASE_PATH: String = "res://prompts/"

var _cache: Dictionary = {}


func load_prompt(filename: String) -> String:
	if filename.is_empty():
		push_error("PromptLoader: Empty filename.")
		return ""

	if _cache.has(filename):
		return _cache[filename]

	var path: String = PROMPTS_BASE_PATH + filename
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("PromptLoader: Failed to open prompt file: " + path)
		return ""

	var content: String = file.get_as_text()
	file.close()
	_cache[filename] = content
	return content


func load_template(filename: String, placeholders: Dictionary = {}) -> String:
	var template: String = load_prompt(filename)
	if template.is_empty():
		return ""
	if placeholders.is_empty():
		return template
	return template.format(placeholders)
