extends GutTest

var engine: BattleEngine


func before_each():
	engine = BattleEngine.new()


func _make_snapshot(unit_defs: Array[Dictionary]) -> BattleSnapshot:
	var snap := BattleSnapshot.new()
	for i in unit_defs.size():
		var d: Dictionary = unit_defs[i]
		snap.units[d.pos] = {
			"unit_type": d.type,
			"owner": d.owner,
			"placement_order": d.get("placement_order", i),
		}
	return snap


# =============================================================================
# A. Unit Type A — Straight Attack & Advance
# =============================================================================

func test_a_attacks_enemy_directly_ahead():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "attack", "A should attack enemy directly ahead")
	assert_eq(result["removal"], Vector2i(1, 1), "Enemy at (1,1) should be removed")
	assert_false(snap.units.has(Vector2i(1, 1)), "Enemy should no longer be in snapshot")


func test_a_advances_when_clear():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(3, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "advance", "A should advance when cell ahead is clear")
	assert_eq(result["move"]["from"], Vector2i(0, 1))
	assert_eq(result["move"]["to"], Vector2i(1, 1))
	assert_true(snap.units.has(Vector2i(1, 1)), "A should now be at (1,1)")
	assert_false(snap.units.has(Vector2i(0, 1)), "A should no longer be at (0,1)")


func test_a_blocked_when_friendly_ahead():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM, "placement_order": 1 },
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM, "placement_order": 0 },
		{ "pos": Vector2i(3, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN, "placement_order": 2 },
	])
	# A has higher type priority but cannot act (friendly at (1,1) blocks it).
	# B is next in priority and can advance, so B should act instead.
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["acting_unit_type"], UnitData.UnitType.B, "A is blocked so B should act next")
	assert_eq(result["event_type"], "advance", "B should advance since cell ahead is clear")
	assert_true(snap.units.has(Vector2i(0, 1)), "A should remain at (0,1)")
	assert_true(snap.units.has(Vector2i(2, 1)), "B should have advanced to (2,1)")
	assert_false(snap.units.has(Vector2i(1, 1)), "B should no longer be at (1,1)")


func test_a_escapes_off_board_edge():
	var snap := _make_snapshot([
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "escaped", "A should escape off the board edge")
	assert_eq(result["self_removal"], Vector2i(3, 1))
	assert_eq(snap.llm_escaped, 1, "LLM escaped count should increment")
	assert_false(snap.units.has(Vector2i(3, 1)), "A should be removed from the board")


func test_human_a_attacks_upward():
	var snap := _make_snapshot([
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(2, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.HUMAN)
	assert_eq(result["event_type"], "attack", "Human A should attack upward")
	assert_eq(result["removal"], Vector2i(2, 1), "LLM unit at (2,1) should be removed")


func test_human_a_escapes_off_top_edge():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.HUMAN)
	assert_eq(result["event_type"], "escaped", "Human A should escape off the top edge")
	assert_eq(snap.human_escaped, 1, "Human escaped count should increment")


# =============================================================================
# B. Unit Type B — Diagonal-Left Attack & Advance
# =============================================================================

func test_b_attacks_diag_left():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(1, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "attack", "B should attack diagonally left")
	assert_eq(result["removal"], Vector2i(1, 0))


func test_b_advances_when_diag_clear():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "advance", "B should advance when diagonal is clear")
	assert_eq(result["move"]["to"], Vector2i(1, 1), "B advances straight forward")


func test_b_on_leftmost_col_cannot_attack():
	# B at col 0 cannot attack diagonally left; should advance instead
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(1, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	# B on leftmost col can't attack diag-left and can't advance (occupied). No other LLM units, so turn is skipped.
	assert_eq(result["event_type"], "pass", "B on leftmost col cannot act; turn should be skipped")


func test_b_on_leftmost_col_advances():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "advance", "B on leftmost col should advance forward")
	assert_eq(result["move"]["to"], Vector2i(1, 0))


func test_b_on_leftmost_col_escapes():
	var snap := _make_snapshot([
		{ "pos": Vector2i(3, 0), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "escaped", "B on last row should escape")
	assert_eq(snap.llm_escaped, 1)


func test_human_b_diag_left_is_mirrored():
	# Human B at (3,1) faces up, diag-left-ahead = (2, 2)
	var snap := _make_snapshot([
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.B, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(2, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.HUMAN)
	# Human B faces up: ahead = (2,1), diag_left = (2, 0)
	assert_eq(result["event_type"], "attack")
	assert_eq(result["removal"], Vector2i(2, 0), "Human B diagonal-left is col-1 when facing up")


# =============================================================================
# C. Unit Type C — Diagonal-Right Attack & Advance
# =============================================================================

func test_c_attacks_diag_right():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(1, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "attack")
	assert_eq(result["removal"], Vector2i(1, 2))


func test_c_advances_when_diag_clear():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "advance")
	assert_eq(result["move"]["to"], Vector2i(1, 1))


func test_c_on_rightmost_col_cannot_attack():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 2), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(1, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	# C on rightmost col skips diagonal, tries advance. Cell ahead occupied → blocked.
	assert_eq(result["event_type"], "pass")


func test_c_on_rightmost_col_advances():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 2), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "advance")
	assert_eq(result["move"]["to"], Vector2i(1, 2))


func test_c_on_rightmost_col_escapes():
	var snap := _make_snapshot([
		{ "pos": Vector2i(3, 2), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "escaped")
	assert_eq(snap.llm_escaped, 1)


func test_human_c_diag_right_is_mirrored():
	# Human C at (3,1) faces up: ahead = (2,1), diag_right = (2, 2)
	var snap := _make_snapshot([
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.C, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(2, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.HUMAN)
	assert_eq(result["event_type"], "attack")
	assert_eq(result["removal"], Vector2i(2, 2), "Human C diagonal-right is col+1 when facing up")


# =============================================================================
# D. Unit Type D — Ranged Manhattan Distance
# =============================================================================

func test_d_removes_closest_enemy_by_manhattan():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(2, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(3, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "attack")
	assert_eq(result["removal"], Vector2i(2, 0), "D should remove closest enemy (dist 2 vs dist 5)")


func test_d_tiebreak_left_to_right():
	var snap := _make_snapshot([
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(2, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(2, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	# Both enemies at manhattan distance 2. Tie-break: smaller col wins.
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["removal"], Vector2i(2, 0), "Tie-break should pick leftmost column (col 0)")


func test_d_tiebreak_top_to_bottom():
	# (2,1) has manhattan dist 1, (3,1) has dist 2 — not a tie. Use equal distances:
	# Actually let's use enemies at same distance and same column
	# D at (1,1): enemy at (0,1) dist=1 and (2,1) dist=1 — but (0,1) would be friendly row
	# Let's adjust: D at (2,1), enemies at (0,1) dist=2 and (3,0) dist=2
	# Wait, (3,0): dist = |3-2|+|0-1| = 2, (0,1): dist = |0-2|+|1-1| = 2
	# Tie-break: smaller col first → (0,1) col=1 vs (3,0) col=0 → (3,0) wins
	# This tests left-to-right. For top-to-bottom with same col:
	var snap := _make_snapshot([
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(2, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	# (0,0): dist = 1+1 = 2, (2,0): dist = 1+1 = 2. Same col (0). Tie-break: smaller row → (0,0)
	var result2 := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result2["removal"], Vector2i(0, 0), "Same col tie-break should pick top-most (smaller row)")


func test_d_no_enemies_does_nothing():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "pass", "D with no enemies should pass")


func test_d_does_not_advance():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(3, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
		{ "pos": Vector2i(3, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "attack")
	assert_eq(result["removal"], Vector2i(3, 0), "D should target closest enemy by Manhattan distance")
	assert_null(result["move"], "D should not advance after attacking")
	assert_true(snap.units.has(Vector2i(0, 0)), "D should remain in place")


# =============================================================================
# E. Priority & Placement Order
# =============================================================================

func test_priority_a_before_b_before_c_before_d():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.D, "owner": UnitData.Owner.LLM, "placement_order": 0 },
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM, "placement_order": 1 },
		{ "pos": Vector2i(0, 2), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM, "placement_order": 2 },
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM, "placement_order": 3 },
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN, "placement_order": 0 },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["acting_unit_type"], UnitData.UnitType.A, "A should have highest priority")


func test_same_type_priority_by_placement_order():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM, "placement_order": 5 },
		{ "pos": Vector2i(0, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM, "placement_order": 2 },
	])
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["acting_unit_pos"], Vector2i(0, 2), "Lower placement_order (2) should act first")


# =============================================================================
# F. Stalemate Detection
# =============================================================================

func test_stalemate_when_no_units_can_act():
	# Two columns of same-owner units facing each other but blocked
	var snap := _make_snapshot([
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM, "placement_order": 0 },
		{ "pos": Vector2i(2, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN, "placement_order": 0 },
	])
	# A at (1,1) faces enemy at (2,1) — can attack. Not stalemate yet.
	# Need a scenario where nobody can act. B/C on edge columns blocked by friendlies:
	var stale_snap := _make_snapshot([
		{ "pos": Vector2i(1, 0), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM, "placement_order": 0 },
		{ "pos": Vector2i(2, 0), "type": UnitData.UnitType.B, "owner": UnitData.Owner.HUMAN, "placement_order": 0 },
	])
	# LLM B at (1,0): on leftmost col, can't diag-attack. Ahead is (2,0) occupied → blocked.
	# Human B at (2,0): on leftmost col, can't diag-attack. Ahead is (1,0) occupied → blocked.
	assert_true(engine.is_stalemate(stale_snap), "Should be stalemate when no units can act")


func test_not_stalemate_when_action_possible():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	assert_false(engine.is_stalemate(snap), "Should not be stalemate when units can advance")


# =============================================================================
# G. Winner Determination & Scoring
# =============================================================================

func test_winner_when_all_enemy_eliminated():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(1, 1), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	# LLM A attacks Human A → Human has no units left
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["event_type"], "attack")
	# After removing Human's only unit, check terminal
	# LLM has 1 unit, Human has 0 → LLM can still act (not both stuck)
	# But human has 0 units and 0 escaped, so human_can_act = false
	# LLM can still act → not both_stuck → game continues
	# Need to run until both sides can't act or both empty
	# Let's run the LLM unit to escape
	var result2 := engine.execute_step(snap, UnitData.Owner.LLM)
	var result3 := engine.execute_step(snap, UnitData.Owner.LLM)
	var result4 := engine.execute_step(snap, UnitData.Owner.LLM)
	# At some point board should be empty and game finished
	var finished: bool = result["is_finished"] or result2["is_finished"] or result3["is_finished"] or result4["is_finished"]
	assert_true(finished, "Game should finish when all units gone")


func test_score_includes_escaped_and_remaining():
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM },
		{ "pos": Vector2i(3, 2), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN },
	])
	snap.llm_escaped = 1
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_eq(result["llm_escaped"], 1, "Escaped count should be tracked")
	# LLM has 1 remaining + 1 escaped = score 2
	assert_eq(result["llm_score"], 2, "Score should include both remaining and escaped")


func test_empty_board_is_finished():
	var snap := BattleSnapshot.new()
	var result := engine.execute_step(snap, UnitData.Owner.LLM)
	assert_true(result["is_finished"], "Empty board should be terminal")


# =============================================================================
# H. Full Battle Simulation — Deterministic Replay
# =============================================================================

func test_full_battle_deterministic_replay():
	var results_a: Array[Dictionary] = _run_full_battle()
	var results_b: Array[Dictionary] = _run_full_battle()

	assert_eq(results_a.size(), results_b.size(), "Replay should produce same number of steps")
	for i in results_a.size():
		assert_eq(results_a[i]["event_type"], results_b[i]["event_type"],
			"Step %d event_type should match" % i)
		assert_eq(results_a[i]["acting_unit_pos"], results_b[i]["acting_unit_pos"],
			"Step %d acting_unit_pos should match" % i)
		assert_eq(results_a[i]["removal"], results_b[i]["removal"],
			"Step %d removal should match" % i)
		assert_eq(results_a[i]["move"], results_b[i]["move"],
			"Step %d move should match" % i)


func _run_full_battle() -> Array[Dictionary]:
	var snap := _make_snapshot([
		{ "pos": Vector2i(0, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM, "placement_order": 0 },
		{ "pos": Vector2i(0, 1), "type": UnitData.UnitType.B, "owner": UnitData.Owner.LLM, "placement_order": 1 },
		{ "pos": Vector2i(1, 2), "type": UnitData.UnitType.C, "owner": UnitData.Owner.LLM, "placement_order": 2 },
		{ "pos": Vector2i(3, 0), "type": UnitData.UnitType.A, "owner": UnitData.Owner.HUMAN, "placement_order": 0 },
		{ "pos": Vector2i(3, 1), "type": UnitData.UnitType.B, "owner": UnitData.Owner.HUMAN, "placement_order": 1 },
		{ "pos": Vector2i(2, 2), "type": UnitData.UnitType.C, "owner": UnitData.Owner.HUMAN, "placement_order": 2 },
	])
	var results: Array[Dictionary] = []
	var active_owner := UnitData.Owner.LLM
	var max_steps := 50
	for i in max_steps:
		var result := engine.execute_step(snap, active_owner)
		results.append(result)
		if result["is_finished"]:
			break
		active_owner = UnitData.Owner.HUMAN if active_owner == UnitData.Owner.LLM else UnitData.Owner.LLM
	return results
