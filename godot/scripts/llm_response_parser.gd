class_name LlmResponseParser
extends RefCounted

var valid_rows: Array[int] = [0, 1]


func parse_place_command(text: String) -> Dictionary:
	var search_pattern: String = "PLACE:"
	var last_index: int = text.rfind(search_pattern)
	if last_index == -1:
		push_error("LlmResponseParser: No PLACE: command found in response.")
		return {}

	var after_tag: String = text.substr(last_index + search_pattern.length()).strip_edges()

	# Expected format: <type> (row, col)
	var type_str: String = ""
	var paren_start: int = -1
	for i in range(after_tag.length()):
		var character: String = after_tag[i]
		if character == "(":
			paren_start = i
			break
		if character != " ":
			type_str += character

	type_str = type_str.strip_edges().to_upper()
	if type_str not in ["A", "B", "C", "D"]:
		push_error("LlmResponseParser: Invalid unit type in PLACE command: '%s'" % type_str)
		return {}

	if paren_start == -1:
		push_error("LlmResponseParser: No coordinates found in PLACE command.")
		return {}

	var paren_end: int = after_tag.find(")", paren_start)
	if paren_end == -1:
		push_error("LlmResponseParser: Missing closing paren in PLACE command.")
		return {}

	var coord_text: String = after_tag.substr(paren_start + 1, paren_end - paren_start - 1)
	var parts: PackedStringArray = coord_text.split(",")
	if parts.size() != 2:
		push_error("LlmResponseParser: Expected 2 coordinates, got %d." % parts.size())
		return {}

	var row_str: String = parts[0].strip_edges()
	var col_str: String = parts[1].strip_edges()
	if not row_str.is_valid_int() or not col_str.is_valid_int():
		push_error("LlmResponseParser: Non-integer coordinates: '%s', '%s'" % [row_str, col_str])
		return {}

	var row: int = row_str.to_int()
	var col: int = col_str.to_int()

	# Validate rows and columns
	if row not in valid_rows:
		push_error("LlmResponseParser: Row %d is not in valid rows %s." % [row, str(valid_rows)])
		return {}
	if col < 0 or col >= GridConstants.COLS:
		push_error("LlmResponseParser: Column %d is out of range (must be 0-%d)." % [col, GridConstants.COLS - 1])
		return {}

	var unit_type: UnitData.UnitType = UnitData.type_from_string(type_str)
	return {
		"unit_type": unit_type,
		"position": Vector2i(row, col),
	}
