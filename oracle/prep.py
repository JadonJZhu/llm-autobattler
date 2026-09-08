"""Standalone Python port of the Godot game's preparation phase.

Ported from ``godot/scripts/puzzle_loader.gd``, the prep half of
``godot/scripts/turn_manager.gd`` (``apply_llm_prep_placement``,
``apply_human_prep_placement``, ``skip_prep_turn``, ``_check_prep_over``),
``godot/scripts/game_controller.gd`` (``_on_prep_turn_changed`` and
``_apply_scripted_opponent_turn``), ``godot/scripts/shop.gd`` and
``godot/scripts/game_board.gd``. The GDScript is ground truth: where a rule here
looks odd, it is odd there too.

Positions are ``(row, col)`` tuples and units are
``(unit_type, owner, placement_order)`` triples, the shapes ``engine.run_battle``
takes. Types and owners are the constants from ``engine``.

A *play* is one complete legal run of prep by the agent: an ordered sequence of
(unit type, square) placements, ending where the game would stop handing the
agent a turn. It is ordered because ``battle_engine.gd`` breaks priority ties by
placement order, so the same units placed in a different order are a different
play and can resolve to a different battle.
"""

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import engine

DEFAULT_PUZZLE_PATH = (
    Path(__file__).resolve().parent.parent / "godot" / "puzzles" / "puzzle_suite.json"
)

# Shop.STARTING_GOLD, which puzzle_loader.gd defaults a missing gold field to.
STARTING_GOLD = 3

# Each side places on its own two rows only, so this is both how many units a
# side can hold and the count at which _check_prep_over calls it out of space.
SQUARES_PER_SIDE = len(engine.LLM_ROWS) * engine.COLS

# Row-major, matching GameBoard.get_empty_positions_for.
LLM_SQUARES = tuple(
    (row, col) for row in engine.LLM_ROWS for col in range(engine.COLS)
)

_VALID_TYPE_LABELS = ("A", "B", "C", "D")


class Placement(NamedTuple):
    """One buy-and-place. ``pos`` is a ``(row, col)`` square."""

    unit_type: int
    pos: tuple


@dataclass(frozen=True)
class Puzzle:
    """A scenario from puzzle_suite.json, after the loader's defaulting.

    Frozen and all-tuples so it can key the prep cache.
    """

    id: str
    difficulty: int
    llm_shop: tuple
    llm_gold: int
    opponent_shop: tuple
    opponent_gold: int
    opponent_placements: tuple


class PrepResult(NamedTuple):
    """What running prep for one play produced.

    ``llm_orders`` holds the placement_order of each of the play's placements, in
    play order. ``opponent_units`` holds ``(pos, unit_type, placement_order)`` in
    the order the scripted opponent placed them. ``refused`` holds the queued
    placements the opponent consumed but could not make.
    """

    llm_orders: tuple
    opponent_units: tuple
    refused: tuple


# --- Loading ---


def _warn(message):
    # puzzle_loader.gd reports these with push_error, which prints and carries on.
    print("prep: %s" % message, file=sys.stderr)


def _parse_shop_types(raw_types, index, field_name):
    if not isinstance(raw_types, list):
        _warn("puzzle index %d field '%s' must be an array" % (index, field_name))
        return ()
    parsed = []
    for raw_type in raw_types:
        label = str(raw_type).upper().strip()
        if label not in _VALID_TYPE_LABELS:
            _warn(
                "invalid unit type '%s' in field '%s' (puzzle index %d)"
                % (label, field_name, index)
            )
            continue
        parsed.append(engine.label_to_type(label))
    return tuple(parsed)


def _parse_opponent_placements(raw_placements, index):
    if not isinstance(raw_placements, list):
        _warn("puzzle index %d field 'opponent_placements' must be an array" % index)
        return ()
    placements = []
    for entry_index, item in enumerate(raw_placements):
        if not isinstance(item, dict):
            _warn(
                "opponent placement %d for puzzle index %d is not a dictionary"
                % (entry_index, index)
            )
            continue
        label = str(item.get("type", "")).upper().strip()
        if label not in _VALID_TYPE_LABELS:
            _warn(
                "invalid placement type '%s' at puzzle index %d entry %d"
                % (label, index, entry_index)
            )
            continue
        row = int(item.get("row", -1))
        col = int(item.get("col", -1))
        if not (0 <= row < engine.ROWS and 0 <= col < engine.COLS) or (
            row not in engine.OPPONENT_ROWS
        ):
            _warn(
                "invalid opponent placement (%d, %d) at puzzle index %d entry %d"
                % (row, col, index, entry_index)
            )
            continue
        placements.append(Placement(engine.label_to_type(label), (row, col)))
    return tuple(placements)


def _parse_scenario(raw, index):
    puzzle_id = str(raw.get("id", "")).strip()
    if not puzzle_id:
        _warn("puzzle at index %d is missing 'id'" % index)
        return None

    llm_shop = _parse_shop_types(raw.get("llm_shop", []), index, "llm_shop")
    opponent_shop = _parse_shop_types(
        raw.get("opponent_shop", []), index, "opponent_shop"
    )
    if not llm_shop:
        _warn("puzzle '%s' has empty llm_shop" % puzzle_id)
        return None
    if not opponent_shop:
        _warn("puzzle '%s' has empty opponent_shop" % puzzle_id)
        return None

    return Puzzle(
        id=puzzle_id,
        difficulty=max(1, int(raw.get("difficulty", 1))),
        llm_shop=llm_shop,
        llm_gold=max(0, int(raw.get("llm_gold", STARTING_GOLD))),
        opponent_shop=opponent_shop,
        opponent_gold=max(0, int(raw.get("opponent_gold", STARTING_GOLD))),
        opponent_placements=_parse_opponent_placements(
            raw.get("opponent_placements", []), index
        ),
    )


def load_puzzles(path=DEFAULT_PUZZLE_PATH):
    """Load the puzzle suite the way puzzle_loader.gd loads it.

    An entry the GDScript rejects with push_error is dropped here too, with the
    same reason on stderr. The game plays the file minus those entries, so an
    oracle that either refused the whole file or kept them would be measuring a
    different game from the one being studied.
    """
    with open(path) as handle:
        root = json.load(handle)

    if not isinstance(root, dict):
        _warn("root JSON must be a dictionary")
        return []
    raw_puzzles = root.get("puzzles", [])
    if not isinstance(raw_puzzles, list):
        _warn("'puzzles' must be an array")
        return []

    puzzles = []
    for index, raw in enumerate(raw_puzzles):
        if not isinstance(raw, dict):
            _warn("puzzle entry at index %d is not a dictionary" % index)
            continue
        puzzle = _parse_scenario(raw, index)
        if puzzle is not None:
            puzzles.append(puzzle)
    return puzzles


# --- The action space ---


def enumerate_plays(puzzle):
    """Yield every complete legal play for the agent, lazily.

    A play ends where ``_check_prep_over`` stops calling the agent back: it can
    afford nothing in its shop, or its own rows are full. The agent cannot stop
    early. ``_on_prep_turn_changed`` triggers an agent turn for as long as the
    turn manager hands it one, and prep ends only once both sides are done, so
    every legal play spends down to a state where no purchase is possible.

    The opponent never enters this. It places only on rows 2 and 3, so it can
    neither take a square the agent might want nor change what the agent can
    afford, and the agent's own options are therefore the same whatever the
    opponent did on its turns.

    Duplicate shop slots collapse: ``can_afford`` asks only whether the type is
    in the shop, so two plays differing by which slot a unit came from are the
    same play and the same board.
    """
    types = tuple(dict.fromkeys(puzzle.llm_shop))
    play = []
    used = set()

    def walk(gold):
        affordable = [t for t in types if gold >= engine.UNIT_COSTS[t]]
        free = [square for square in LLM_SQUARES if square not in used]
        if not affordable or not free:
            yield tuple(play)
            return
        for unit_type in affordable:
            remaining = gold - engine.UNIT_COSTS[unit_type]
            for square in free:
                play.append(Placement(unit_type, square))
                used.add(square)
                yield from walk(remaining)
                used.remove(square)
                play.pop()

    yield from walk(puzzle.llm_gold)


def count_plays(puzzle):
    """How many complete legal plays the agent has.

    Counted by walking the enumeration rather than by a formula over gold and
    squares, so the count cannot disagree with the plays actually produced.
    """
    return sum(1 for _ in enumerate_plays(puzzle))


# --- Running the prep phase ---


@lru_cache(maxsize=None)
def _run_prep(puzzle, llm_costs):
    """Prep as the game runs it, for an agent that spends ``llm_costs`` in order.

    Keyed on the costs rather than on the play because nothing else about the
    play reaches this. ``_check_prep_over`` reads only the agent's gold and how
    many of its own squares are filled, and the two sides' rows are disjoint, so
    which squares the agent picks changes neither the turn order nor anything
    the opponent does. That is what makes a cache correct here, and it is what
    keeps per-play board construction to a dictionary build.
    """
    llm_gold = puzzle.llm_gold
    llm_placed = 0
    llm_orders = []

    opponent_gold = puzzle.opponent_gold
    opponent_units = []
    occupied = set()
    refused = []
    queue = list(puzzle.opponent_placements)

    # game_controller._start_game marks an opponent with nothing queued as done.
    scripted_done = not queue
    counter = 0
    turn = engine.LLM

    while True:
        if turn == engine.LLM:
            if len(llm_orders) == len(llm_costs):
                raise ValueError(
                    "the agent still has a prep turn after %d placements, so this "
                    "is not a complete play" % len(llm_costs)
                )
            llm_gold -= llm_costs[len(llm_orders)]
            llm_orders.append(counter)
            counter += 1
            llm_placed += 1
        else:
            # _apply_scripted_opponent_turn consumes the queue entry before it
            # tries to place it, so a placement the opponent cannot make is gone
            # either way: an over-budget queue silently loses units.
            placement = queue.pop(0) if queue else None
            scripted_done = not queue
            if placement is not None:
                cost = engine.UNIT_COSTS[placement.unit_type]
                # apply_human_prep_placement's guards. The square is on the
                # opponent's own half by construction, because the loader drops
                # any placement that is not, which leaves can_afford (both the
                # in-shop test and the gold test) and the occupancy test.
                if (
                    placement.unit_type in puzzle.opponent_shop
                    and opponent_gold >= cost
                    and placement.pos not in occupied
                ):
                    opponent_gold -= cost
                    opponent_units.append((placement.pos, placement.unit_type, counter))
                    occupied.add(placement.pos)
                    counter += 1
                else:
                    refused.append(placement)

        llm_done = llm_placed >= SQUARES_PER_SIDE or not any(
            llm_gold >= engine.UNIT_COSTS[t] for t in puzzle.llm_shop
        )
        opponent_done = (
            scripted_done
            or len(occupied) >= SQUARES_PER_SIDE
            or not any(
                opponent_gold >= engine.UNIT_COSTS[t] for t in puzzle.opponent_shop
            )
        )
        if llm_done and opponent_done:
            break

        # A side that is done does not get skipped turns: the other side keeps
        # the turn until it is done too.
        if turn == engine.LLM:
            turn = engine.LLM if opponent_done else engine.OPPONENT
        else:
            turn = engine.OPPONENT if llm_done else engine.LLM

    if len(llm_orders) != len(llm_costs):
        raise ValueError(
            "prep ended after %d of the play's %d placements, so this is not a "
            "legal play" % (len(llm_orders), len(llm_costs))
        )
    return PrepResult(tuple(llm_orders), tuple(opponent_units), tuple(refused))


def simulate_prep(puzzle, play):
    """Run the prep phase for one play and return its PrepResult.

    Raises ValueError if the play is not one the game could have produced.
    """
    gold = puzzle.llm_gold
    used = set()
    for index, placement in enumerate(play):
        cost = engine.UNIT_COSTS[placement.unit_type]
        if placement.unit_type not in puzzle.llm_shop or gold < cost:
            raise ValueError(
                "placement %d buys %s with %d gold left"
                % (index, engine.TYPE_LABELS[placement.unit_type], gold)
            )
        if placement.pos not in LLM_SQUARES or placement.pos in used:
            raise ValueError(
                "placement %d is on %s, which is not a free square of the agent's"
                % (index, (placement.pos,))
            )
        gold -= cost
        used.add(placement.pos)
    return _run_prep(puzzle, tuple(engine.UNIT_COSTS[p.unit_type] for p in play))


def build_board(puzzle, play):
    """The starting board a play produces, ready for ``engine.run_battle``."""
    result = simulate_prep(puzzle, play)
    board = {
        pos: (unit_type, engine.OPPONENT, order)
        for pos, unit_type, order in result.opponent_units
    }
    for placement, order in zip(play, result.llm_orders):
        board[placement.pos] = (placement.unit_type, engine.LLM, order)
    return board


# --- CLI ---


def _format_placements(placements):
    return " ".join(
        "%s(%d,%d)" % (engine.TYPE_LABELS[unit_type], pos[0], pos[1])
        for unit_type, pos in placements
    )


def _shop_label(types):
    return "/".join(engine.TYPE_LABELS[t] for t in types)


def main():
    for puzzle in load_puzzles():
        # One pass over the whole action space, collecting the count and every
        # distinct opponent outcome, so the opponent lines below are measured
        # across all plays rather than read off one of them. Placement orders are
        # left out of the outcome: they do vary with how the agent spends, which
        # is why they are shown per play at the end instead.
        count = 0
        outcomes = {}
        first_play = None
        for play in enumerate_plays(puzzle):
            count += 1
            if first_play is None:
                first_play = play
            result = simulate_prep(puzzle, play)
            units = tuple(
                Placement(unit_type, pos) for pos, unit_type, _ in result.opponent_units
            )
            outcomes[(units, result.refused)] = None

        queue_cost = sum(
            engine.UNIT_COSTS[p.unit_type] for p in puzzle.opponent_placements
        )
        print("puzzle %s" % puzzle.id)
        print(
            "  agent: %d gold, shop %s -> %d complete plays"
            % (puzzle.llm_gold, _shop_label(puzzle.llm_shop), count)
        )
        print(
            "  opponent: %d gold, shop %s, %d queued placements costing %d"
            % (
                puzzle.opponent_gold,
                _shop_label(puzzle.opponent_shop),
                len(puzzle.opponent_placements),
                queue_cost,
            )
        )
        for units, refused in outcomes:
            print(
                "    starts with %d units: %s"
                % (len(units), _format_placements(units))
            )
            if refused:
                print(
                    "    %d queued placement(s) refused and lost: %s"
                    % (len(refused), _format_placements(refused))
                )
        board = build_board(puzzle, first_play)
        print("  first play %s builds:" % _format_placements(first_play))
        print(
            "    %s"
            % " ".join(
                "%s%s(%d,%d)#%d"
                % (
                    "llm " if owner == engine.LLM else "opp ",
                    engine.TYPE_LABELS[unit_type],
                    pos[0],
                    pos[1],
                    order,
                )
                for pos, (unit_type, owner, order) in sorted(board.items())
            )
        )


if __name__ == "__main__":
    main()
