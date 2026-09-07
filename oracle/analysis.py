"""The value landscape of a puzzle: difficulty, regret, and the prefix structure.

One enumeration of a puzzle's complete legal plays (``prep.enumerate_plays``)
resolved through ``engine.run_battle`` gives every number this module reports.

The VALUE of a play is the final score margin, ``llm_score - human_score``. A
margin rather than a win flag is the study's statistical-power win, so it is
what everything here is built on.

DIFFICULTY is the fraction of complete legal plays that win. "Win" is
``puzzle_runner.gd``'s own definition from ``record_attempt_result``:
``solved = llm_score > opponent_score``, so a tie is not a win.

WHOLE-PLAY REGRET is the puzzle's best achievable value minus the play's value.

PER-PLACEMENT REGRET splits that across placements. For a prefix ``p``, ``V*(p)``
is the best value over every completion of ``p``. The regret charged to the i-th
placement is ``V*(prefix before it) - V*(prefix after it)``. Because a longer
prefix maximises over a subset of the completions of a shorter one, each term is
non-negative, and the terms telescope to ``V*(empty) - value(play)``, the
whole-play regret. ``analyze_puzzle`` checks both properties over every play
rather than trusting the algebra.

Plays are keyed as strings ("A@0,0|D@1,2", the empty prefix as "") so that an
analysis loaded back from its JSON artifact scores plays exactly as one held in
memory does.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import NamedTuple

import engine
import prep

# The action space of each shipped puzzle, confirmed three ways in prep.py. A
# mismatch means the puzzle file or the prep port changed under the study, which
# invalidates every landscape built before the change, so the CLI writes nothing
# at all rather than artifacts that silently describe a different game. A puzzle
# named here and absent from the suite is the same failure wearing a rename: the
# check would otherwise just disappear.
EXPECTED_PLAY_COUNTS = {"1": 3240, "2": 1080, "3": 7230}

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "artifacts"

_KEY_SEPARATOR = "|"

_TIMING_METHOD = (
    "enumeration_seconds: perf_counter around the whole landscape pass "
    "(enumerate, build board, resolve battle, record). "
    "simulation_seconds: perf_counter around a pass of engine.run_battle over "
    "pre-built boards from an evenly spaced sample of the puzzle's plays, "
    "divided by the sample size, best of several passes."
)


def encode_placement(placement):
    """One placement as "<type>@<row>,<col>"."""
    return "%s@%d,%d" % (
        engine.TYPE_LABELS[placement.unit_type],
        placement.pos[0],
        placement.pos[1],
    )


def encode_play(play):
    """A play or prefix as its placement keys joined by "|"; "" when empty."""
    return _KEY_SEPARATOR.join(encode_placement(p) for p in play)


def puzzle_fingerprint(puzzle):
    """The loaded puzzle definition as plain JSON-safe data.

    This is the definition in full as ``prep.load_puzzles`` produced it, so a
    landscape can be matched against the suite it claims to describe instead of
    being taken on trust. It does not fingerprint the prep port or the engine;
    the play-count check is what catches those changing.
    """
    return {
        "id": puzzle.id,
        "difficulty": puzzle.difficulty,
        "llm_shop": [engine.TYPE_LABELS[unit_type] for unit_type in puzzle.llm_shop],
        "llm_gold": puzzle.llm_gold,
        "opponent_shop": [
            engine.TYPE_LABELS[unit_type] for unit_type in puzzle.opponent_shop
        ],
        "opponent_gold": puzzle.opponent_gold,
        "opponent_placements": [
            encode_placement(placement) for placement in puzzle.opponent_placements
        ],
    }


def _prefix_keys(play):
    """The keys of every proper prefix of ``play``, and the key of ``play``.

    Built by accumulation rather than by re-encoding each prefix, since the
    landscape pass calls this once per play.
    """
    keys = []
    accumulated = ""
    for placement in play:
        keys.append(accumulated)
        token = encode_placement(placement)
        accumulated = token if not accumulated else accumulated + _KEY_SEPARATOR + token
    return keys, accumulated


class PlayScore(NamedTuple):
    """What one play was worth and what it gave up.

    ``placement_regrets`` is in play order and sums to ``whole_play_regret``.
    """

    value: int
    whole_play_regret: int
    placement_regrets: tuple


@dataclass(frozen=True)
class PuzzleAnalysis:
    """The complete value landscape of one puzzle.

    ``prefix_values`` holds V* for every proper prefix, ``play_values`` the value
    of every complete play; together they are V* over every prefix. Values in
    ``value_distribution`` are keyed by the margin as a string, so the mapping
    survives a JSON round trip unchanged. ``puzzle`` is the definition every
    number below was computed from, in ``puzzle_fingerprint`` form.
    """

    puzzle_id: str
    puzzle: dict
    play_count: int
    win_count: int
    best_value: int
    worst_value: int
    value_distribution: dict
    prefix_values: dict
    play_values: dict
    enumeration_seconds: float
    simulation_seconds: float

    @property
    def difficulty(self):
        """Fraction of complete legal plays that win."""
        return self.win_count / self.play_count

    def best_value_after(self, key):
        """V* over the prefix with this key.

        A complete play is its own only completion, so its value is its V*.
        """
        value = self.prefix_values.get(key)
        if value is None:
            value = self.play_values.get(key)
        if value is None:
            raise KeyError(
                "%r is not a prefix of any legal play of puzzle %s"
                % (key, self.puzzle_id)
            )
        return value


def score_play(analysis, play):
    """The whole-play and per-placement regrets of one play.

    ``play`` is a sequence of ``prep.Placement``. It must be a complete legal
    play of the analysed puzzle; anything else is a scoring bug upstream rather
    than a lower score, so it raises.
    """
    prefixes, full_key = _prefix_keys(play)
    value = analysis.play_values.get(full_key)
    if value is None:
        raise KeyError(
            "%r is not a complete legal play of puzzle %s"
            % (full_key, analysis.puzzle_id)
        )

    stars = [analysis.best_value_after(key) for key in prefixes]
    stars.append(value)
    regrets = tuple(stars[i] - stars[i + 1] for i in range(len(prefixes)))
    return PlayScore(value, stars[0] - value, regrets)


def _build_landscape(puzzle):
    """Resolve every complete legal play and fold it into the landscape.

    Returns the landscape parts and the wall clock of the pass.
    """
    play_values = {}
    prefix_values = {}
    distribution = Counter()
    win_count = 0

    start = perf_counter()
    for play in prep.enumerate_plays(puzzle):
        result = engine.run_battle(prep.build_board(puzzle, play))
        if result["aborted"]:
            # run_battle only aborts on its step cap, which a terminating battle
            # cannot reach; the value would be read off an unfinished board.
            raise ValueError(
                "battle did not finish for play %s of puzzle %s"
                % (encode_play(play), puzzle.id)
            )
        final = result["final"]
        value = final["llm_score"] - final["human_score"]

        prefixes, full_key = _prefix_keys(play)
        play_values[full_key] = value
        for key in prefixes:
            current = prefix_values.get(key)
            if current is None or current < value:
                prefix_values[key] = value

        distribution[value] += 1
        if value > 0:
            win_count += 1
    elapsed = perf_counter() - start

    return play_values, prefix_values, distribution, win_count, elapsed


def measure_simulation_cost(puzzle, sample_size=200, repeats=5):
    """Measured seconds per battle resolution for this puzzle.

    The sample is spread evenly across the enumeration rather than taken from
    its front, because the front shares its opening placements and battle cost
    depends on what is on the board. Boards are built before timing starts, so
    the number covers resolution only. The best of several passes is reported:
    scheduling noise can only add time.
    """
    plays = list(prep.enumerate_plays(puzzle))
    step = max(1, len(plays) // sample_size)
    boards = [prep.build_board(puzzle, play) for play in plays[::step][:sample_size]]

    best = None
    for _ in range(repeats):
        start = perf_counter()
        for board in boards:
            engine.run_battle(board)
        elapsed = perf_counter() - start
        if best is None or elapsed < best:
            best = elapsed
    return best / len(boards)


def _check_decomposition(analysis, puzzle):
    """Check the properties that make the regret decomposition meaningful.

    Over every play: the per-placement regrets are non-negative and sum to the
    whole-play regret. And V* over the empty prefix is the best value in the
    puzzle, which is what makes whole-play regret a regret against the puzzle
    rather than against a subtree.
    """
    empty_star = analysis.best_value_after("")
    if empty_star != analysis.best_value:
        raise AssertionError(
            "puzzle %s: V* over the empty prefix is %d but the best play is worth %d"
            % (puzzle.id, empty_star, analysis.best_value)
        )

    for play in prep.enumerate_plays(puzzle):
        score = score_play(analysis, play)
        if sum(score.placement_regrets) != score.whole_play_regret:
            raise AssertionError(
                "puzzle %s: per-placement regrets %s do not sum to the whole-play "
                "regret %d for play %s"
                % (
                    puzzle.id,
                    score.placement_regrets,
                    score.whole_play_regret,
                    encode_play(play),
                )
            )
        if any(regret < 0 for regret in score.placement_regrets):
            raise AssertionError(
                "puzzle %s: negative per-placement regret %s for play %s"
                % (puzzle.id, score.placement_regrets, encode_play(play))
            )


def analyze_puzzle(puzzle):
    """The full landscape of one puzzle, checked and timed.

    Enumerates once, then verifies the decomposition over every play and
    measures the per-simulation cost.
    """
    play_values, prefix_values, distribution, win_count, elapsed = _build_landscape(
        puzzle
    )
    values = play_values.values()
    analysis = PuzzleAnalysis(
        puzzle_id=puzzle.id,
        puzzle=puzzle_fingerprint(puzzle),
        play_count=len(play_values),
        win_count=win_count,
        best_value=max(values),
        worst_value=min(values),
        value_distribution={
            str(value): distribution[value] for value in sorted(distribution)
        },
        prefix_values=prefix_values,
        play_values=play_values,
        enumeration_seconds=elapsed,
        simulation_seconds=measure_simulation_cost(puzzle),
    )
    _check_decomposition(analysis, puzzle)
    return analysis


# --- The artifact ---


def artifact(analysis):
    """The analysis as the JSON a later stage consumes without re-enumerating."""
    return {
        "puzzle_id": analysis.puzzle_id,
        "puzzle": analysis.puzzle,
        "win_rule": "llm_score > human_score, from puzzle_runner.gd "
        "record_attempt_result",
        "value_rule": "llm_score - human_score at the end of the battle",
        "play_count": analysis.play_count,
        "win_count": analysis.win_count,
        "difficulty": analysis.difficulty,
        "best_value": analysis.best_value,
        "worst_value": analysis.worst_value,
        "value_distribution": analysis.value_distribution,
        "prefix_values": analysis.prefix_values,
        "play_values": analysis.play_values,
        "timing": {
            "enumeration_seconds": analysis.enumeration_seconds,
            "simulation_seconds": analysis.simulation_seconds,
            "method": _TIMING_METHOD,
        },
    }


def load_analysis(path):
    """A PuzzleAnalysis read back from an artifact, ready to score plays."""
    with open(path) as handle:
        data = json.load(handle)
    return PuzzleAnalysis(
        puzzle_id=data["puzzle_id"],
        puzzle=data["puzzle"],
        play_count=data["play_count"],
        win_count=data["win_count"],
        best_value=data["best_value"],
        worst_value=data["worst_value"],
        value_distribution=data["value_distribution"],
        prefix_values=data["prefix_values"],
        play_values=data["play_values"],
        enumeration_seconds=data["timing"]["enumeration_seconds"],
        simulation_seconds=data["timing"]["simulation_seconds"],
    )


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(
        description="Build the value landscape of every puzzle in the suite."
    )
    parser.add_argument(
        "--puzzles",
        default=prep.DEFAULT_PUZZLE_PATH,
        help="puzzle suite JSON (default: the game's own suite)",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help="directory to write puzzle_<id>.json into (default: oracle/artifacts)",
    )
    args = parser.parse_args()

    analyses = []
    miscounted = []
    for puzzle in prep.load_puzzles(args.puzzles):
        analysis = analyze_puzzle(puzzle)
        analyses.append(analysis)

        expected = EXPECTED_PLAY_COUNTS.get(puzzle.id)
        if expected is not None and analysis.play_count != expected:
            miscounted.append((puzzle.id, analysis.play_count, expected))

        print("puzzle %s" % analysis.puzzle_id)
        print("  %d complete legal plays" % analysis.play_count)
        if expected is None:
            print("  play count unchecked: no expected count for this puzzle id")
        print(
            "  difficulty %.4f (%d of %d plays win)"
            % (analysis.difficulty, analysis.win_count, analysis.play_count)
        )
        print(
            "  value %d to %d, distribution %s"
            % (
                analysis.worst_value,
                analysis.best_value,
                " ".join(
                    "%s:%d" % (value, count)
                    for value, count in analysis.value_distribution.items()
                ),
            )
        )
        print(
            "  %.1f us per battle, %.3f s to enumerate the puzzle"
            % (analysis.simulation_seconds * 1e6, analysis.enumeration_seconds)
        )

    analysed_ids = {analysis.puzzle_id for analysis in analyses}
    absent = sorted(set(EXPECTED_PLAY_COUNTS) - analysed_ids)

    if miscounted or absent:
        for puzzle_id, actual, expected in miscounted:
            print(
                "puzzle %s enumerated %d plays, expected %d: the puzzle file or the "
                "prep port has changed and this landscape describes a different "
                "action space" % (puzzle_id, actual, expected),
                file=sys.stderr,
            )
        for puzzle_id in absent:
            print(
                "puzzle %s has an expected play count but is not in the suite, so "
                "its action space went unchecked" % puzzle_id,
                file=sys.stderr,
            )
        print("no artifacts written", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for analysis in analyses:
        out_path = out_dir / ("puzzle_%s.json" % analysis.puzzle_id)
        with open(out_path, "w") as handle:
            json.dump(artifact(analysis), handle, indent=1, sort_keys=True)
        print("wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
