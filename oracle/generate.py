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
import json
import math
import random
import statistics
import sys
import tempfile
from dataclasses import dataclass, replace
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


def random_puzzle(rng, puzzle_id):
    """One random legal puzzle. ``difficulty`` is a placeholder here; the value
    the loader reads is set per puzzle by ``puzzle_json`` when a suite is written.

    Every draw is a statement here rather than an argument, so the order the
    seed is consumed in is the order it is read in and a seed reproduces the
    same puzzle.
    """
    opponent_shop = tuple(rng.sample(ALL_TYPES, rng.choice(OPPONENT_SHOP_SIZES)))
    opponent_gold = rng.choice(GOLD_BAND)
    llm_shop = tuple(rng.sample(ALL_TYPES, AGENT_SHOP_SIZE))
    llm_gold = rng.choice(GOLD_BAND)
    queue = _random_queue(rng, opponent_shop, opponent_gold)
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
    """A random puzzle and the enumeration that measured its difficulty."""

    puzzle: prep.Puzzle
    play_count: int
    win_count: int
    seconds: float

    @property
    def difficulty(self):
        return self.win_count / self.play_count


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
    start = perf_counter()
    for play in prep.enumerate_plays(puzzle):
        result = engine.run_battle(prep.build_board(puzzle, play))
        if result["aborted"]:
            raise ValueError(
                "battle did not finish for play %s of puzzle %s"
                % (analysis.encode_play(play), puzzle.id)
            )
        final = result["final"]
        play_count += 1
        if final["llm_score"] > final["human_score"]:
            win_count += 1
    return Candidate(puzzle, play_count, win_count, perf_counter() - start)


def draw(rng, puzzle_id):
    """A random puzzle, measured, with its queue held to landing in full.

    The check is a postcondition on the generator and not a rejection rule:
    ``_random_queue`` cannot build a queue that fails it, so nothing here
    resamples and a failure aborts generation. That is the intended behaviour.
    A generator that had started emitting puzzles harder than they read as would
    otherwise write them into a suite, and every difficulty measured from that
    suite would describe boards other than the ones its file states.
    """
    puzzle = random_puzzle(rng, puzzle_id)
    prep.check_queue_lands(puzzle)
    return evaluate(puzzle)


def sample_candidates(rng, count, prefix, on_candidate=None):
    """Evaluate ``count`` random puzzles, reporting each as it lands."""
    candidates = []
    for index in range(count):
        candidate = draw(rng, "%s%d" % (prefix, index))
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
    """What filling the bins cost, whether or not they all filled."""

    edges: list
    quotas: list
    accepted: list
    filled_at: list
    attempts: int
    degenerate: int
    seconds: float

    @property
    def accepted_count(self):
        return sum(len(bucket) for bucket in self.accepted)


def build_suite(rng, edges, quotas, cap, on_candidate=None):
    """Reject-sample until every bin holds its quota or ``cap`` enumerations.

    A candidate is accepted into its own bin if that bin still has room, so a
    suite spanning a range costs far less than the same number of puzzles at one
    target. Those bins are much wider than the ``--band`` window the acceptance
    table measures, so what this run spends per accepted puzzle prices the bins
    and not that window. A degenerate candidate is rejected wherever it falls,
    which is what keeps the end bins from filling with puzzles the agent cannot
    affect. The cap is what stops an unreachable bin from running forever; the
    caller reports which bins were short.
    """
    classify = suite_classifier(edges)
    accepted = [[] for _ in quotas]
    filled_at = [None] * len(quotas)
    attempts = 0
    degenerate = 0
    start = perf_counter()
    while attempts < cap and any(
        len(bucket) < quota for bucket, quota in zip(accepted, quotas)
    ):
        candidate = draw(rng, "gen%d" % attempts)
        attempts += 1
        if is_degenerate(candidate.difficulty):
            degenerate += 1
        index = classify(candidate.difficulty)
        taken = index is not None and len(accepted[index]) < quotas[index]
        if taken:
            accepted[index].append(candidate)
            if len(accepted[index]) == quotas[index]:
                filled_at[index] = attempts
        if on_candidate is not None:
            on_candidate(attempts, candidate, index if taken else None)
    return SuiteRun(
        edges, quotas, accepted, filled_at, attempts, degenerate, perf_counter() - start
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
    "suite_cap",
)
STUDY_OUTPUTS = ("suite_out", "record_out", "verbose")


def study_parameters(args):
    """The study's arguments, resolved, in the shape a suite file records them.

    Resolved rather than as typed, because an argument the run left to a default
    reproduces a different file the day that default moves, and what the run
    actually used is the recorded value. Seven of the eight defaults are
    argparse's and arrive here already applied; the bin count's is a layer below
    it, in ``suite_bin_count``, so a run that named neither the count nor the
    edges is recorded with the count that run binned the prior at. The literal
    command line is kept beside this by ``study_provenance``, since the resolved
    set cannot recover it.
    """
    resolved = {}
    for name in STUDY_PARAMETERS:
        value = getattr(args, name)
        resolved[name] = list(value) if isinstance(value, (list, tuple)) else value
    if resolved["suite_edges"] is None:
        resolved["suite_bins"] = suite_bin_count(args)
    return resolved


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
            tokens.append(",".join(repr(float(part)) for part in value))
        else:
            tokens.append(repr(value))
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

    Rank 1 is the easiest puzzle in the file and rank N the hardest, ties inside
    a bin broken by win fraction. Rank rises with tier by construction, so the
    unique field the loader keeps carries the same direction the tier does.
    """
    bins = len(run.accepted)
    rank = 0
    for index in range(bins - 1, -1, -1):
        for candidate in sorted(
            run.accepted[index], key=lambda c: c.difficulty, reverse=True
        ):
            rank += 1
            yield rank, bins - index, candidate


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
    print()
    print(
        "SUITE: %d bins spanning %.4f to %.4f, degenerate puzzles rejected"
        % (len(run.quotas), run.edges[0], run.edges[-1])
    )
    print(
        "  %d of %d puzzles accepted from %d enumerations in %.1f s"
        % (run.accepted_count, sum(run.quotas), run.attempts, run.seconds)
    )
    print("  bin              tier  quota  filled  full at  difficulties")
    short = []
    for index, bucket in enumerate(run.accepted):
        values = sorted(c.difficulty for c in bucket)
        print(
            "  %.4f-%.4f  %4d  %5d  %6d  %7s  %s"
            % (
                run.edges[index],
                run.edges[index + 1],
                len(run.accepted) - index,
                run.quotas[index],
                len(values),
                run.filled_at[index] if run.filled_at[index] else "-",
                " ".join("%.4f" % value for value in values) or "-",
            )
        )
        if len(values) < run.quotas[index]:
            short.append(index)
    print(
        "  %d of the %d enumerations were degenerate and rejected wherever they fell"
        % (run.degenerate, run.attempts)
    )
    if run.accepted_count:
        print(
            "  %.1f enumerations and %.1f s per accepted puzzle, under the bin rule "
            "and not the band the acceptance table measures"
            % (run.attempts / run.accepted_count, run.seconds / run.accepted_count)
        )
    if short:
        print(
            "  UNFILLED after the %d-enumeration cap: %s"
            % (
                run.attempts,
                ", ".join(
                    "%.4f-%.4f (%d of %d)"
                    % (
                        run.edges[index],
                        run.edges[index + 1],
                        len(run.accepted[index]),
                        run.quotas[index],
                    )
                    for index in short
                ),
            )
        )
    return short


# --- CLI ---


def _record(prior, run, timing, args):
    return {
        "seed": args.seed,
        "band": args.band,
        "targets": list(args.targets),
        "timing_us_per_play": timing,
        "prior": [
            {
                "puzzle": puzzle_json(candidate, 1, 1),
                "difficulty": candidate.difficulty,
                "play_count": candidate.play_count,
                "win_count": candidate.win_count,
                "seconds": candidate.seconds,
            }
            for candidate in prior
        ],
        "suite": {
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

    def trace(index, candidate):
        print(
            "  candidate %d/%d  difficulty %.4f  %d plays  %.2f s"
            % (index + 1, args.sample, candidate.difficulty, candidate.play_count, candidate.seconds),
            file=sys.stderr,
        )

    prior = sample_candidates(rng, args.sample, "rand", trace if args.verbose else None)
    timing = timing_spread(prior)
    report_timing(timing)
    difficulties = report_prior(prior)
    report_targets(prior, args.targets, args.band)

    edges = suite_edges(args, difficulties)
    quotas = bin_quotas(args.suite_size, len(edges) - 1)
    report_forecast(
        difficulties,
        edges,
        quotas,
        args.targets,
        args.band,
        sum(c.seconds for c in prior) / len(prior),
        args.seed + 2,
    )

    def suite_trace(attempts, candidate, index):
        # Always the accepted ones, because a band the prior barely reached
        # spends most of a long cap between them, and a run that prints nothing
        # for an hour reads as a stall rather than as the cost it is.
        if index is None and not args.verbose:
            return
        print(
            "  attempt %d  difficulty %.4f  %.2f s  %s"
            % (
                attempts,
                candidate.difficulty,
                candidate.seconds,
                "-> bin %d" % index if index is not None else "rejected",
            ),
            file=sys.stderr,
        )

    run = build_suite(
        random.Random(args.seed + 1), edges, quotas, args.suite_cap, suite_trace
    )
    short = report_suite(run)

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
            json.dump(_record(prior, run, timing, args), handle, indent=1)
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
    run = SuiteRun([0.1, 0.6, 0.9], [1, 1], [[candidate], []], [1, None], 1, 0, 0.0)

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

    The stamp fixture is a fourth thing rather than a guard: it writes a suite
    and reads back what the file says produced it. ``_stamp_complaints`` holds
    the reason.

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
