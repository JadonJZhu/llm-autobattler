"""Standalone Python port of the Godot game's battle resolution.

Ported from ``godot/scripts/battle_engine.gd`` and the battle loop in
``godot/scripts/turn_manager.gd`` (``_start_battle`` / ``_execute_battle_step``).
The GDScript is ground truth: where a rule here looks odd, it is odd there too.

Positions are ``(row, col)`` tuples. The GDScript stores them in a ``Vector2i``
whose ``x`` is the row and whose ``y`` is the column, and prints them in that
order, so ``(3,1)`` means row 3, column 1 in both.

A unit is a ``(unit_type, owner, placement_order)`` tuple.
"""

import argparse
import json

A, B, C, D = 0, 1, 2, 3
LLM, OPPONENT = 0, 1

TYPE_LABELS = {A: "A", B: "B", C: "C", D: "D"}
UNIT_COSTS = {A: 1, B: 1, C: 1, D: 2}

ROWS = 4
COLS = 3
LLM_ROWS = (0, 1)
OPPONENT_ROWS = (2, 3)

_TYPE_FROM_LABEL = {label: unit_type for unit_type, label in TYPE_LABELS.items()}
_OWNER_LABELS = {LLM: "llm", OPPONENT: "human"}
_OWNER_FROM_LABEL = {label: owner for owner, label in _OWNER_LABELS.items()}


def label_to_type(label):
    """Map "A".."D" to a type constant. Unknown labels raise."""
    try:
        return _TYPE_FROM_LABEL[label.upper()]
    except KeyError:
        raise ValueError("unknown unit type label: %r" % (label,)) from None


# --- Geometry and board queries ---


def _fmt(pos):
    return "(%d,%d)" % pos


def _cell_ahead(pos, owner):
    # The LLM faces down the board (increasing row), the opponent faces up.
    if owner == LLM:
        return (pos[0] + 1, pos[1])
    return (pos[0] - 1, pos[1])


def _has_enemy_at(units, cell, owner):
    unit = units.get(cell)
    return unit is not None and unit[1] != owner


def _has_any_enemy(units, owner):
    for unit in units.values():
        if unit[1] != owner:
            return True
    return False


def _find_closest_enemy(units, pos, owner):
    """Nearest enemy by Manhattan distance, ties broken by column then row."""
    row, col = pos
    closest = None
    best_distance = ROWS * COLS + 1
    for cell, unit in units.items():
        if unit[1] == owner:
            continue
        distance = abs(cell[0] - row) + abs(cell[1] - col)
        if distance < best_distance:
            best_distance = distance
            closest = cell
        elif distance == best_distance and (
            cell[1] < closest[1] or (cell[1] == closest[1] and cell[0] < closest[0])
        ):
            closest = cell
    return closest


# --- Unit actions ---
#
# Each returns ``(event, event_type)`` and mutates ``units`` in place. ``event``
# is None unless ``trace`` is set, and so is the per-step record ``run_battle``
# keeps. Together those two cost about a sixth of a battle's run time, split
# roughly evenly between the strings built here and the record built there
# (measured 2026-09-07, best of seven over 30,000 random boards: 3.10s untraced
# against 3.72s traced). Neither half dominates, so the untraced path skips
# both; enumeration runs hundreds of thousands of battles and reads neither.
#
# An escape does not increment the escape counter here; the caller does that on
# seeing the "escaped" event type, since a unit only ever escapes off its own
# owner's forward edge.


def _try_advance(units, pos, owner, trace):
    unit = units[pos]
    ahead = _cell_ahead(pos, owner)
    if ahead[0] < 0 or ahead[0] >= ROWS:
        del units[pos]
        event = "%s %s escape" % (TYPE_LABELS[unit[0]], _fmt(pos)) if trace else None
        return event, "escaped"

    if ahead in units:
        # Not reachable through _pick_acting_unit, which never selects a unit
        # that can neither attack nor move.
        event = "%s %s no_action" % (TYPE_LABELS[unit[0]], _fmt(pos)) if trace else None
        return event, "blocked"

    del units[pos]
    units[ahead] = unit
    event = (
        "%s %s -> %s" % (TYPE_LABELS[unit[0]], _fmt(pos), _fmt(ahead)) if trace else None
    )
    return event, "advance"


def _act_a(units, pos, owner, trace):
    ahead = _cell_ahead(pos, owner)
    if _has_enemy_at(units, ahead, owner):
        del units[ahead]
        event = "A %s x %s" % (_fmt(pos), _fmt(ahead)) if trace else None
        return event, "attack"
    return _try_advance(units, pos, owner, trace)


def _act_b(units, pos, owner, trace):
    # B attacks diagonally forward-left. On the leftmost column that square is
    # off the board, so it can only advance.
    if pos[1] == 0:
        return _try_advance(units, pos, owner, trace)

    ahead = _cell_ahead(pos, owner)
    diag_left = (ahead[0], ahead[1] - 1)
    if _has_enemy_at(units, diag_left, owner):
        del units[diag_left]
        event = "B %s x %s" % (_fmt(pos), _fmt(diag_left)) if trace else None
        return event, "attack"
    return _try_advance(units, pos, owner, trace)


def _act_c(units, pos, owner, trace):
    # C is B mirrored: diagonally forward-right, blocked on the rightmost column.
    if pos[1] == COLS - 1:
        return _try_advance(units, pos, owner, trace)

    ahead = _cell_ahead(pos, owner)
    diag_right = (ahead[0], ahead[1] + 1)
    if _has_enemy_at(units, diag_right, owner):
        del units[diag_right]
        event = "C %s x %s" % (_fmt(pos), _fmt(diag_right)) if trace else None
        return event, "attack"
    return _try_advance(units, pos, owner, trace)


def _act_d(units, pos, owner, trace):
    # D shoots the closest enemy anywhere on the board and never moves.
    target = _find_closest_enemy(units, pos, owner)
    if target is not None:
        del units[target]
        event = "D %s x %s" % (_fmt(pos), _fmt(target)) if trace else None
        return event, "attack"
    # Not reachable through _pick_acting_unit, which only selects a D while an
    # enemy is on the board.
    event = "D %s no_action" % _fmt(pos) if trace else None
    return event, "pass"


_ACTIONS = (_act_a, _act_b, _act_c, _act_d)


# --- Selecting who acts ---


def _can_diagonal_attack_or_advance(units, pos, ahead, owner, col_offset, can_advance):
    edge_col = 0 if col_offset < 0 else COLS - 1
    if pos[1] != edge_col:
        if _has_enemy_at(units, (ahead[0], ahead[1] + col_offset), owner):
            return True
    return can_advance


def _can_unit_act(units, pos, owner):
    unit_type = units[pos][0]
    ahead = _cell_ahead(pos, owner)
    # Walking off the far edge counts as a move: it is an escape, not a wall.
    can_advance = ahead[0] < 0 or ahead[0] >= ROWS or ahead not in units

    if unit_type == A:
        return _has_enemy_at(units, ahead, owner) or can_advance
    if unit_type == B:
        return _can_diagonal_attack_or_advance(units, pos, ahead, owner, -1, can_advance)
    if unit_type == C:
        return _can_diagonal_attack_or_advance(units, pos, ahead, owner, 1, can_advance)
    if unit_type == D:
        return _has_any_enemy(units, owner)
    raise ValueError("unknown unit type: %r" % (unit_type,))


def _pick_acting_unit(units, owner):
    """Highest-priority unit of ``owner`` that can act, or None.

    Priority is type A > B > C > D, then lower placement_order first. The sort
    is stable, matching the insertion sort Godot's sort_custom falls back to for
    the small arrays a 4x3 board produces; that only matters when two units of
    one owner share a placement_order, which the game does not produce.
    """
    candidates = [pos for pos, unit in units.items() if unit[1] == owner]
    candidates.sort(key=lambda pos: (units[pos][0], units[pos][2]))
    for pos in candidates:
        if _can_unit_act(units, pos, owner):
            return pos
    return None


def _count_units(units):
    llm_count = 0
    human_count = 0
    for unit in units.values():
        if unit[1] == LLM:
            llm_count += 1
        else:
            human_count += 1
    return llm_count, human_count


def _winner_of(llm_score, human_score):
    if llm_score > human_score:
        return "llm"
    if human_score > llm_score:
        return "human"
    return "tie"


# --- The battle loop ---


def run_battle(units, trace=False, max_steps=200):
    """Play a whole battle from a starting board.

    ``units`` maps (row, col) to (unit_type, owner, placement_order) and is
    treated as read-only. The LLM acts first and the active owner alternates
    after every non-terminal step.

    ``max_steps`` is a divergence guard rather than a game rule: every step of a
    real battle kills, moves or escapes a unit, so a real battle terminates. If
    the cap is reached the returned "aborted" flag is true.
    """
    board = dict(units)
    escaped = [0, 0]
    active = LLM
    steps = []

    # The picks double as the terminal test and as the next step's actor, so
    # they are computed once per state rather than once per use.
    picks = [_pick_acting_unit(board, LLM), _pick_acting_unit(board, OPPONENT)]
    llm_count, human_count = _count_units(board)
    llm_score = llm_count + escaped[LLM]
    human_score = human_count + escaped[OPPONENT]
    winner = _winner_of(llm_score, human_score)

    n = 0
    finished = False
    while n < max_steps:
        n += 1
        acting = picks[active]
        if acting is None:
            event, event_type = ("PASS" if trace else None), "pass"
        else:
            event, event_type = _ACTIONS[board[acting][0]](board, acting, active, trace)
            if event_type == "escaped":
                escaped[active] += 1

        picks[LLM] = _pick_acting_unit(board, LLM)
        picks[OPPONENT] = _pick_acting_unit(board, OPPONENT)
        llm_count, human_count = _count_units(board)
        llm_score = llm_count + escaped[LLM]
        human_score = human_count + escaped[OPPONENT]
        winner = _winner_of(llm_score, human_score)

        # An empty board is also a board where neither side can act, so the
        # engine's separate empty-board condition adds nothing to these two.
        finished = (picks[LLM] is None and picks[OPPONENT] is None) or (
            (llm_count == 0) != (human_count == 0)
        )

        if trace:
            if finished:
                event = event + " | END" if event else "END"
            steps.append(
                {
                    "n": n,
                    "active_owner": _OWNER_LABELS[active],
                    "event": event,
                    "event_type": event_type,
                    "is_finished": finished,
                    "winner": winner if finished else None,
                    "llm_score": llm_score,
                    "human_score": human_score,
                    "llm_remaining": llm_count,
                    "human_remaining": human_count,
                    "llm_escaped": escaped[LLM],
                    "human_escaped": escaped[OPPONENT],
                }
            )

        if finished:
            break
        active = 1 - active

    return {
        "steps": steps,
        "final": {
            "winner": winner,
            "llm_score": llm_score,
            "human_score": human_score,
            "llm_remaining": llm_count,
            "human_remaining": human_count,
            "llm_escaped": escaped[LLM],
            "human_escaped": escaped[OPPONENT],
            "steps": n,
        },
        "aborted": not finished,
    }


# --- CLI ---


def _bad_label(case_id, index, field, value, table):
    return ValueError(
        "case %r: units[%d] %s is %r, expected one of %s"
        % (case_id, index, field, value, ", ".join(sorted(table)))
    )


def _board_from_case(case):
    """Build a board from a case.

    A label the case generator got wrong is reported with the case, the unit and
    the offending value, since these are read in bulk and a bare lookup failure
    names none of the three.
    """
    case_id = case.get("id", "<no id>")
    board = {}
    for index, entry in enumerate(case["units"]):
        try:
            unit_type = label_to_type(entry["type"])
        except (ValueError, AttributeError):
            raise _bad_label(
                case_id, index, "type", entry["type"], _TYPE_FROM_LABEL
            ) from None
        try:
            owner = _OWNER_FROM_LABEL[entry["owner"]]
        except (KeyError, TypeError):
            raise _bad_label(
                case_id, index, "owner", entry["owner"], _OWNER_FROM_LABEL
            ) from None
        board[(entry["row"], entry["col"])] = (
            unit_type,
            owner,
            entry["placement_order"],
        )
    return board


def main():
    parser = argparse.ArgumentParser(
        description="Run battle cases through the oracle engine and write their traces."
    )
    parser.add_argument("--cases", required=True, help="input JSON with a 'cases' list")
    parser.add_argument("--out", required=True, help="output JSON to write")
    args = parser.parse_args()

    with open(args.cases) as handle:
        cases = json.load(handle)["cases"]

    traces = []
    for case in cases:
        result = run_battle(_board_from_case(case), trace=True)
        traces.append(
            {
                "id": case["id"],
                "steps": result["steps"],
                "final": result["final"],
                "aborted": result["aborted"],
            }
        )

    with open(args.out, "w") as handle:
        json.dump({"traces": traces}, handle, indent=2)


if __name__ == "__main__":
    main()
