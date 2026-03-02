# Plan: Update Battle Phase Scanning & Win Condition

## Goal & Motivation

Two core mechanics need to change:

1. **Battle phase unit scanning should skip blocked units.** Currently, during battle phase, each side's units are scanned in priority order A > B > C > D (ties broken by placement order), and the first unit found attempts an action. However, if that unit is blocked (e.g., cannot attack and cannot advance because the cell ahead is occupied), the turn is wasted — no other unit gets a chance to act. The fix: continue scanning down the priority list until a unit that **can** take an action is found. Only if *no* unit on that side can act should the step be a no-op.

2. **Win condition should be a score, not elimination.** Currently the game ends when one side's units are all removed, and that side loses. The new win condition: the game ends when **neither side can take any more actions** (true stalemate). The winner is determined by **score = units still on the board + units that escaped** (i.e., moved off the board via the opponent's edge). A unit that advances past the opponent's edge counts as an "escape" rather than simply being removed. Higher score wins; equal scores = tie.

These changes affect battle logic, win condition evaluation, the instructions shown to the player, the LLM system prompt, and game logging/history.

---

## Step-by-Step Implementation

### Step 1: Track escaped units in BattleEngine

**File:** `godot/scripts/battle_engine.gd`

- Add two counters to the battle snapshot: `llm_escaped: int` and `human_escaped: int`, initialized to `0` when the snapshot is first created.
- In `_try_advance()`: when a unit moves off the board (the existing `ahead.x < 0 or ahead.x >= ROWS` branch), increment the appropriate escape counter in the snapshot instead of just removing the unit silently. The unit is still removed from the board, but now it's counted.
- Ensure the step result events include an `"escaped"` event string (e.g., `"A at (0,2) escaped off the board"`) so it can be logged and displayed.

### Step 2: Update `_pick_acting_unit` to skip blocked units

**File:** `godot/scripts/battle_engine.gd`

- Currently `_pick_acting_unit()` returns the single highest-priority candidate. Change it to return a **list of candidates sorted by priority** (or iterate internally).
- New logic in `execute_step()`: iterate through the sorted candidate list. For each candidate, **check if it can act** before committing:
  - **Unit A:** Can act if the cell directly ahead has an enemy (attack) OR the cell directly ahead is empty (advance) OR the cell ahead is off-board (escape). Blocked only if ahead cell is occupied by a friendly unit or a same-side unit.
  - **Unit B:** Can act if its diagonal-left-ahead cell has an enemy (attack), OR it can advance (ahead cell is empty or off-board). Blocked if diagonal target is empty/friendly AND ahead cell is occupied.
  - **Unit C:** Same as B but diagonal-right-ahead.
  - **Unit D:** Can act if there is any enemy on the board. Cannot move, so if no enemies exist, it cannot act.
- The first unit in priority order that **can** act is selected. If none can act, the step is a no-op for that side.
- Consider extracting a `_can_unit_act(snapshot, unit_pos, owner) -> bool` helper to keep this clean.

### Step 3: Update `_check_terminal` win condition

**File:** `godot/scripts/battle_engine.gd`

- Remove the current win condition logic (one side has 0 units = loss).
- New terminal condition: the game ends when **both sides** have no unit that can act (i.e., `_pick_acting_unit` returns nothing for both LLM and HUMAN in sequence — a true double-stalemate).
  - Note: also end if both sides literally have 0 units on the board.
- When terminal, compute scores:
  - `llm_score = llm_units_on_board + llm_escaped`
  - `human_score = human_units_on_board + human_escaped`
- Return the winner based on higher score, or `null` for a tie if scores are equal.
- Include both scores in the result dictionary so they can be logged and displayed.

### Step 4: Update stalemate detection

**File:** `godot/scripts/battle_engine.gd`

- The existing `is_stalemate()` function checks if neither side can pick an acting unit. With the new `_pick_acting_unit` that skips blocked units, this naturally aligns — if `_pick_acting_unit` returns no candidate for both sides, it's terminal.
- Merge stalemate detection into the new `_check_terminal` logic so there's one unified end-of-game check. Stalemate is now just the normal way the game ends (not a special edge case).

### Step 5: Update TurnManager to handle new end-game data

**File:** `godot/scripts/turn_manager.gd`

- Update `_end_game()` to accept and propagate scores (llm_score, human_score) alongside the winner.
- Update the `game_over` signal to include scores.
- When a side's `_pick_acting_unit` returns no candidate but the other side still can act, **skip that side's turn** rather than ending the game. The game only ends when neither side can act on consecutive checks.

### Step 6: Update GameController end-game display

**File:** `godot/scripts/game_controller.gd`

- Update `_on_game_over()` (or equivalent handler) to display scores, not just winner.
- Show something like: `"LLM: 3 pts (2 remaining + 1 escaped) — Human: 2 pts (1 remaining + 1 escaped)"`.
- Update the status label text accordingly.

### Step 7: Update GameLogger

**File:** `godot/scripts/game_logger.gd`

- Update `log_game_result()` to include both scores, units remaining, and units escaped in the log entry.
- Update `log_battle_step()` to capture escape events distinctly (so the replay can mention escapes).
- Update `finalize_game_replay()` to include final scores in the outcome data, so the LLM receives score context in subsequent games.
- Update `get_previous_game_replay()` return format to include score breakdown.

### Step 8: Update LLM system prompt

**File:** `godot/scripts/llm_client.gd`

- In `_build_system_prompt()`, update the rules section:
  - **Battle mechanics:** Explain that if the highest-priority unit is blocked, the next unit in priority order attempts to act, and so on.
  - **Escaping:** Clarify that a unit advancing past the opponent's edge counts as an "escape" and earns a point.
  - **Win condition:** The game ends when neither side can take any actions. Winner is determined by `score = units on board + escaped units`. Higher score wins.
  - **Strategy implications:** The LLM should consider that escaping units is a valid (and valuable) strategy, not just elimination.
- In `_build_user_message()`, if a previous game replay is included, make sure the outcome section shows scores (not just "LLM"/"Human"/"Tie").

### Step 9: Update player-facing instructions

**File:** `godot/scripts/instructions_menu.gd`

- Update the `BATTLE PHASE` section:
  - Add: "If the highest-priority unit cannot act (blocked), the next unit in priority tries instead."
  - Change: "Units that advance past opponent's edge are removed" → "Units that advance past opponent's edge **escape** and earn 1 point."
- Update the `WINNING` section:
  - Remove: "Eliminate all enemy units to win"
  - Add: "The battle ends when neither side can take any more actions."
  - Add: "Your score = units remaining on the board + units that escaped."
  - Add: "Highest score wins. Equal scores = tie."

### Step 10: Update BoardSerializer (if needed)

**File:** `godot/scripts/board_serializer.gd`

- If the serialized board state sent to the LLM includes any game-state summary (like remaining unit counts), update it to also show escaped counts and current scores.
- If it's purely a grid representation, no changes needed here — the score context will come from the prompt and replay.

### Step 11: Update GameBoard visual feedback (if applicable)

**File:** `godot/scripts/game_board.gd`

- In `apply_battle_step()`, if an escape event occurs, consider adding a brief visual indication (e.g., the unit slides off the edge before being removed) rather than just disappearing. This is optional/cosmetic but improves clarity.
- Update any score display that `GameBoard` might own (or confirm this is handled by `GameController`/`ShopUI`).

### Step 12: Testing & edge cases

Verify the following scenarios work correctly:

- **All units blocked on one side, not the other:** The blocked side's turn is skipped; the other side keeps acting. Game does not end until both are stuck.
- **All units escape:** A side with 0 units on board but 3 escaped should score 3.
- **Mixed outcome:** Side A has 1 unit on board + 2 escaped = 3 pts vs. Side B has 2 on board + 0 escaped = 2 pts → Side A wins.
- **Mutual annihilation:** Both sides reach 0 units on board, 0 escaped = tie (score 0-0).
- **D unit alone with no enemies:** D cannot act (no target), and cannot move. If it's the only unit left, that side is stuck. If the other side is also stuck, game ends. The D unit counts as 1 remaining.
- **Unit scanning exhausts all candidates:** If every unit on a side is blocked (all paths occupied, no valid attacks), that side passes. Confirm the turn toggle still works correctly.

---

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `battle_engine.gd` | Escape tracking, skip-blocked-unit scanning, new win condition |
| `turn_manager.gd` | Score propagation, skip-side-when-stuck logic |
| `game_controller.gd` | Score display in end-game UI |
| `game_logger.gd` | Log escapes, scores, updated replay format |
| `llm_client.gd` | Updated system prompt and replay formatting |
| `instructions_menu.gd` | Updated player-facing rules text |
| `board_serializer.gd` | Possibly add score/escape context (if applicable) |
| `game_board.gd` | Escape visual feedback (optional) |
