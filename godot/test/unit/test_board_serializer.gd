extends GutTest


# =============================================================================
# 1. Empty Board
# =============================================================================

func test_empty_board_serialization():
	var snapshot: Dictionary = {}
	var output := BoardSerializer.serialize_snapshot(snapshot)
	assert_string_contains(output, "col 0")
	assert_string_contains(output, "col 1")
	assert_string_contains(output, "col 2")
	assert_string_contains(output, "row 0")
	assert_string_contains(output, "row 3")
	# All cells should be empty markers "."
	assert_string_contains(output, ".")
	# Score should be all zeros
	assert_string_contains(output, "Score Summary: LLM 0 | Opponent 0")


# =============================================================================
# 2. Single LLM Unit
# =============================================================================

func test_single_llm_unit():
	var snapshot: Dictionary = {
		Vector2i(0, 1): { "unit_type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
	}
	var output := BoardSerializer.serialize_snapshot(snapshot)
	assert_string_contains(output, "La", "LLM A unit should show as 'La'")
	assert_string_contains(output, "Score Summary: LLM 1 | Opponent 0")


# =============================================================================
# 3. Single Human Unit
# =============================================================================

func test_single_human_unit():
	var snapshot: Dictionary = {
		Vector2i(3, 0): { "unit_type": UnitData.UnitType.B, "owner": UnitData.Owner.HUMAN },
	}
	var output := BoardSerializer.serialize_snapshot(snapshot)
	assert_string_contains(output, "Hb", "Human B unit should show as 'Hb'")
	assert_string_contains(output, "Score Summary: LLM 0 | Opponent 1")


# =============================================================================
# 4. Full Board Snapshot
# =============================================================================

func test_full_board_snapshot():
	var snapshot: Dictionary = {
		Vector2i(0, 0): { "unit_type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		Vector2i(0, 2): { "unit_type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM },
		Vector2i(1, 1): { "unit_type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM },
		Vector2i(2, 0): { "unit_type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
		Vector2i(3, 2): { "unit_type": UnitData.UnitType.B, "owner": UnitData.Owner.HUMAN },
	}
	var output := BoardSerializer.serialize_snapshot(snapshot)
	assert_string_contains(output, "La")
	assert_string_contains(output, "Lc")
	assert_string_contains(output, "Ld")
	assert_string_contains(output, "Ha")
	assert_string_contains(output, "Hb")
	assert_string_contains(output, "Score Summary: LLM 3 | Opponent 2")


# =============================================================================
# 5. Meta Score Summary with Escaped
# =============================================================================

func test_meta_score_summary():
	var snapshot: Dictionary = {
		Vector2i(0, 0): { "unit_type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		"__meta": { "llm_escaped": 1, "human_escaped": 2 },
	}
	var output := BoardSerializer.serialize_snapshot(snapshot)
	assert_string_contains(output, "Score Summary: LLM 2 | Opponent 2")


# =============================================================================
# 6. Snapshot Without Meta
# =============================================================================

func test_snapshot_without_meta():
	var snapshot: Dictionary = {
		Vector2i(1, 1): { "unit_type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM },
	}
	var output := BoardSerializer.serialize_snapshot(snapshot)
	assert_string_contains(output, "Score Summary: LLM 1 | Opponent 0")
