extends GutTest

var parser: LlmResponseParser


func before_each():
	parser = LlmResponseParser.new()


# =============================================================================
# A. Valid Inputs
# =============================================================================

func test_parse_valid_place_commands(params = use_parameters([
	[{ "input": "PLACE: A (0, 1)", "type": UnitData.UnitType.A, "pos": Vector2i(0, 1) }],
	[{ "input": "PLACE: B (1, 0)", "type": UnitData.UnitType.B, "pos": Vector2i(1, 0) }],
	[{ "input": "PLACE: C (0, 2)", "type": UnitData.UnitType.C, "pos": Vector2i(0, 2) }],
	[{ "input": "PLACE: D (1, 2)", "type": UnitData.UnitType.D, "pos": Vector2i(1, 2) }],
])):
	var p: Dictionary = params[0]
	var result := parser.parse_place_command(p["input"])
	assert_eq(result["unit_type"], p["type"])
	assert_eq(result["position"], p["pos"])


func test_parse_extracts_last_place_command():
	var text := "PLACE: A (0, 0)\nPLACE: B (1, 2)"
	var result := parser.parse_place_command(text)
	assert_eq(result["unit_type"], UnitData.UnitType.B, "Should extract the last PLACE command")
	assert_eq(result["position"], Vector2i(1, 2))


func test_parse_ignores_preceding_text():
	var text := "I think I'll go with\nPLACE: A (0, 0)"
	var result := parser.parse_place_command(text)
	assert_eq(result["unit_type"], UnitData.UnitType.A)
	assert_eq(result["position"], Vector2i(0, 0))


func test_parse_case_insensitive_type():
	var result := parser.parse_place_command("PLACE: a (0, 0)")
	# Parser converts to uppercase internally
	assert_eq(result["unit_type"], UnitData.UnitType.A, "Lowercase type should be accepted")


# =============================================================================
# B. Invalid / Malformed Inputs
# =============================================================================

func test_parse_empty_string_returns_empty():
	var result := parser.parse_place_command("")
	assert_eq(result, {}, "Empty string should return empty dict")


func test_parse_no_place_keyword_returns_empty():
	var result := parser.parse_place_command("I want to put A at row 0 col 1")
	assert_eq(result, {})


func test_parse_malformed_coords_returns_empty():
	var result := parser.parse_place_command("PLACE: A (abc, def)")
	assert_eq(result, {})


func test_parse_missing_parens_returns_empty():
	var result := parser.parse_place_command("PLACE: A 0, 1")
	assert_eq(result, {})


func test_parse_unknown_type_returns_empty():
	var result := parser.parse_place_command("PLACE: Z (0, 0)")
	assert_eq(result, {})


# =============================================================================
# C. Out-of-Bounds Validation
# =============================================================================

func test_parse_row_out_of_valid_rows():
	var result := parser.parse_place_command("PLACE: A (2, 0)")
	assert_eq(result, {}, "Row 2 is not in default valid_rows [0, 1]")


func test_parse_col_out_of_bounds():
	var result := parser.parse_place_command("PLACE: A (0, 3)")
	assert_eq(result, {}, "Col 3 is out of bounds (COLS=3, max col=2)")


func test_parse_negative_coords():
	var result := parser.parse_place_command("PLACE: A (-1, 0)")
	assert_eq(result, {}, "Negative coords should fail")


# =============================================================================
# D. Custom valid_rows
# =============================================================================

func test_parse_with_opponent_valid_rows():
	parser.valid_rows = [2, 3]
	var success := parser.parse_place_command("PLACE: A (2, 1)")
	assert_eq(success["unit_type"], UnitData.UnitType.A, "Row 2 should be valid with opponent rows")
	assert_eq(success["position"], Vector2i(2, 1))

	var fail := parser.parse_place_command("PLACE: A (0, 1)")
	assert_eq(fail, {}, "Row 0 should fail with opponent valid_rows [2, 3]")
