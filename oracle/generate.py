"""Random puzzle generation, and what a puzzle at a target difficulty costs.

Difficulty is not a knob on a generated puzzle: it is a property you only learn
by enumerating the puzzle's whole action space and resolving every play, which
is what ``analysis`` does. So generating a puzzle at a target difficulty is
reject sampling, and the cost of a suite is the cost of every candidate that was
enumerated and thrown away, not the cost of the ones that were kept.

This module measures that. In order:

1. The prior. A sample of random legal puzzles, every one of them enumerated,
   giving the distribution of difficulty over random puzzles. Nothing about a
   target is decided before this, because the prior is what says which targets
   exist at all.
2. The acceptance rate per target, over that same sample. A candidate is
   accepted at target ``t`` if its difficulty is within the band of ``t``.
   Every enumeration behind the table happened, but a 0.05-wide band accepts a
   few percent of candidates, so a 200-candidate sample rests each target on a
   single-digit count. The table therefore reports an interval rather than a
   rate, including for a target nothing landed in, and states which targets
   differ by more than that interval. Where none do, the ordering of the
   column is noise and the table says so in those words.
3. A forecast. Resampling the measured difficulties to fill a set of quotas,
   which prices a rule without enumerating another candidate. It prices two
   rules and labels both: the wide bins step 4 fills, and the same number of
   puzzles spread over the step 2 targets at the band. The two are different
   acceptance rules, the wider one is always cheaper, and neither number
   checks the other.
4. A suite. Bins filled by reject sampling from a fresh seed stream, capped in
   attempts. Its enumerations per accepted puzzle price those bins and say
   nothing about the band of step 2. The bins come from one of two rules, and
   the caller picks: ``--suite-bins`` spans the range this run's own prior
   happened to observe, which over a large sample is very nearly 0 to 1;
   ``--suite-edges`` is the caller naming the edges outright, which is the only
   way to ask for a band the prior did not reach, or for bins of uneven width.
   A band the prior barely reached is priced before it is spent: step 3
   forecasts the same edges this step fills, and says so in those words when no
   resample of the prior could fill them.
   A candidate every play wins, or none does, is rejected however well it fills
   a bin, because it is decided before the agent chooses and so measures
   nothing about an agent. The file it writes ranks puzzles from the easiest,
   which is the opposite direction to the win fraction, and carries the bin
   each one filled beside it: see ``accepted_in_order`` and ``puzzle_json``.
   It also stamps the arguments this run resolved, so the file says what would
   produce it again: see ``study_provenance``.

STRUCTURE IS BUILT IN; ONLY DIFFICULTY IS SAMPLED FOR. Difficulty is knowable
only by enumerating, so aiming at it costs every candidate that missed. The two
other things a suite has to control are properties of a puzzle's own
description: how large the agent's action space is, which its shop and its gold
settle on their own, and which unit types the opponent fields, which its queue
settles. Those are constructed rather than rejected for, so asking for them
costs no enumerations at all. ``--suite-plays`` names action-space targets as
exact counts of legal plays and ``--opponent-mix`` names the units every
opponent fields. Each action-space target is a stratum, reported separately at
every step above, because a run under one target draws from a different
population than a run under another and a pooled prior would price a rule no
stratum spends. The suite then crosses the strata against the difficulty bins,
one quota per cell, which is what lets difficulty and action-space size be
varied independently instead of together.

DIFFICULTY here is ``analysis``'s: the fraction of complete legal plays that
win, a win being ``llm_score > human_score``. ``self-check`` runs this module's
counter and ``analysis.analyze_puzzle`` over the shipped suite and requires them
to agree, which is what says the two are the same measurement. It also requires
every shipped puzzle to field the placements its file lists, and fires on
fixtures of its own every guard against a puzzle being measured, or read back
later, as something its file does not describe: one per way a listed placement
can fail to reach the board, one per way a whole puzzle can fail to reach a
measurement, and one per way a written landscape can stop describing what a
reader of it would compute. It writes a suite of its own besides, and requires
the stamp on it to name every argument the study resolved, in a form the parser
reads back as itself.

EVERY SECONDS FIGURE IS WALL CLOCK on whatever machine and load the run met.
``study`` re-enumerates one puzzle several times and prints how far apart those
runs came out before it prints any other timing, so the spread is on the page
next to the numbers it applies to. Enumeration counts are what carries between
machines; seconds are this machine, this hour.

MOST OF THE SPREAD IN MICROSECONDS PER PLAY IS THE PUZZLES, NOT THE MACHINE.
Resolution cost is close to linear in how many steps a battle runs, and that
varies about fourfold across random boards. Fitted over the 89 puzzles of one
200-candidate prior small enough to trace: us per play = 2.6 + 5.7 * steps per
battle, r-squared 0.88, residual standard deviation 5.9 us per play. So a
puzzle that costs twice another is normally longer battles, and reading that
column as machine load is the mistake to avoid; the timing line is what sizes
the machine.
"""

import argparse
import contextlib
import copy
import io
import itertools
import json
import math
import random
import statistics
import sys
import tempfile
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import analysis
import engine
import prep

# Shop.create_randomized deals three distinct types, and all three shipped
# puzzles give the agent three. The shipped opponent shops are three (puzzles 1
# and 2) and four (puzzle 3), so the opponent draws its size from both.
AGENT_SHOP_SIZE = 3
OPPONENT_SHOP_SIZES = (3, 4)

# The shipped suite spends 3 to 6 gold a side, and 3 is Shop.STARTING_GOLD.
GOLD_BAND = (3, 4, 5, 6)

ALL_TYPES = (engine.A, engine.B, engine.C, engine.D)

OPPONENT_SQUARES = tuple(
    (row, col) for row in engine.OPPONENT_ROWS for col in range(engine.COLS)
)

# Half-width of the acceptance window: a candidate is accepted at target t when
# |difficulty - t| <= this. Fixed at 0.025, a 0.05-wide window, before the prior
# was measured.
DEFAULT_BAND = 0.025

DEFAULT_TARGETS = (0.05, 0.15, 0.30, 0.50, 0.70, 0.90)

# Bins the suite uses when the caller names neither the bin count nor the edges.
DEFAULT_SUITE_BINS = 6

# Resamples behind a forecast, and re-enumerations of one puzzle behind the
# timing spread. Both are cheap next to the prior they read.
BOOTSTRAP_TRIALS = 2000
TIMING_REPEATS = 3


# --- What a candidate is built to satisfy ---


@lru_cache(maxsize=None)
def action_space_table():
    """Every action-space size the agent can be dealt, and what deals it.

    The agent's action space is settled by its shop and its gold alone:
    ``prep.enumerate_plays`` walks the agent's own squares and reads nothing
    about the opponent, so the number of legal plays is a property a puzzle can
    be built to hit rather than one it has to be measured for. This is the whole
    table of what is hittable, keyed by play count and holding the ``(shop,
    gold)`` pairs that give it.

    Counted by walking the enumeration, the same way ``prep.count_plays`` does,
    because a formula over gold and squares would be a second implementation of
    the rule that decides what a play is. The whole table costs a couple of
    seconds and is built once per process.
    """
    table = {}
    for shop in itertools.combinations(ALL_TYPES, AGENT_SHOP_SIZE):
        for gold in GOLD_BAND:
            probe = prep.Puzzle(
                id="probe",
                difficulty=1,
                llm_shop=shop,
                llm_gold=gold,
                opponent_shop=(engine.A,),
                opponent_gold=0,
                opponent_placements=(),
            )
            table.setdefault(prep.count_plays(probe), []).append((shop, gold))
    return {plays: tuple(options) for plays, options in sorted(table.items())}


def parse_plays(text):
    """Action-space targets named on the command line, as exact play counts.

    Refuses a count no shop and gold produces, and names the ones that exist:
    the reachable set is small and fixed by the game's unit costs and its board,
    so a target off it is a typo, and the run it would produce is a long cap
    that fills nothing.
    """
    table = action_space_table()
    targets = []
    for part in text.split(","):
        plays = int(part)
        if plays not in table:
            raise argparse.ArgumentTypeError(
                "no shop and gold gives the agent %d legal plays; the reachable "
                "counts are %s" % (plays, ", ".join(str(key) for key in table))
            )
        if plays in targets:
            raise argparse.ArgumentTypeError("%d named twice" % plays)
        targets.append(plays)
    return tuple(targets)


def parse_mix(text):
    """The units every generated opponent fields, as a multiset of type labels.

    Sorted on the way in, so two spellings of one mix are one recorded stamp and
    read back through the parser as themselves. Refuses a mix no opponent can be
    dealt: more units than it has squares, a cost above the top of the gold
    band, or a label that is not a unit type.
    """
    labels = [part.strip() for part in text.split(",") if part.strip()]
    if not labels:
        raise argparse.ArgumentTypeError("a mix names at least one unit: %r" % text)
    if len(labels) > len(OPPONENT_SQUARES):
        raise argparse.ArgumentTypeError(
            "the opponent has %d squares and this mix fields %d units: %s"
            % (len(OPPONENT_SQUARES), len(labels), text)
        )
    try:
        types = [engine.label_to_type(label) for label in labels]
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    cost = sum(engine.UNIT_COSTS[unit_type] for unit_type in types)
    if cost > max(GOLD_BAND):
        raise argparse.ArgumentTypeError(
            "this mix costs %d and the opponent is dealt at most %d gold: %s"
            % (cost, max(GOLD_BAND), text)
        )
    return tuple(sorted(engine.TYPE_LABELS[unit_type] for unit_type in types))


@lru_cache(maxsize=None)
def mix_shops(mix):
    """The opponent shops a queue fielding ``mix`` can be dealt.

    Every shop the generator deals is a legal one, so this is the shops of a
    size ``OPPONENT_SHOP_SIZES`` allows that hold every type the mix names. A
    mix naming all four types therefore forces the four-type shop, which is a
    real narrowing of the draw and not a bug: a shop is what makes a placement
    affordable, and a unit the shop does not carry is a unit the opponent is
    refused.
    """
    needed = set(mix)
    return tuple(
        shop
        for size in OPPONENT_SHOP_SIZES
        for shop in itertools.combinations(ALL_TYPES, size)
        if needed <= set(shop)
    )


@dataclass(frozen=True)
class Structure:
    """What a candidate is built to satisfy, as against what it is measured for.

    ``plays`` is the size of the agent's action space, as an exact count of
    complete legal plays, and ``mix`` is the tuple of unit types the opponent
    fields. Either left None is that half of the puzzle drawn the way it was
    before any constraint existed, so the unconstrained structure reproduces the
    generator exactly as it was.
    """

    plays: int = None
    mix: tuple = None

    @property
    def label(self):
        return "action space %s, opponent %s" % (
            "%d plays" % self.plays if self.plays is not None else "unconstrained",
            "/".join(engine.TYPE_LABELS[t] for t in self.mix)
            if self.mix is not None
            else "unconstrained",
        )


UNCONSTRAINED = Structure()


def structures(args):
    """The strata a study draws from: one per action-space target, or one.

    The mix is the same in every stratum, because holding it steady across the
    whole suite is the point of naming it; the action-space target is what
    separates one stratum from the next.
    """
    mix = (
        None
        if args.opponent_mix is None
        else tuple(engine.label_to_type(label) for label in args.opponent_mix)
    )
    if args.suite_plays is None:
        return (Structure(None, mix),)
    return tuple(Structure(plays, mix) for plays in args.suite_plays)


# --- Generating one puzzle ---


def _random_queue(rng, shop, gold):
    """A placement queue the scripted opponent can afford and fully place.

    Every placement lands by construction: squares are distinct and on the
    opponent's own rows, every type is in its shop, and a type is queued only
    while the running total still leaves it affordable, so none is refused and
    the opponent is never marked done with entries left. This matters because
    the game consumes a queued placement before testing whether it can be made,
    so an over-budget queue silently loses units and yields a puzzle harder than
    it reads as. ``draw`` asserts the property rather than trusting this
    paragraph.
    """
    squares = list(OPPONENT_SQUARES)
    rng.shuffle(squares)
    queue = []
    for pos in squares[: rng.randint(1, len(squares))]:
        affordable = [t for t in shop if engine.UNIT_COSTS[t] <= gold]
        if not affordable:
            break
        unit_type = rng.choice(affordable)
        gold -= engine.UNIT_COSTS[unit_type]
        queue.append(prep.Placement(unit_type, pos))
    return tuple(queue)


def _mix_queue(rng, mix):
    """A queue fielding exactly ``mix``, on distinct squares, in a random order.

    Lands in full for the same reason ``_random_queue`` does, one step earlier:
    the gold it is dealt with is never below what the mix costs, so no entry is
    refused and none is left unconsumed, and the squares are distinct and the
    opponent's own. ``draw`` asserts the property rather than trusting this
    paragraph.

    What is left free is the whole of the board: which squares the units take
    and in what order they are placed. That is the only thing a constrained
    draw can vary, and it is what difficulty is reject-sampled over.
    """
    order = list(mix)
    rng.shuffle(order)
    squares = rng.sample(OPPONENT_SQUARES, len(order))
    return tuple(
        prep.Placement(unit_type, pos) for unit_type, pos in zip(order, squares)
    )


def random_puzzle(rng, puzzle_id, structure=UNCONSTRAINED):
    """One random legal puzzle inside ``structure``. ``difficulty`` is a
    placeholder here; the value the loader reads is set per puzzle by
    ``puzzle_json`` when a suite is written.

    Every draw is a statement here rather than an argument, so the order the
    seed is consumed in is the order it is read in and a seed reproduces the
    same puzzle. A constrained half draws from a narrower set in the same place
    the unconstrained half draws from the full one, so the two paths consume the
    seed at the same points and an unconstrained run is the run it always was.
    """
    if structure.mix is None:
        opponent_shop = tuple(rng.sample(ALL_TYPES, rng.choice(OPPONENT_SHOP_SIZES)))
        opponent_gold = rng.choice(GOLD_BAND)
    else:
        # A mix is dealt a shop that carries every type in it and gold that
        # covers it, which is what makes the queue below land in full.
        cost = sum(engine.UNIT_COSTS[unit_type] for unit_type in structure.mix)
        opponent_shop = rng.choice(mix_shops(structure.mix))
        opponent_gold = rng.choice([gold for gold in GOLD_BAND if gold >= cost])
    if structure.plays is None:
        llm_shop = tuple(rng.sample(ALL_TYPES, AGENT_SHOP_SIZE))
        llm_gold = rng.choice(GOLD_BAND)
    else:
        llm_shop, llm_gold = rng.choice(action_space_table()[structure.plays])
    queue = (
        _random_queue(rng, opponent_shop, opponent_gold)
        if structure.mix is None
        else _mix_queue(rng, structure.mix)
    )
    return prep.Puzzle(
        id=puzzle_id,
        difficulty=1,
        llm_shop=llm_shop,
        llm_gold=llm_gold,
        opponent_shop=opponent_shop,
        opponent_gold=opponent_gold,
        opponent_placements=queue,
    )


# --- Evaluating one candidate ---


@dataclass(frozen=True)
class Candidate:
    """A random puzzle and the enumeration that measured its difficulty.

    The play lengths are summed and bracketed during that same enumeration
    rather than recovered later. A call budget is built from how many placements
    an attempt takes, so something has to read it, and reading it afterwards
    means walking every play of every accepted puzzle a second time, which on a
    half-million-play puzzle costs as much as measuring the difficulty did.
    """

    puzzle: prep.Puzzle
    play_count: int
    win_count: int
    placement_count: int
    shortest_play: int
    longest_play: int
    seconds: float

    @property
    def difficulty(self):
        return self.win_count / self.play_count

    @property
    def mean_play_length(self):
        return self.placement_count / self.play_count


def evaluate(puzzle):
    """Enumerate every complete legal play and count the winning ones.

    The same quantity ``analysis.analyze_puzzle`` reports as ``difficulty``,
    computed without the prefix landscape because reject sampling reads only the
    win fraction and the landscape of a 500,000-play puzzle is millions of keys.
    ``self-check`` is what holds the two to the same answer.

    This measures whatever puzzle it is handed, including one whose queue does
    not land: the win fraction is a fact about the units a puzzle actually
    fields, not about the ones it lists. ``draw`` asserts the stronger property
    for generated puzzles, and ``analysis.analyze_puzzle`` holds every puzzle it
    builds a landscape for.
    """
    play_count = 0
    win_count = 0
    placement_count = 0
    shortest = None
    longest = None
    start = perf_counter()
    for play in prep.enumerate_plays(puzzle):
        result = engine.run_battle(prep.build_board(puzzle, play))
        if result["aborted"]:
            raise ValueError(
                "battle did not finish for play %s of puzzle %s"
                % (analysis.encode_play(play), puzzle.id)
            )
        final = result["final"]
        length = len(play)
        play_count += 1
        placement_count += length
        shortest = length if shortest is None else min(shortest, length)
        longest = length if longest is None else max(longest, length)
        if final["llm_score"] > final["human_score"]:
            win_count += 1
    return Candidate(
        puzzle,
        play_count,
        win_count,
        placement_count,
        shortest,
        longest,
        perf_counter() - start,
    )


def draw(rng, puzzle_id, structure=UNCONSTRAINED):
    """A random puzzle, measured, with its queue held to landing in full.

    The check is a postcondition on the generator and not a rejection rule:
    ``_random_queue`` cannot build a queue that fails it, so nothing here
    resamples and a failure aborts generation. That is the intended behaviour.
    A generator that had started emitting puzzles harder than they read as would
    otherwise write them into a suite, and every difficulty measured from that
    suite would describe boards other than the ones its file states.
    """
    puzzle = random_puzzle(rng, puzzle_id, structure)
    prep.check_queue_lands(puzzle)
    return evaluate(puzzle)


def sample_candidates(rng, count, prefix, on_candidate=None, structure=UNCONSTRAINED):
    """Evaluate ``count`` random puzzles, reporting each as it lands."""
    candidates = []
    for index in range(count):
        candidate = draw(rng, "%s%d" % (prefix, index), structure)
        candidates.append(candidate)
        if on_candidate is not None:
            on_candidate(index, candidate)
    return candidates


# --- The suite ---


def bin_edges(low, high, count):
    """``count`` + 1 evenly spaced edges from ``low`` to ``high``."""
    width = (high - low) / count
    return [low + width * i for i in range(count)] + [high]


def parse_edges(text):
    """Bin edges named on the command line, as increasing difficulties.

    The other route into ``build_suite``. ``bin_edges`` spans whatever range the
    prior sample happened to cover, so it cannot be asked for a band that sample
    did not reach, and it spaces the bins evenly, so it cannot be asked for a
    band whose interesting structure is not evenly spread. This route takes the
    edges as given and does neither.

    Refuses a list that names no bin, and an edge outside 0 to 1, since
    difficulty is a fraction of plays and no puzzle can fall there. It does not
    and cannot refuse a bin no puzzle exists in: whether a bin is reachable is
    what the run measures, and ``report_suite`` reports it unfilled.
    """
    edges = [float(part) for part in text.split(",")]
    if len(edges) < 2:
        raise argparse.ArgumentTypeError("two edges make one bin; got %d" % len(edges))
    if edges[0] < 0.0 or edges[-1] > 1.0:
        raise argparse.ArgumentTypeError(
            "difficulty is a fraction of plays, so edges lie in 0 to 1: %s" % text
        )
    for low, high in zip(edges, edges[1:]):
        if high <= low:
            raise argparse.ArgumentTypeError("edges must increase: %s" % text)
    return edges


def bin_index(edges, difficulty):
    """Which bin a difficulty falls in, or None if it is outside the range.

    The top bin owns its upper edge, so the puzzle that defined the range is in
    the range.
    """
    if difficulty < edges[0] or difficulty > edges[-1]:
        return None
    for index in range(len(edges) - 2, -1, -1):
        if difficulty >= edges[index]:
            return index
    return None


def bin_quotas(size, bins):
    """``size`` puzzles spread over ``bins`` bins, remainder to the low bins."""
    base, extra = divmod(size, bins)
    return [base + (1 if index < extra else 0) for index in range(bins)]


def is_degenerate(difficulty):
    """True when every complete play wins, or none does.

    Such a puzzle is decided before the agent chooses anything, so it measures
    nothing about an agent and does not belong in a suite however neatly it
    fills an end bin. ``report_prior`` counts them because their share is a
    fact about the generator; the suite rejects them.
    """
    return difficulty in (0.0, 1.0)


def suite_classifier(edges):
    """The suite's acceptance rule: the bin a candidate may fill, or None.

    ``build_suite`` and the forecast both go through this, so a forecast cannot
    price a rule the run does not use.
    """

    def classify(difficulty):
        if is_degenerate(difficulty):
            return None
        return bin_index(edges, difficulty)

    return classify


def target_classifier(targets, band):
    """The band rule: the target a candidate is within ``band`` of, or None.

    The acceptance table and the forecast both go through this, so the rate the
    table reports is the rate the forecast spends. First match wins, which
    matters only if a caller passes targets closer together than ``2 * band``.
    """

    def classify(difficulty):
        for index, target in enumerate(targets):
            if abs(difficulty - target) <= band:
                return index
        return None

    return classify


@dataclass
class SuiteRun:
    """What filling the cells cost, whether or not they all filled.

    A cell is one structure crossed with one difficulty bin, so ``quotas``,
    ``accepted`` and ``filled_at`` are all indexed structure first and bin
    second, and ``attempts`` is per structure because what a stratum costs is
    the thing a crossed run most needs to be able to read separately.
    """

    structures: tuple
    edges: list
    quotas: list
    accepted: list
    filled_at: list
    attempts: list
    degenerate: int
    seconds: float

    @property
    def accepted_count(self):
        return sum(len(bucket) for row in self.accepted for bucket in row)

    @property
    def total_attempts(self):
        return sum(self.attempts)

    def short_cells(self):
        """The cells that did not reach their quota, as (structure, bin)."""
        return [
            (outer, inner)
            for outer, row in enumerate(self.quotas)
            for inner, quota in enumerate(row)
            if len(self.accepted[outer][inner]) < quota
        ]


def build_suite(rng, structures, edges, quotas, cap, on_candidate=None):
    """Reject-sample until every cell holds its quota or ``cap`` enumerations.

    A candidate is accepted into its own bin if that bin still has room, so a
    suite spanning a range costs far less than the same number of puzzles at one
    target. Those bins are much wider than the ``--band`` window the acceptance
    table measures, so what this run spends per accepted puzzle prices the bins
    and not that window. A degenerate candidate is rejected wherever it falls,
    which is what keeps the end bins from filling with puzzles the agent cannot
    affect. The cap is what stops an unreachable bin from running forever; the
    caller reports which cells were short.

    A candidate can only fill a cell of the structure it was drawn under,
    because its structure is built into it rather than measured off it. So the
    structures are drawn round robin among those still short, and the cap is
    spent across all of them: one expensive stratum cannot spend the whole cap
    before a cheap one has begun, and a stratum that has filled stops drawing.
    """
    classify = suite_classifier(edges)
    accepted = [[[] for _ in row] for row in quotas]
    filled_at = [[None] * len(row) for row in quotas]
    attempts = [0] * len(structures)
    degenerate = 0
    start = perf_counter()

    def still_short(outer):
        return any(
            len(bucket) < quota
            for bucket, quota in zip(accepted[outer], quotas[outer])
        )

    turn = 0
    while sum(attempts) < cap and any(
        still_short(outer) for outer in range(len(structures))
    ):
        while not still_short(turn % len(structures)):
            turn += 1
        outer = turn % len(structures)
        turn += 1
        candidate = draw(rng, "gen%d" % sum(attempts), structures[outer])
        attempts[outer] += 1
        if is_degenerate(candidate.difficulty):
            degenerate += 1
        index = classify(candidate.difficulty)
        taken = index is not None and len(accepted[outer][index]) < quotas[outer][index]
        if taken:
            accepted[outer][index].append(candidate)
            if len(accepted[outer][index]) == quotas[outer][index]:
                filled_at[outer][index] = attempts[outer]
        if on_candidate is not None:
            on_candidate(
                structures[outer],
                sum(attempts),
                candidate,
                index if taken else None,
            )
    return SuiteRun(
        tuple(structures),
        edges,
        quotas,
        accepted,
        filled_at,
        attempts,
        degenerate,
        perf_counter() - start,
    )


# --- The suite file ---


# The study options that describe the run, as against the three that say where
# it wrote its output and how loud it was on stderr. A suite file records these
# because re-running them is what reproduces it; ``--suite-out``,
# ``--record-out`` and ``--verbose`` change nothing about which puzzles a run
# produces. ``_stamp_complaints`` holds this split against the parser's own
# options, so a study option added later cannot go unrecorded unnoticed.
STUDY_PARAMETERS = (
    "seed",
    "sample",
    "band",
    "targets",
    "suite_size",
    "suite_bins",
    "suite_edges",
    "suite_plays",
    "opponent_mix",
    "suite_cap",
)
STUDY_OUTPUTS = ("suite_out", "record_out", "verbose")


def study_parameters(args):
    """The study's arguments, resolved, in the shape a suite file records them.

    Resolved rather than as typed, because an argument the run left to a default
    reproduces a different file the day that default moves, and what the run
    actually used is the recorded value. Every default but one is argparse's and
    arrives here already applied; the bin count's is a layer below it, in
    ``suite_bin_count``, so a run that named neither the count nor the edges is
    recorded with the count that run binned the prior at. The literal command
    line is kept beside this by ``study_provenance``, since the resolved set
    cannot recover it.
    """
    resolved = {}
    for name in STUDY_PARAMETERS:
        value = getattr(args, name)
        resolved[name] = list(value) if isinstance(value, (list, tuple)) else value
    if resolved["suite_edges"] is None:
        resolved["suite_bins"] = suite_bin_count(args)
    return resolved


def _parameter_token(value):
    """One recorded value as the text the parser reads it back from.

    ``repr`` for a number, so a float keeps every digit it was resolved at and
    an integer stays an integer; the value itself for a unit-type label, since
    a quoted label is not a label.
    """
    return value if isinstance(value, str) else repr(value)


def study_command(parameters):
    """Recorded parameters as the study arguments that would produce them again.

    The tokens follow the script path, so a recorded run is re-run as
    ``python3 -B oracle/generate.py`` plus these plus a ``--suite-out`` naming
    where the file should land this time. A parameter recorded as None was not
    named and is not named back: ``--suite-bins`` and ``--suite-edges`` exclude
    each other at the command line, so passing both refuses.
    """
    tokens = ["study"]
    for name in STUDY_PARAMETERS:
        value = parameters[name]
        if value is None:
            continue
        tokens.append("--" + name.replace("_", "-"))
        if isinstance(value, list):
            tokens.append(",".join(_parameter_token(part) for part in value))
        else:
            tokens.append(_parameter_token(value))
    return tokens


def study_provenance(args):
    """What produced a suite file: the arguments it resolved, and the line run.

    ``parameters`` is what regenerates the file. ``command`` is the argument
    list this process was given, which holds the output path and any tracing
    that the resolved set does not; it starts at the script path rather than at
    the interpreter, so it is re-run the way ``study_command`` says, behind a
    ``python3 -B``.

    Neither carries a clock reading, so a file regenerated from its own stamp
    differs from the one it came from only where the run genuinely differed:
    replay to a new path and the recorded ``--suite-out`` is the one thing that
    moves, and the puzzles are identical. A timestamp would make every
    regeneration differ and buy nothing this needs.
    """
    return {"command": list(sys.argv), "parameters": study_parameters(args)}


def puzzle_json(candidate, rank, tier):
    """One puzzle in puzzle_suite.json's shape, plus what it measured.

    ``difficulty`` is the puzzle's rank, unique across the file, because
    ``GameController._build_mini_puzzle_subset`` keeps the first scenario at
    each ``int(difficulty)`` and drops every later one. A field holding the bin
    tier repeats, so a mini ablation would run one puzzle per bin and say
    nothing about the rest. Ranks run easiest first, the same direction the
    tiers ran, so anything ordering ablation rows by the field still orders
    them from easiest.

    The bin is in ``tier`` and the win fraction in ``measured_difficulty``.
    Both are ignored by ``PuzzleLoader._parse_scenario`` and by
    ``prep.load_suite``, and grouping on ``tier`` recovers the bins the
    acceptance measurement used.
    """
    puzzle = candidate.puzzle
    return {
        "id": puzzle.id,
        "difficulty": rank,
        "tier": tier,
        "llm_shop": [engine.TYPE_LABELS[t] for t in puzzle.llm_shop],
        "llm_gold": puzzle.llm_gold,
        "opponent_shop": [engine.TYPE_LABELS[t] for t in puzzle.opponent_shop],
        "opponent_gold": puzzle.opponent_gold,
        "opponent_placements": [
            {
                "type": engine.TYPE_LABELS[placement.unit_type],
                "row": placement.pos[0],
                "col": placement.pos[1],
            }
            for placement in puzzle.opponent_placements
        ],
        "measured_difficulty": candidate.difficulty,
        "play_count": candidate.play_count,
        "win_count": candidate.win_count,
    }


def accepted_in_order(run):
    """The accepted candidates with their rank and tier, easiest first.

    Tier 1 is the bin where the most plays win. That inverts the bin order,
    because bin 0 is the fewest wins, and it has to: ``puzzle_runner.gd`` copies
    the loader's difficulty field into every ablation result row, so a number
    that fell as puzzles got harder would reverse every solve rate ordered by
    it. The win fraction ``analysis`` calls difficulty runs the other way, and
    this is the one place the two meet.

    Rank 1 is the easiest puzzle in the file and rank N the hardest. The order
    is the win fraction itself, across every cell at once rather than bin by
    bin, because a crossed run fills the same bin under several structures and
    ranking those by cell would put a puzzle of one structure above an easier
    puzzle of another. The bins partition the win fraction, so ranking by it
    still rises with tier, and the unique field the loader keeps still carries
    the same direction the tier does.
    """
    bins = len(run.edges) - 1
    ranked = sorted(
        (
            (bins - index, candidate)
            for row in run.accepted
            for index, bucket in enumerate(row)
            for candidate in bucket
        ),
        key=lambda pair: -pair[1].difficulty,
    )
    for rank, (tier, candidate) in enumerate(ranked, start=1):
        yield rank, tier, candidate


def suite_puzzles(run):
    """The accepted puzzles, ranked, in the shape a suite file lists them."""
    return [
        puzzle_json(candidate, rank, tier)
        for rank, tier, candidate in accepted_in_order(run)
    ]


def suite_json(run, provenance):
    """The accepted puzzles as a loadable suite, the bins behind them, and what
    would produce the file again.

    ``provenance`` is a top-level key beside ``bin_edges``, and every reader of
    a suite file passes over both: ``prep.load_suite`` and ``puzzle_loader.gd``
    read ``puzzles`` and nothing else out of the root, and
    ``analysis.recorded_counts`` reads the counts inside each puzzle.
    """
    return {
        "bin_edges": list(run.edges),
        "provenance": provenance,
        "puzzles": suite_puzzles(run),
    }


def write_suite(run, path, provenance):
    """Write the suite, stamped with what produced it, and read it back through
    the loader the game uses.

    ``prep.load_suite`` is the port of ``puzzle_loader.gd``, so a file it reads
    back as the puzzles it was written from is a file the game's loader accepts.
    Writing a suite the study cannot load is the failure this catches, and one
    comparison against the candidates in memory is cheap enough to always run.
    Going through ``puzzles`` rather than the kept list also holds the written
    file to being measurable: a puzzle it dropped, or an id it wrote twice,
    refuses here rather than in whatever stage reads the file next.
    """
    with open(path, "w") as handle:
        json.dump(suite_json(run, provenance), handle, indent=2)

    expected = tuple(
        replace(candidate.puzzle, difficulty=rank)
        for rank, _tier, candidate in accepted_in_order(run)
    )
    if prep.load_suite(path).puzzles() != expected:
        raise ValueError(
            "%s does not read back as the puzzles it was written from" % path
        )
    return len(expected)


# --- Reporting ---


def histogram(difficulties, width=0.05):
    """Counts per ``width``-wide bucket over the whole 0-to-1 difficulty axis.

    The axis is fixed rather than fitted to the sample, because an empty bucket
    is the finding: it says random sampling did not reach that difficulty. The
    top bucket owns 1.0, so a puzzle every play wins lands in 0.95-1.00.
    """
    bucket_count = round(1.0 / width)
    counts = [0] * bucket_count
    for difficulty in difficulties:
        counts[min(bucket_count - 1, int(difficulty / width))] += 1
    return [
        (index * width, (index + 1) * width, counts[index])
        for index in range(bucket_count)
    ]


def wilson_interval(successes, trials, z=1.96):
    """The 95% interval on a rate, by Wilson's score method.

    Wilson rather than successes over trials plus or minus a normal error
    because every count in the acceptance table is single digit, where the
    normal error runs below zero and a count of nothing reports an interval of
    zero width. Returns (low, high) on the rate.
    """
    if trials == 0:
        return (0.0, 1.0)
    centre = (successes + z * z / 2) / (trials + z * z)
    half = (
        z
        / (trials + z * z)
        * math.sqrt(successes * (trials - successes) / trials + z * z / 4)
    )
    return (max(0.0, centre - half), min(1.0, centre + half))


def enum_window(low, high):
    """An interval on a rate, read as enumerations per accepted puzzle.

    A rate interval whose low end is zero is an open one: the sample bounds how
    cheap a target can be and not how expensive.
    """
    if low <= 0.0:
        return "%.0f or more" % (1.0 / high) if high else "unbounded"
    return "%.0f to %.0f" % (1.0 / high, 1.0 / low)


def bootstrap_attempts(difficulties, classify, quotas, cap, rng, trials=BOOTSTRAP_TRIALS):
    """Enumerations to fill ``quotas``, resampled from the measured prior.

    Draws with replacement from difficulties already measured, so it prices an
    acceptance rule without enumerating anything new and carries the prior's
    sampling error and nothing else. Returns the sorted attempt counts and how
    many trials hit ``cap`` unfilled; a censored trial is counted separately
    rather than averaged in, because it says a bucket may be rarer than this
    sample can price at all.
    """
    results = []
    censored = 0
    for _ in range(trials):
        counts = [0] * len(quotas)
        attempts = 0
        while attempts < cap and any(
            count < quota for count, quota in zip(counts, quotas)
        ):
            attempts += 1
            index = classify(rng.choice(difficulties))
            if index is not None and counts[index] < quotas[index]:
                counts[index] += 1
        if any(count < quota for count, quota in zip(counts, quotas)):
            censored += 1
        results.append(attempts)
    return sorted(results), censored


def timing_spread(candidates, repeats=TIMING_REPEATS):
    """The cheapest measured candidate re-enumerated, in microseconds per play.

    Identical work every time, so what separates the values is the machine and
    not the puzzle. The first is what that candidate cost when the sample
    reached it and the rest are after the sample finished, so the spread covers
    the run rather than a few adjacent seconds of it. It is the error bar on
    every other seconds figure the study prints, which is why the study prints
    it first.
    """
    reference = min(candidates, key=lambda c: c.play_count)
    values = [reference.seconds / reference.play_count * 1e6]
    for _ in range(repeats):
        repeat = evaluate(reference.puzzle)
        values.append(repeat.seconds / repeat.play_count * 1e6)
    return values


def quantile(sorted_values, fraction):
    """Nearest-rank quantile, so every value reported is one that was measured."""
    rank = min(len(sorted_values) - 1, int(fraction * len(sorted_values)))
    return sorted_values[rank]


def report_prior(candidates):
    difficulties = sorted(c.difficulty for c in candidates)
    plays = sum(c.play_count for c in candidates)
    seconds = sum(c.seconds for c in candidates)

    print("PRIOR: %d random puzzles, every one enumerated" % len(candidates))
    print(
        "  %d plays resolved in %.1f s, %.1f us per play"
        % (plays, seconds, seconds / plays * 1e6)
    )
    print(
        "  plays per puzzle: min %d, median %d, max %d"
        % (
            min(c.play_count for c in candidates),
            int(statistics.median(c.play_count for c in candidates)),
            max(c.play_count for c in candidates),
        )
    )
    print(
        "  seconds per puzzle: min %.2f, mean %.2f, max %.2f"
        % (
            min(c.seconds for c in candidates),
            seconds / len(candidates),
            max(c.seconds for c in candidates),
        )
    )
    per_play = sorted(c.seconds / c.play_count * 1e6 for c in candidates)
    print(
        "  us per play by puzzle: min %.1f, p25 %.1f, median %.1f, p75 %.1f, max %.1f"
        % (
            per_play[0],
            quantile(per_play, 0.25),
            quantile(per_play, 0.50),
            quantile(per_play, 0.75),
            per_play[-1],
        )
    )
    print(
        "  difficulty: min %.4f, p25 %.4f, median %.4f, p75 %.4f, p95 %.4f, max %.4f"
        % (
            difficulties[0],
            quantile(difficulties, 0.25),
            quantile(difficulties, 0.50),
            quantile(difficulties, 0.75),
            quantile(difficulties, 0.95),
            difficulties[-1],
        )
    )
    print(
        "  degenerate, so rejected by the suite: exactly 0 (no play wins) %d of "
        "%d, exactly 1 (every play wins) %d of %d"
        % (
            sum(1 for value in difficulties if value == 0.0),
            len(difficulties),
            sum(1 for value in difficulties if value == 1.0),
            len(difficulties),
        )
    )
    print("  distribution, 0.05 wide buckets:")
    for low, high, count in histogram(difficulties):
        print(
            "    %.2f-%.2f  %4d  %5.1f%%  %s"
            % (low, high, count, 100.0 * count / len(candidates), "#" * count)
        )
    return difficulties


def report_targets(candidates, targets, band):
    """The acceptance table, every figure carrying the interval it is good to."""
    seconds = sum(c.seconds for c in candidates)
    attempts = len(candidates)
    classify = target_classifier(targets, band)
    accepted = [0] * len(targets)
    for candidate in candidates:
        index = classify(candidate.difficulty)
        if index is not None:
            accepted[index] += 1

    print()
    print(
        "ACCEPTANCE, band +/-%.3f, measured over the %d enumerated candidates above"
        % (band, attempts)
    )
    print("  target  accepted  rate      enum/accept  95% interval   s/accept*")
    intervals = []
    for target, count in zip(targets, accepted):
        low, high = wilson_interval(count, attempts)
        intervals.append((low, high))
        if count:
            print(
                "  %.2f    %8d  %7.4f  %11.1f  %-13s  %8.1f"
                % (
                    target,
                    count,
                    count / attempts,
                    attempts / count,
                    enum_window(low, high),
                    seconds / count,
                )
            )
        else:
            print(
                "  %.2f    %8d  %7.4f  %11s  %-13s  %8s"
                % (target, 0, 0.0, "none seen", enum_window(low, high), "-")
            )
    print(
        "  * wall clock on this machine, carrying the spread the timing line "
        "measured; the enumeration counts are the figures that travel"
    )

    separated = [
        "%.2f and %.2f" % (targets[i], targets[j])
        for i in range(len(targets))
        for j in range(i + 1, len(targets))
        if intervals[i][1] < intervals[j][0] or intervals[j][1] < intervals[i][0]
    ]
    if separated:
        print(
            "  separated by more than sampling error: %s. Every other pair "
            "overlaps." % ", ".join(separated)
        )
    else:
        low = min(pair[0] for pair in intervals)
        high = max(pair[1] for pair in intervals)
        print(
            "  every pair of intervals overlaps, so this sample does not rank the "
            "targets: one figure of %s enumerations per accepted puzzle covers all "
            "%d, and the column's ordering is noise."
            % (enum_window(low, high), len(targets))
        )


def report_forecast(difficulties, edges, quotas, targets, band, seconds_each, seed):
    """Price both acceptance rules off the same measured difficulties."""
    rng = random.Random(seed)
    size = sum(quotas)
    cap = 100 * size
    rules = (
        (
            "%d bins over %.4f-%.4f" % (len(quotas), edges[0], edges[-1]),
            suite_classifier(edges),
            quotas,
        ),
        (
            "%d targets at band +/-%.3f" % (len(targets), band),
            target_classifier(targets, band),
            bin_quotas(size, len(targets)),
        ),
    )

    print()
    print(
        "FORECAST: %d puzzles under each rule, %d resamples of the %d measured "
        "difficulties" % (size, BOOTSTRAP_TRIALS, len(difficulties))
    )
    print(
        "  %-28s  %6s  %-13s  %s" % ("rule", "median", "p05-p95", "minutes*")
    )
    for label, classify, rule_quotas in rules:
        results, censored = bootstrap_attempts(
            difficulties, classify, rule_quotas, cap, rng
        )
        if censored == BOOTSTRAP_TRIALS:
            print(
                "  %-28s  more than %d in every resample: some bucket is rarer "
                "than this sample can price" % (label, cap)
            )
            continue
        low = quantile(results, 0.05)
        high = quantile(results, 0.95)
        print(
            "  %-28s  %6d  %6d-%-6d  %s"
            % (
                label,
                quantile(results, 0.50),
                low,
                high,
                "%.0f-%.0f" % (low * seconds_each / 60.0, high * seconds_each / 60.0),
            )
        )
        if censored:
            print(
                "    %d of %d resamples hit the %d-enumeration cap, so every "
                "quantile above the %.0fth is a floor"
                % (
                    censored,
                    BOOTSTRAP_TRIALS,
                    cap,
                    100.0 * (1.0 - censored / BOOTSTRAP_TRIALS),
                )
            )
    print(
        "  * at %.1f s per enumeration, this run's mean, so the timing spread above "
        "is the error on the minutes and not on the counts" % seconds_each
    )
    print(
        "  the two rules are not comparable and neither number checks the other: "
        "the bins are wider than the band, and a wider rule accepts more."
    )


def report_timing(values):
    print(
        "TIMING: one puzzle enumerated %d times, identical work each time, the "
        "first during the sample and the rest after it: %s us per play, %.2fx "
        "from the fastest to the slowest."
        % (
            len(values),
            ", ".join("%.1f" % value for value in values),
            max(values) / min(values),
        )
    )
    print(
        "  That ratio is what identical work varied by across this run. Every "
        "seconds figure below is this machine at this load, and none of them is "
        "worth more digits than that ratio leaves."
    )
    print()


def report_suite(run):
    bins = len(run.edges) - 1
    print()
    print(
        "SUITE: %d bins spanning %.4f to %.4f crossed against %d structure(s), "
        "degenerate puzzles rejected"
        % (bins, run.edges[0], run.edges[-1], len(run.structures))
    )
    print(
        "  %d of %d puzzles accepted from %d enumerations in %.1f s"
        % (
            run.accepted_count,
            sum(sum(row) for row in run.quotas),
            run.total_attempts,
            run.seconds,
        )
    )
    for outer, structure in enumerate(run.structures):
        print("  %s: %d enumerations" % (structure.label, run.attempts[outer]))
        print("    bin              tier  quota  filled  full at  difficulties")
        for index in range(bins):
            values = sorted(c.difficulty for c in run.accepted[outer][index])
            print(
                "    %.4f-%.4f  %4d  %5d  %6d  %7s  %s"
                % (
                    run.edges[index],
                    run.edges[index + 1],
                    bins - index,
                    run.quotas[outer][index],
                    len(values),
                    run.filled_at[outer][index] or "-",
                    " ".join("%.4f" % value for value in values) or "-",
                )
            )
    print(
        "  %d of the %d enumerations were degenerate and rejected wherever they fell"
        % (run.degenerate, run.total_attempts)
    )
    if run.accepted_count:
        print(
            "  %.1f enumerations and %.1f s per accepted puzzle, under the bin rule "
            "and not the band the acceptance table measures"
            % (
                run.total_attempts / run.accepted_count,
                run.seconds / run.accepted_count,
            )
        )
    short = run.short_cells()
    if short:
        print(
            "  UNFILLED after the %d-enumeration cap: %s"
            % (
                run.total_attempts,
                ", ".join(
                    "%s %.4f-%.4f (%d of %d)"
                    % (
                        run.structures[outer].label,
                        run.edges[index],
                        run.edges[index + 1],
                        len(run.accepted[outer][index]),
                        run.quotas[outer][index],
                    )
                    for outer, index in short
                ),
            )
        )
    return short


def column_floors(column):
    """The smallest one-sided p a predictor column can reach, against two outcomes.

    ``1/n!`` is the floor of the test only where nothing ties, and a suite is
    built knowing its predictor columns and not its outcome column, so the
    honest figure is a pair: what the column reaches against an outcome whose
    every value is distinct, and what it reaches against a balanced win-or-not
    split, which is the coarsest column an arm's wins can come back as. Ties in
    the predictor raise both, which is how a suite with few distinct play counts
    caps its own action-space test.

    Measured by ``outcomes.permutation_test``, on the column itself, so it is the
    floor of the test that will actually be run rather than a formula standing in
    for it. ``outcomes`` imports this module, so the import is made here.
    """
    import outcomes

    half = len(column) // 2
    return (
        outcomes.permutation_test(column, list(range(len(column))), +1).floor,
        outcomes.permutation_test(
            column, [1] * half + [0] * (len(column) - half), +1
        ).floor,
    )


def report_crossing(run):
    """What the accepted suite holds steady and what it varies, measured on it.

    Three properties decide whether a null result about difficulty is about
    difficulty. Difficulty and the size of the action space have to vary
    independently, or a suite cannot tell a difficulty measure that fails to
    predict from an action space that dominates. The opponent's unit mix has to
    be the same puzzle to puzzle, or "harder" and "more of one unit type" are
    the same axis. And the suite has to hold enough puzzles that the exact
    permutation test has somewhere below the observed pairing to go.

    All three are measured here rather than asserted, and the rank correlation
    is ``outcomes.spearman``, the one the study's own test will compute on this
    suite, midranks and all. ``outcomes`` imports this module, so the import is
    made here, at the one call, rather than at the top of the file.

    Difficulty is the win fraction and not the rank the file records, so the
    sign is the one ``analysis`` uses. The rank is a strictly decreasing
    function of it, so the magnitude is the same either way and the sign flips.
    """
    import outcomes

    accepted = [candidate for _rank, _tier, candidate in accepted_in_order(run)]
    print()
    print("CROSSING: what the %d accepted puzzles hold steady" % len(accepted))
    if not accepted:
        print("  nothing was accepted, so there is nothing to describe")
        return

    plays = [c.play_count for c in accepted]
    difficulties = [c.difficulty for c in accepted]
    rho = outcomes.spearman(difficulties, plays)
    orderings = math.factorial(len(accepted))
    print(
        "  difficulty against legal plays: spearman %s over %d puzzles, "
        "%d distinct play counts"
        % ("none, one column is constant" if rho is None else "%+.3f" % rho,
           len(accepted), len(set(plays)))
    )
    if orderings > outcomes.EXACT_LIMIT:
        print(
            "  %d puzzles is %d pairings, past the %d outcomes.permutation_test "
            "enumerates: it will refuse this suite rather than sample a p, so "
            "neither column below can be tested at all"
            % (len(accepted), orderings, outcomes.EXACT_LIMIT)
        )
    else:
        print(
            "  smallest one-sided p each column can reach, measured on the column "
            "itself; 1/%d! = %.6f is what an untied column would give"
            % (len(accepted), 1.0 / orderings)
        )
        print("    column      outcome all distinct  outcome a %d/%d win split"
              % (len(accepted) // 2, len(accepted) - len(accepted) // 2))
        for name, column in (("difficulty", difficulties), ("legal plays", plays)):
            distinct, split = column_floors(column)
            print("    %-10s  %18.6f  %21.6f" % (name, distinct, split))
        print(
            "    the legal plays row is the cap on the action-space test whatever "
            "the effect size, because the suite holds %d play counts over %d "
            "puzzles and tied predictors raise the floor the same way tied "
            "outcomes do" % (len(set(plays)), len(accepted))
        )

    counts = {label: 0 for label in engine.TYPE_LABELS.values()}
    shares = {label: [] for label in counts}
    for candidate in accepted:
        queue = candidate.puzzle.opponent_placements
        for label in counts:
            held = sum(
                1
                for placement in queue
                if engine.TYPE_LABELS[placement.unit_type] == label
            )
            counts[label] += held
            shares[label].append(held / len(queue))
    total = sum(counts.values())
    print("  opponent units: %d over %d puzzles" % (total, len(accepted)))
    print("    type  suite share  per-puzzle share, min to max")
    for label in sorted(counts):
        print(
            "    %-4s  %10.3f  %.3f to %.3f"
            % (label, counts[label] / total, min(shares[label]), max(shares[label]))
        )

    print(
        "  placements per attempt: %.3f over the suite, taken over every legal "
        "play; no attempt is shorter than %d or longer than %d"
        % (
            statistics.mean(c.mean_play_length for c in accepted),
            min(c.shortest_play for c in accepted),
            max(c.longest_play for c in accepted),
        )
    )
    print(
        "    a mean over the plays and not over what an agent picks, which is the "
        "estimate available before an arm runs. It is what a call budget is built "
        "from, at whatever rate of model calls per placement an arm turns out to "
        "spend."
    )


# --- CLI ---


def _record(priors, run, timing, args):
    return {
        "seed": args.seed,
        "band": args.band,
        "targets": list(args.targets),
        "timing_us_per_play": timing,
        "prior": [
            {
                "structure": structure.label,
                "puzzle": puzzle_json(candidate, 1, 1),
                "difficulty": candidate.difficulty,
                "play_count": candidate.play_count,
                "win_count": candidate.win_count,
                "seconds": candidate.seconds,
            }
            for structure, prior in priors
            for candidate in prior
        ],
        "suite": {
            "structures": [structure.label for structure in run.structures],
            "edges": run.edges,
            "quotas": run.quotas,
            "attempts": run.attempts,
            "degenerate": run.degenerate,
            "seconds": run.seconds,
            "puzzles": suite_puzzles(run),
        },
    }


def suite_bin_count(args):
    """The bins a run fills when it was not handed the edges outright.

    argparse leaves ``--suite-bins`` at None, so the count a run used is settled
    here rather than at the command line, and this is the value a suite file
    records for it.
    """
    return args.suite_bins or DEFAULT_SUITE_BINS


def suite_edges(args, difficulties):
    """The bins this run will fill: the caller's edges, or the prior's range.

    The two rules are mutually exclusive at the command line, so this chooses
    between them and never reconciles them. Where neither is named the prior's
    own observed range is the fallback, which is what every run before this
    option did.
    """
    if args.suite_edges is not None:
        return args.suite_edges
    return bin_edges(difficulties[0], difficulties[-1], suite_bin_count(args))


def _study(args):
    rng = random.Random(args.seed)
    strata = structures(args)
    crossed = strata != (UNCONSTRAINED,)

    def trace(index, candidate):
        print(
            "  candidate %d/%d  difficulty %.4f  %d plays  %.2f s"
            % (index + 1, args.sample, candidate.difficulty, candidate.play_count, candidate.seconds),
            file=sys.stderr,
        )

    priors = [
        (
            structure,
            sample_candidates(
                rng,
                args.sample,
                "rand" if not crossed else "rand%d-" % outer,
                trace if args.verbose else None,
                structure,
            ),
        )
        for outer, structure in enumerate(strata)
    ]
    pooled = [candidate for _structure, prior in priors for candidate in prior]
    timing = timing_spread(pooled)
    report_timing(timing)

    # The bins are the same in every stratum, so where the caller did not name
    # them they come off the pooled prior: a stratum is a narrower population
    # and edges fitted to one of them would leave the others unfillable at an
    # end. Where the caller named them this reads nothing.
    edges = suite_edges(args, sorted(c.difficulty for c in pooled))
    per_structure = bin_quotas(args.suite_size, len(strata))
    quotas = [bin_quotas(size, len(edges) - 1) for size in per_structure]

    for outer, (structure, prior) in enumerate(priors):
        if crossed:
            print()
            print("=== %s ===" % structure.label)
        difficulties = report_prior(prior)
        report_targets(prior, args.targets, args.band)
        report_forecast(
            difficulties,
            edges,
            quotas[outer],
            args.targets,
            args.band,
            sum(c.seconds for c in prior) / len(prior),
            args.seed + 2,
        )

    def suite_trace(structure, attempts, candidate, index):
        # Always the accepted ones, because a band the prior barely reached
        # spends most of a long cap between them, and a run that prints nothing
        # for an hour reads as a stall rather than as the cost it is.
        if index is None and not args.verbose:
            return
        print(
            "  attempt %d  %s  difficulty %.4f  %.2f s  %s"
            % (
                attempts,
                structure.label,
                candidate.difficulty,
                candidate.seconds,
                "-> bin %d" % index if index is not None else "rejected",
            ),
            file=sys.stderr,
        )

    run = build_suite(
        random.Random(args.seed + 1),
        strata,
        edges,
        quotas,
        args.suite_cap,
        suite_trace,
    )
    short = report_suite(run)
    report_crossing(run)

    if args.suite_out and not run.accepted_count:
        # Every bin came up short, which the report above has already said. A
        # file listing no puzzles is not a suite and prep refuses to load one,
        # so writing it would leave a path that reads as a suite and is not one.
        print(
            "  no candidate landed in any bin, so %s was not written"
            % args.suite_out
        )
    elif args.suite_out:
        written = write_suite(run, args.suite_out, study_provenance(args))
        print(
            "  wrote %d puzzles to %s, reloaded through prep.load_suite"
            % (written, args.suite_out)
        )
        print(
            "  each puzzle's difficulty field is its rank, 1 (easiest) to %d, so no "
            "mode of the game drops one; its bin is in tier and its win fraction in "
            "measured_difficulty" % written
        )
    if args.record_out:
        with open(args.record_out, "w") as handle:
            json.dump(_record(priors, run, timing, args), handle, indent=1)
        print("  wrote the measurements to %s" % args.record_out)

    return 1 if short else 0


def _unlanded_fixtures():
    """Puzzles that field fewer units than they list, one per way.

    A placement the loader kept goes missing at run time two ways: the opponent
    consumes it and refuses it, or the opponent is marked done and never
    consumes it. ``prep.check_queue_lands`` must fire on each, and a guard that
    has never been seen to fire is not known to work. The third way, a
    placement the loader threw away, is a loss against the file rather than
    against the queue, so it is one of ``_unmeasurable_fixtures`` instead.

    These are fixtures rather than perturbed copies of the suite under test,
    because whether the guard works is a fact about the guard. Starving a copy
    of each shipped puzzle tied the check to the suite's shape and failed a
    legal suite whose opponent queues nothing, which has nothing to starve.

    Yields ``(what is lost, puzzle)``.
    """
    # 3 gold against a queue costing 5. The second D is popped with 1 gold left
    # and refused, and the A behind it still lands, which is the shape shipped
    # puzzle 2 carried until 2026-09-08.
    yield "a queue entry consumed and refused", prep.Puzzle(
        id="fixture-overspent",
        difficulty=1,
        llm_shop=(engine.A, engine.B, engine.C),
        llm_gold=3,
        opponent_shop=(engine.A, engine.D),
        opponent_gold=3,
        opponent_placements=(
            prep.Placement(engine.D, (2, 0)),
            prep.Placement(engine.D, (2, 1)),
            prep.Placement(engine.A, (2, 2)),
        ),
    )

    # One gold and a shop of nothing but A: after the first placement the
    # opponent can afford nothing, is marked done, and never reaches the second.
    yield "a queue entry never consumed", prep.Puzzle(
        id="fixture-unconsumed",
        difficulty=1,
        llm_shop=(engine.A, engine.B, engine.C),
        llm_gold=3,
        opponent_shop=(engine.A,),
        opponent_gold=1,
        opponent_placements=(
            prep.Placement(engine.A, (2, 0)),
            prep.Placement(engine.A, (2, 1)),
        ),
    )


def _unmeasurable_fixtures():
    """Suite files that do not load as the suite they describe, one per way.

    ``prep.Suite.puzzles`` must refuse every one of them, and a guard that has
    never been seen to fire is not known to work. There is one case per place
    the loader can discard something the file listed: the whole file, a whole
    puzzle entry, a shop entry inside a kept puzzle, a placement inside a kept
    puzzle. Both shops appear because they are read for different things, the
    agent's to enumerate its plays and the opponent's to test affordability, and
    a case per shop is what says the guard does not depend on which.

    The last two are not discards. A file that lists no puzzles measures nothing
    and reads as a pass, and two entries under one id have one count and one
    artifact file between them, so the second's measurement replaces the first's.

    Most are a two-puzzle file whose first puzzle is legal, which is the shape
    that used to pass: a warning on stderr, then exit 0 with artifacts for the
    first puzzle only. Yields ``(what is lost, path)``.
    """
    legal = {
        "id": "measurable-1",
        "llm_shop": ["A", "B", "C"],
        "llm_gold": 3,
        "opponent_shop": ["A"],
        "opponent_gold": 2,
        "opponent_placements": [
            {"type": "A", "row": 2, "col": 0},
            {"type": "A", "row": 2, "col": 1},
        ],
    }
    second = dict(legal, id="measurable-2")

    def pair(broken):
        return {"puzzles": [legal, broken]}

    cases = [
        ("a root that is not a dictionary", [legal]),
        ("a 'puzzles' that is not an array", {"puzzles": {"0": legal}}),
        # generate.py --record-out nests its puzzles a level deeper, so this is
        # the shape a reviewer reaches for by mistake.
        ("a file that lists no puzzles", {"bin_edges": [0.0, 1.0]}),
        ("a puzzle entry that is not a dictionary", pair("measurable-2")),
        (
            "a puzzle with no id",
            pair({key: value for key, value in second.items() if key != "id"}),
        ),
        ("an llm_shop that is not an array", pair(dict(second, llm_shop="ABC"))),
        ("an llm_shop with no readable type", pair(dict(second, llm_shop=["Z", "Q"]))),
        (
            "an opponent_shop with no readable type",
            pair(dict(second, opponent_shop=["Z"])),
        ),
        (
            "an unreadable type in an otherwise readable llm_shop",
            pair(dict(second, llm_shop=["A", "B", "Z"])),
        ),
        (
            "an unreadable type in an otherwise readable opponent_shop",
            pair(dict(second, opponent_shop=["A", "Z"])),
        ),
        (
            "opponent_placements that is not an array",
            pair(dict(second, opponent_placements={})),
        ),
        (
            "an opponent placement that is not a dictionary",
            pair(dict(second, opponent_placements=["A at 2,0"])),
        ),
        (
            "an opponent placement with an unreadable type",
            pair(dict(second, opponent_placements=[{"type": "Z", "row": 2, "col": 0}])),
        ),
        (
            # The agent's own half, so puzzle_loader.gd drops it and so does
            # prep. It reaches no board and must still be counted.
            "an opponent placement on a square that is not the opponent's",
            pair(
                dict(
                    second,
                    opponent_placements=[
                        {"type": "A", "row": 2, "col": 0},
                        {"type": "A", "row": 0, "col": 0},
                    ],
                )
            ),
        ),
        ("two puzzles under one id", pair(dict(second, id="measurable-1"))),
    ]
    with tempfile.TemporaryDirectory() as directory:
        for index, (description, root) in enumerate(cases):
            path = Path(directory) / ("unmeasurable-%d.json" % index)
            path.write_text(json.dumps(root))
            yield description, path


def _stale_artifact_fixtures():
    """Analysis directories whose artifacts no longer say what a reader computes.

    ``analysis.load_analysis`` must refuse every one of them, and a guard that
    has never been seen to fire is not known to work. There is one case per way
    the ground under a written artifact moves: the suite file restates its
    puzzle, the suite file stops listing its puzzle, the oracle that computed
    its numbers is not the oracle reading them, and the manifest that names the
    suite stops reading as one.

    Each case is a directory the real writer built from a puzzle small enough to
    enumerate in milliseconds, moved out from under afterwards. The third case
    rewrites the fingerprint the artifact recorded rather than editing a source
    file, which is what an artifact from any earlier oracle looks like on disk:
    the guard compares recorded against current and cannot tell the two apart.

    Yields ``(what moved, artifact path)``.
    """
    puzzle = {
        "id": "staged",
        "difficulty": 1,
        "llm_shop": ["A"],
        "llm_gold": 1,
        "opponent_shop": ["A"],
        "opponent_gold": 2,
        "opponent_placements": [
            {"type": "A", "row": 2, "col": 0},
            {"type": "A", "row": 2, "col": 1},
        ],
    }

    def restate_the_puzzle(suite, root, artifact_path):
        root["puzzles"][0]["opponent_placements"].append(
            {"type": "A", "row": 2, "col": 2}
        )
        suite.write_text(json.dumps(root))

    def drop_the_puzzle(suite, root, artifact_path):
        root["puzzles"][0]["id"] = "renamed"
        suite.write_text(json.dumps(root))

    def age_the_oracle(suite, root, artifact_path):
        built = json.loads(artifact_path.read_text())
        built["code"] = "0" * len(built["code"])
        artifact_path.write_text(json.dumps(built))

    def truncate_the_manifest(suite, root, artifact_path):
        manifest = artifact_path.parent / analysis.MANIFEST_NAME
        manifest.write_text(manifest.read_text()[:12])

    cases = [
        ("a suite file that restates the artifact's puzzle", restate_the_puzzle),
        ("a suite file that no longer lists the artifact's puzzle", drop_the_puzzle),
        ("an artifact built by another version of the oracle", age_the_oracle),
        ("a manifest that no longer reads as one", truncate_the_manifest),
    ]
    with tempfile.TemporaryDirectory() as directory:
        for index, (description, move) in enumerate(cases):
            staged = Path(directory) / ("staged-%d" % index)
            staged.mkdir()
            suite = staged / "suite_file.json"
            root = {"puzzles": [copy.deepcopy(puzzle)]}
            suite.write_text(json.dumps(root))

            landscape = analysis.analyze_puzzle(prep.load_suite(suite).puzzles()[0])
            with contextlib.redirect_stdout(io.StringIO()):
                analysis.write_artifacts(staged / "artifacts", suite, [landscape])

            artifact_path = staged / "artifacts" / ("puzzle_%s.json" % puzzle["id"])
            move(suite, root, artifact_path)
            yield description, artifact_path


def _structure_complaints():
    """A puzzle drawn under every reachable structure, held to what it names.

    ``--suite-plays`` and ``--opponent-mix`` are built into a candidate rather
    than rejected for, so nothing downstream reads them back: a suite whose
    draws had stopped obeying either one would still be written, still be
    stamped with the arguments that were asked for, and still pass every other
    check in this module, while holding puzzles that satisfy neither. This is
    what would notice.

    The play count is recounted with ``prep.count_plays`` on the drawn puzzle,
    opponent and all. That is the claim ``action_space_table`` rests on and
    cannot check for itself: it probes each shop and gold against an empty
    opponent, so a recount against a real one is the evidence that the agent's
    action space is settled by its own shop and gold alone. Counting resolves no
    battles, so even the half-million-play stratum costs under a second and
    every reachable count is checked rather than a sample of them.

    The mix cycles rather than crossing, because the two constraints are built
    by separate code paths with no argument in common: the mix settles the
    opponent's shop, gold and queue and the play count settles the agent's shop
    and gold, so every mix and every count is exercised without paying for the
    product of the two.

    Yields ``(what was checked, what is wrong or None)``.
    """
    rng = random.Random(4)
    mixes = [parse_mix(text) for text in ("A", "D,D,D", "A,B,C,D", "A,A,B,C,D")]
    wrong_plays = []
    wrong_mix = []
    unlanded = []
    for index, plays in enumerate(action_space_table()):
        mix = mixes[index % len(mixes)]
        structure = Structure(
            plays, tuple(engine.label_to_type(label) for label in mix)
        )
        puzzle = random_puzzle(rng, "structured%d" % index, structure)
        counted = prep.count_plays(puzzle)
        if counted != plays:
            wrong_plays.append(
                "%s was asked for %d legal plays and has %d" % (puzzle.id, plays, counted)
            )
        fielded = tuple(
            sorted(
                engine.TYPE_LABELS[placement.unit_type]
                for placement in puzzle.opponent_placements
            )
        )
        if fielded != mix:
            wrong_mix.append(
                "%s was asked to field %s and fields %s"
                % (puzzle.id, "/".join(mix), "/".join(fielded) or "nothing")
            )
        try:
            prep.check_queue_lands(puzzle)
        except prep.QueueDoesNotLand as error:
            unlanded.append("%s: %s" % (puzzle.id, error))

    yield (
        "a puzzle drawn under an action-space target has that many legal plays",
        None if not wrong_plays else "; ".join(wrong_plays),
    )
    yield (
        "a puzzle drawn under an opponent mix fields exactly that mix",
        None if not wrong_mix else "; ".join(wrong_mix),
    )
    yield (
        "a constrained draw still lands its whole queue",
        None if not unlanded else "; ".join(unlanded),
    )


def _stamp_complaints():
    """A suite this module writes, and what its stamp fails to say, if anything.

    The stamp exists because ``lowtail_suite.json`` was written without one: on
    2026-09-10 its seed had to be recovered by replaying candidate streams until
    one reproduced all five of its puzzles, and two of the arguments behind it
    were never recovered. So what is checked here is not that a key is present
    but that what is in it is enough to run the study again.

    Four things make it enough. Every option the study takes is either recorded
    or one of the three that only say where output went, which is what stops an
    option added later from going unrecorded. The stamp holds what this run
    resolved, defaults included, rather than what the caller happened to type.
    The recorded parameters go back through the parser as themselves, so they
    are a command and not just a description of one. And a run that named
    neither the bin count nor the edges still bins the prior the same way when
    it is replayed with ``DEFAULT_SUITE_BINS`` moved, which is the one default
    argparse does not apply and so the one a stamp can silently miss.

    The suite is written from one fixture puzzle rather than a sampled run: what
    is under test is what the file says about its own making, which is the same
    whether the puzzles in it took one enumeration or ten thousand.

    Yields ``(what was checked, what is wrong or None)``.
    """
    parser = build_parser()
    args = parser.parse_args(
        [
            # Every option away from its default, so that dropping one from
            # the reconstructed command line shows up as a difference rather
            # than being handed back by the default it happened to match.
            # ``--suite-bins`` is the exception and has to be: it excludes
            # ``--suite-edges``, which is the rule this suite was built under.
            "study",
            "--seed", "11",
            "--sample", "3",
            "--band", "0.04",
            "--targets", "0.2,0.8",
            "--suite-edges", "0.1,0.6,0.9",
            "--suite-size", "2",
            "--suite-plays", "1080",
            "--opponent-mix", "A,D",
            "--suite-cap", "9",
        ]
    )

    unrecorded = sorted(
        set(vars(args))
        - {"command", "handler"}
        - set(STUDY_PARAMETERS)
        - set(STUDY_OUTPUTS)
    )
    yield (
        "every study option is recorded or is an output destination",
        None
        if not unrecorded
        else "study also takes %s, which a suite file neither records nor knows "
        "to leave out" % ", ".join(unrecorded),
    )

    candidate = evaluate(
        prep.Puzzle(
            id="stamped",
            difficulty=1,
            llm_shop=(engine.A,),
            llm_gold=1,
            opponent_shop=(engine.A,),
            opponent_gold=2,
            opponent_placements=(
                prep.Placement(engine.A, (2, 0)),
                prep.Placement(engine.A, (2, 1)),
            ),
        )
    )
    run = SuiteRun(
        structures(args),
        [0.1, 0.6, 0.9],
        [[1, 1]],
        [[[candidate], []]],
        [[1, None]],
        [1],
        0,
        0.0,
    )

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "stamped_suite.json"
        write_suite(run, path, study_provenance(args))
        stamped = json.loads(path.read_text())["provenance"]

    resolved = study_parameters(args)
    yield (
        "the stamp records the arguments the run resolved",
        None
        if stamped["parameters"] == resolved
        else "the run resolved %s and the file says %s"
        % (resolved, stamped["parameters"]),
    )
    yield (
        "the stamp records the command line that ran",
        None
        if stamped["command"] == sys.argv
        else "the line run was %s and the file says %s" % (sys.argv, stamped["command"]),
    )

    again = study_parameters(parser.parse_args(study_command(stamped["parameters"])))
    yield (
        "the recorded arguments read back through the parser as themselves",
        None
        if again == stamped["parameters"]
        else "%s reads back as %s" % (stamped["parameters"], again),
    )

    # The fixture above names --suite-edges, which excludes --suite-bins, so it
    # can never exercise a resolved bin count. This one names neither, and the
    # default is moved under the replay: a stamp that recorded the count binds
    # the same edges either way, and a stamp that recorded None follows the
    # moved default into a different suite.
    global DEFAULT_SUITE_BINS
    defaulted = parser.parse_args(["study"])
    difficulties = [0.02, 0.31, 0.88]
    binned = suite_edges(defaulted, difficulties)
    replayed = parser.parse_args(study_command(study_parameters(defaulted)))
    held = DEFAULT_SUITE_BINS
    DEFAULT_SUITE_BINS = held + 2
    try:
        rebinned = suite_edges(replayed, difficulties)
    finally:
        DEFAULT_SUITE_BINS = held
    yield (
        "a run that named no bins records the bin count it resolved",
        None
        if rebinned == binned
        else "the run binned the prior at %s and its recorded arguments bin it at "
        "%s once the default moves" % (binned, rebinned),
    )


def _self_check(args):
    """Hold ``evaluate`` to ``analysis.analyze_puzzle`` on the shipped suite,
    fire the loss and staleness guards on fixtures of this module's own, and
    require a suite this module writes to say what would produce it again.

    The shipped suite is the fixture the oracle is checked against, so the two
    things that must be true of it are that the two enumerations agree about its
    difficulty and that every puzzle fields the placements it lists. The second
    is the fault the suite carried on 2026-09-08: puzzle 2 gave its opponent 6
    gold for a queue costing 7 and silently fielded four of the five units it
    lists.

    Loading the suite is itself the third check, since ``prep.Suite.puzzles``
    refuses a file that does not load as the suite it describes.

    The staleness fixtures are the same idea one stage later: a landscape is
    written, the suite or the oracle behind it moves, and
    ``analysis.load_analysis`` must refuse to hand the numbers back.

    The structure fixtures are a fourth thing rather than a guard: they draw a
    puzzle under each action-space target and opponent mix and hold it to what
    was asked for, which nothing else in the module reads back.
    ``_structure_complaints`` holds the reason.

    The stamp fixture is a fifth: it writes a suite and reads back what the file
    says produced it. ``_stamp_complaints`` holds the reason.

    Any suite may be passed, and a legal one passes whatever its opponents
    queue, including nothing at all.
    """
    failed = False
    for puzzle in prep.load_suite(args.puzzles).puzzles():
        try:
            prep.check_queue_lands(puzzle)
        except prep.QueueDoesNotLand as error:
            print("puzzle %s: FIELDS LESS THAN ITS FILE LISTS: %s" % (puzzle.id, error))
            failed = True
            continue
        print("puzzle %s: all %d opponent placements land"
              % (puzzle.id, len(puzzle.opponent_placements)))

        mine = evaluate(puzzle)
        theirs = analysis.analyze_puzzle(puzzle)
        agree = (
            mine.play_count == theirs.play_count and mine.win_count == theirs.win_count
        )
        failed = failed or not agree
        print(
            "  generate %d/%d = %.4f, analysis %d/%d = %.4f  %s"
            % (
                mine.win_count,
                mine.play_count,
                mine.difficulty,
                theirs.win_count,
                theirs.play_count,
                theirs.difficulty,
                "agree" if agree else "DISAGREE",
            )
        )

    for description, fixture in _unlanded_fixtures():
        try:
            prep.check_queue_lands(fixture)
        except prep.QueueDoesNotLand as error:
            print("guard fires on %s: %s" % (description, error))
        else:
            print("GUARD DID NOT FIRE on %s, puzzle %s" % (description, fixture.id))
            failed = True

    for description, path in _unmeasurable_fixtures():
        try:
            prep.load_suite(path).puzzles()
        except prep.SuiteNotMeasurable as error:
            print("guard fires on %s: %s" % (description, error))
        else:
            print("GUARD DID NOT FIRE on %s, %s" % (description, path))
            failed = True

    for description, path in _stale_artifact_fixtures():
        try:
            analysis.load_analysis(path)
        except analysis.ArtifactNotCurrent as error:
            print("guard fires on %s: %s" % (description, error))
        else:
            print("GUARD DID NOT FIRE on %s, %s" % (description, path))
            failed = True

    for description, complaint in _structure_complaints():
        if complaint is None:
            print("a constrained draw holds: %s" % description)
        else:
            print("A CONSTRAINED DRAW DOES NOT HOLD %s: %s" % (description, complaint))
            failed = True

    for description, complaint in _stamp_complaints():
        if complaint is None:
            print("a written suite holds: %s" % description)
        else:
            print("A WRITTEN SUITE DOES NOT HOLD %s: %s" % (description, complaint))
            failed = True
    return 1 if failed else 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Measure what a puzzle at a target difficulty costs to generate."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    study = sub.add_parser(
        "study",
        help="the prior, the acceptance rate per target, a forecast, and a suite",
    )
    study.add_argument("--seed", type=int, default=20260907)
    study.add_argument(
        "--sample", type=int, default=200, help="random puzzles to enumerate for the prior"
    )
    study.add_argument("--band", type=float, default=DEFAULT_BAND)
    study.add_argument(
        "--targets",
        type=lambda text: tuple(float(part) for part in text.split(",")),
        default=DEFAULT_TARGETS,
    )
    study.add_argument("--suite-size", type=int, default=30)
    bins = study.add_mutually_exclusive_group()
    bins.add_argument(
        "--suite-bins",
        type=int,
        default=None,
        help="evenly spaced bins over the range the prior sample observed "
        "(default: %d)" % DEFAULT_SUITE_BINS,
    )
    bins.add_argument(
        "--suite-edges",
        type=parse_edges,
        default=None,
        help="the bin edges outright, increasing, comma separated, as in "
        "0,0.006,0.012,0.022,0.038,0.06. The only way to ask for a band the "
        "prior did not reach, or for bins of uneven width. Bins the cap could "
        "not fill are reported unfilled, not widened",
    )
    study.add_argument(
        "--suite-plays",
        type=parse_plays,
        default=None,
        help="action-space targets, comma separated, as exact counts of legal "
        "agent plays, as in 1080,29160. Each is a stratum drawn and reported "
        "separately and crossed against every difficulty bin, which is what "
        "varies difficulty and action-space size independently rather than "
        "together. Without it the agent's shop and gold are drawn at random and "
        "the action space is whatever they give",
    )
    study.add_argument(
        "--opponent-mix",
        type=parse_mix,
        default=None,
        help="the units every generated opponent fields, comma separated, as in "
        "A,B,C,D. Held identical in every puzzle of every stratum, so no unit "
        "type's share can move with difficulty. Without it the opponent's queue "
        "is drawn at random and its mix is whatever the draw gives",
    )
    study.add_argument(
        "--suite-cap", type=int, default=300, help="enumerations before the suite gives up"
    )
    study.add_argument("--suite-out", help="write the accepted suite here")
    study.add_argument("--record-out", help="write every measurement here as JSON")
    study.add_argument(
        "--verbose",
        action="store_true",
        help="a line per candidate on stderr; without it the suite still reports "
        "each candidate it accepts, so a long run shows progress",
    )
    study.set_defaults(handler=_study)

    check = sub.add_parser(
        "self-check",
        help="require this module's difficulty to match analysis's, require every "
        "puzzle to field what its file lists, fire the queue, loading and "
        "artifact-staleness guards on fixtures, and require a suite this module "
        "writes to name the arguments that produced it",
    )
    check.add_argument("--puzzles", default=prep.DEFAULT_PUZZLE_PATH)
    check.set_defaults(handler=_self_check)

    return parser


def main():
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
