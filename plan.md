# Testing Strategy Implementation Plan

## Prerequisites

### Step 0: Install GUT Addon

GUT is not yet installed in the project. Before any tests can run:

1. **Download GUT** via the Godot Asset Library (top center of Godot editor → search "GUT - Godot Unit Testing") or manually from GitHub.
2. **Verify** `godot/addons/gut/` exists after installation.
3. **Enable the plugin** in Project → Project Settings → Plugins → GUT → Enable.
4. **Configure test directories** in the GUT panel settings (see Step 1 below).

> **This is a manual Godot editor step.** The human engineer should perform the install and plugin activation.

### Step 1: Create Test Directory Structure

```
godot/
  test/
    unit/
      test_battle_engine.gd
      test_llm_response_parser.gd
      test_shop.gd
      test_board_serializer.gd
      test_llm_prompt_builder.gd
```

After creating the directories, configure GUT to scan `res://test/unit` in the GUT panel settings (GUT Panel → Settings → Test Directories).

> **The directory creation can be done via script; the GUT panel config is a manual editor step.**

---

## Tier 1: Highest Impact, Lowest Cost

---

### Test 1: `BattleEngine` + `BattleSnapshot`

**File:** `godot/test/unit/test_battle_engine.gd`

This is the highest-value test file. `BattleEngine` is pure `RefCounted` — instantiate with `.new()`, feed it hand-crafted `BattleSnapshot` objects, and assert deterministic outcomes.

#### Helper Setup

```gdscript
extends GutTest

var engine: BattleEngine

func before_each():
    engine = BattleEngine.new()

# Helper to build a BattleSnapshot from a dictionary of positions
func _make_snapshot(unit_defs: Array[Dictionary]) -> BattleSnapshot:
    var snap = BattleSnapshot.new()
    for i in unit_defs.size():
        var d = unit_defs[i]
        snap.units[d.pos] = {
            "unit_type": d.type,
            "owner": d.owner,
            "placement_order": d.get("placement_order", i)
        }
    return snap
```

#### Test Cases by Category

**A. Unit Type A — Straight Attack & Advance**

1. `test_a_attacks_enemy_directly_ahead` — Place LLM A at (0,1), Human unit at (1,1). Execute step for LLM. Assert the Human unit at (1,1) is removed and event_type is "attack".
2. `test_a_advances_when_clear` — Place LLM A at (0,1), no unit at (1,1). Execute step. Assert A moved from (0,1) to (1,1), event_type is "advance".
3. `test_a_blocked_when_friendly_ahead` — Place LLM A at (0,1) and another LLM unit at (1,1). Execute step. Assert A does NOT move, event_type is "blocked" or "pass".
4. `test_a_escapes_off_board_edge` — Place LLM A at (3,1) (last row before escape). Advance it. Assert it escapes, `snap.llm_escaped` increments by 1, event_type is "escaped".
5. `test_human_a_attacks_upward` — Place Human A at (3,1), LLM unit at (2,1). Execute step for HUMAN. Assert LLM unit removed. (Confirms direction is owner-dependent.)
6. `test_human_a_escapes_off_top_edge` — Place Human A at (0,1), no enemies. Execute step. Assert it escapes, `snap.human_escaped` increments.

**B. Unit Type B — Diagonal-Left Attack & Advance**

7. `test_b_attacks_diag_left` — LLM B at (0,1), enemy at (1,0). Assert enemy removed.
8. `test_b_advances_when_diag_clear` — LLM B at (0,1), no enemy at (1,0). Assert B advances forward (to (1,1)).
9. `test_b_on_leftmost_col_cannot_attack` — LLM B at (0,0), enemy at (1,0) (directly ahead). Assert B does NOT attack — it has no diagonal-left target and cannot attack straight. B must advance instead.
10. `test_b_on_leftmost_col_advances` — LLM B at (0,0), cell ahead clear. Assert B advances forward to (1,0).
11. `test_b_on_leftmost_col_escapes` — LLM B at (3,0) (last row, leftmost col). Assert B escapes off the board edge, `snap.llm_escaped` increments.
12. `test_human_b_diag_left_is_mirrored` — Human B at (3,1), enemy at (2,2). Confirm diagonal direction is owner-relative.

**C. Unit Type C — Diagonal-Right Attack & Advance**

11. `test_c_attacks_diag_right` — LLM C at (0,1), enemy at (1,2). Assert enemy removed.
12. `test_c_advances_when_diag_clear` — LLM C at (0,1), no enemy at (1,2). Assert C advances forward.
15. `test_c_on_rightmost_col_cannot_attack` — LLM C at (0,2), enemy at (1,2) (directly ahead). Assert C does NOT attack — it has no diagonal-right target and cannot attack straight. C must advance instead.
16. `test_c_on_rightmost_col_advances` — LLM C at (0,2), cell ahead clear. Assert C advances forward to (1,2).
17. `test_c_on_rightmost_col_escapes` — LLM C at (3,2) (last row, rightmost col). Assert C escapes off the board edge, `snap.llm_escaped` increments.
18. `test_human_c_diag_right_is_mirrored` — Human C at (3,1), enemy at (2,0). Confirm direction mirroring.

**D. Unit Type D — Ranged Manhattan Distance**

19. `test_d_removes_closest_enemy_by_manhattan` — LLM D at (0,0), enemies at (2,0) (dist 2) and (3,2) (dist 5). Assert the closer enemy is removed.
20. `test_d_tiebreak_left_to_right` — LLM D at (1,1), enemies at (2,0) (dist 2) and (2,2) (dist 2). Assert (2,0) is picked (leftmost column).
21. `test_d_tiebreak_top_to_bottom` — LLM D at (1,1), enemies at (2,1) (dist 1) and (0,1) — wait, that's friendly. Use enemies at same manhattan distance but different rows, same column. Assert top-most (lower row index) is picked.
22. `test_d_no_enemies_does_nothing` — LLM D alone on board. Assert event_type is "pass" or similar.
23. `test_d_does_not_advance` — Confirm D stays in place after attacking (ranged unit).

**E. Priority & Placement Order**

24. `test_priority_a_before_b_before_c_before_d` — Place all four LLM unit types. Run one step. Assert the A unit acts first.
25. `test_same_type_priority_by_placement_order` — Place two LLM A units with different `placement_order`. Assert the lower placement_order acts first.

**F. Stalemate Detection**

26. `test_stalemate_when_no_units_can_act` — Construct a board where all units are blocked (e.g., two columns of same-owner units facing each other with no attack targets). Assert `engine.is_stalemate(snap)` returns true.
27. `test_not_stalemate_when_action_possible` — Normal board. Assert `is_stalemate()` returns false.

**G. Winner Determination & Scoring**

28. `test_winner_when_all_enemy_eliminated` — Run steps until one side has no units. Assert `is_finished` is true and `winner` is the surviving side.
29. `test_score_includes_escaped_and_remaining` — Construct scenario where LLM has 1 unit on board + 1 escaped. Assert `llm_score == 2`.
30. `test_empty_board_is_finished` — No units at all. Assert terminal state.

**H. Full Battle Simulation**

31. `test_full_battle_deterministic_replay` — Set up a specific board, run all steps to completion, record the sequence. Run again with identical setup. Assert identical step-by-step results. (Regression anchor test.)

---

### Test 2: `LlmResponseParser`

**File:** `godot/test/unit/test_llm_response_parser.gd`

Pure string → dictionary parsing. Use parameterized tests (GUT's `use_parameters`) for table-driven coverage.

#### Setup

```gdscript
extends GutTest

var parser: LlmResponseParser

func before_each():
    parser = LlmResponseParser.new()
    # Default valid_rows = [0, 1] (LLM rows)
```

#### Test Cases

**A. Valid Inputs**

1. `test_parse_valid_place_commands` — Parameterized test with:
   - `"PLACE: A (0, 1)"` → `{ unit_type: UnitData.UnitType.A, position: Vector2i(0, 1) }`
   - `"PLACE: B (1, 0)"` → B at (1,0)
   - `"PLACE: C (0, 2)"` → C at (0,2)
   - `"PLACE: D (1, 2)"` → D at (1,2)

2. `test_parse_extracts_last_place_command` — Input has multiple PLACE lines; assert the **last** one is returned.

3. `test_parse_ignores_preceding_text` — Input: `"I think I'll go with\nPLACE: A (0, 0)"`. Assert parses correctly.

4. `test_parse_case_insensitive_type` — `"PLACE: a (0, 0)"` — verify if lowercase is accepted. (If not, this documents that behavior.)

**B. Invalid / Malformed Inputs**

5. `test_parse_empty_string_returns_empty` — `""` → `{}`
6. `test_parse_no_place_keyword_returns_empty` — `"I want to put A at row 0 col 1"` → `{}`
7. `test_parse_malformed_coords_returns_empty` — `"PLACE: A (abc, def)"` → `{}`
8. `test_parse_missing_parens_returns_empty` — `"PLACE: A 0, 1"` → `{}`
9. `test_parse_unknown_type_returns_empty` — `"PLACE: Z (0, 0)"` → `{}`

**C. Out-of-Bounds Validation**

10. `test_parse_row_out_of_valid_rows` — `"PLACE: A (2, 0)"` with default valid_rows=[0,1] → `{}`
11. `test_parse_col_out_of_bounds` — `"PLACE: A (0, 3)"` (COLS=3, so max col=2) → `{}`
12. `test_parse_negative_coords` — `"PLACE: A (-1, 0)"` → `{}`

**D. Custom valid_rows**

13. `test_parse_with_human_valid_rows` — Set `parser.valid_rows = [2, 3]`. Assert `"PLACE: A (2, 1)"` succeeds and `"PLACE: A (0, 1)"` fails.

---

### Test 3: `Shop`

**File:** `godot/test/unit/test_shop.gd`

#### Setup

```gdscript
extends GutTest

func _make_shop(types: Array[UnitData.UnitType], gold: int = 3) -> Shop:
    var shop = Shop.new()
    shop.available_types = types
    shop.gold = gold
    return shop
```

#### Test Cases

**A. Purchase Logic**

1. `test_purchase_deducts_gold` — Shop with [A, B, C], gold=3. Purchase A (cost 1). Assert gold == 2.
2. `test_purchase_d_deducts_2_gold` — Shop with [D], gold=3. Purchase D. Assert gold == 1.
3. `test_purchase_returns_true_on_success` — Assert `shop.purchase(UnitData.UnitType.A)` returns `true`.
4. `test_purchase_when_broke_returns_false` — Gold=0, try purchase. Assert returns false, gold unchanged.
5. `test_purchase_unavailable_type_returns_false` — Shop has [A, B], try purchasing C. Assert false.

**B. can_afford**

6. `test_can_afford_with_sufficient_gold` — Gold=1, type A available. Assert true.
7. `test_can_afford_with_insufficient_gold` — Gold=1, type D (cost 2) available. Assert false.
8. `test_can_afford_with_missing_type` — Gold=3, type not in available_types. Assert false.

**C. can_afford_any**

9. `test_can_afford_any_with_gold` — Gold=1, has [A]. Assert true.
10. `test_can_afford_any_when_broke` — Gold=0. Assert false.
11. `test_can_afford_any_only_d_with_1_gold` — Gold=1, only [D] available. Assert false (D costs 2).

**D. Edge Cases**

12. `test_starting_gold_is_3` — `Shop.new()`. Assert `shop.gold == 3`.
13. `test_purchase_summary_format` — Verify `get_purchase_summary()` returns expected string format.

---

### Test 4: `BoardSerializer`

**File:** `godot/test/unit/test_board_serializer.gd`

Test `serialize_snapshot()` — static method, takes a Dictionary, returns ASCII String.

#### Setup

```gdscript
extends GutTest
```

#### Test Cases

1. `test_empty_board_serialization` — Empty dictionary. Assert output is a valid 4x3 grid with all cells showing `"."` or equivalent empty marker.
2. `test_single_llm_unit` — `{ Vector2i(0, 1): { "unit_type": UnitData.UnitType.A, "owner": UnitData.Owner.LLM } }`. Assert cell (0,1) shows `"LA"` (LLM prefix + type).
3. `test_single_human_unit` — Human B at (3, 0). Assert shows `"HB"`.
4. `test_full_board_snapshot` — Place units in multiple cells. Assert the complete ASCII output matches expected string.
5. `test_meta_score_summary` — Include `"__meta"` key with `{ "llm_escaped": 1, "human_escaped": 2 }`. Assert score summary line appears in output.
6. `test_snapshot_without_meta` — No `"__meta"` key. Assert no score summary line (or empty summary).

---

## Tier 2: Moderate Impact, Moderate Cost

---

### Test 5: `LlmPromptBuilder`

**File:** `godot/test/unit/test_llm_prompt_builder.gd`

Only the scene-free methods are testable without mocking.

#### Setup

```gdscript
extends GutTest

var builder: LlmPromptBuilder

func before_each():
    builder = LlmPromptBuilder.new()
```

#### Test Cases

**A. `build_system_prompt`** (requires `LlmModeConfig`, which is also `RefCounted`)

1. `test_system_prompt_always_includes_api_and_format` — Config with all flags false. Assert output contains response format section and API section.
2. `test_system_prompt_with_instructions_enabled` — `config.instructions_enabled = true`. Assert output contains rules/instructions content.
3. `test_system_prompt_with_examples_enabled` — `config.examples_enabled = true`. Assert output contains examples section.
4. `test_system_prompt_with_reflection_enabled_and_feedback` — `config.reflection_enabled = true`, pass feedback string. Assert output contains the feedback.
5. `test_system_prompt_reflection_enabled_but_empty_feedback` — Reflection on, empty string. Assert no reflection section appears.

**B. `format_game_replay`**

6. `test_format_game_replay_basic` — Provide a replay dict with `start_board`, `battle_steps` (array of step descriptions), `outcome` string, `llm_score`, `human_score`. Assert output contains all components.
7. `test_format_game_replay_with_game_number` — Pass `game_number = 3`. Assert "Game 3" (or similar label) appears in output.
8. `test_format_game_replay_empty_battle_steps` — Empty `battle_steps` array. Assert no crash, output still valid.

---

## Implementation Order

Execute in this exact order to maximize early value:

| Step | Action | Details |
|------|--------|---------|
| 0 | Install GUT | Human engineer: install via Asset Library, enable plugin |
| 1 | Create directory structure | Create `godot/test/unit/` |
| 2 | Configure GUT | Human engineer: set test dir to `res://test/unit` in GUT panel |
| 3 | Write `test_battle_engine.gd` | **Highest priority** — 27 test cases covering all unit types, priority, stalemate, scoring, determinism |
| 4 | Run & verify battle tests | Fix any test failures, ensure all green |
| 5 | Write `test_llm_response_parser.gd` | 13 parameterized test cases |
| 6 | Run & verify parser tests | |
| 7 | Write `test_shop.gd` | 13 test cases |
| 8 | Run & verify shop tests | |
| 9 | Write `test_board_serializer.gd` | 6 test cases |
| 10 | Run & verify serializer tests | |
| 11 | Write `test_llm_prompt_builder.gd` | 8 test cases |
| 12 | Run & verify prompt builder tests | |
| 13 | Full regression run | Run all tests via GUT "Run All" or command line |

---

## Running Tests

Tests can be run three ways:
1. **GUT Panel** in Godot editor — click "Run All"
2. **Command line** — `godot --headless -s addons/gut/gut_cmdln.gd` (see `gut-docs/command-line.md` for flags)
3. **VSCode** — via the GUT VSCode extension

---

## Notes & Open Questions

- **B/C edge behavior on boundary columns**: Tests 9, 10, 13, 14 depend on reading `_act_b` and `_act_c` to confirm exact edge-column behavior. The plan assumes "attacks straight ahead" on boundary but should be verified against source.
- **D tie-breaking**: Tests 16–17 assume left-to-right then top-to-bottom from the CLAUDE.md spec. Verify against `_find_closest_enemy` implementation.
- **Parameterized test syntax**: GUT supports `use_parameters()` for table-driven tests (see `gut-docs/parameterized-tests.md`). Use this for parser tests to keep them DRY.
- **No mocking needed**: All Tier 1 and Tier 2 tests target pure `RefCounted` classes. No doubles, stubs, or scene tree required.
