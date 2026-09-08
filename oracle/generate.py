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
4. A suite. Bins spanning the observed difficulty range, filled by reject
   sampling from a fresh seed stream, capped in attempts. Its enumerations per
   accepted puzzle price those bins and say nothing about the band of step 2.
   A candidate every play wins, or none does, is rejected however well it fills
   a bin, because it is decided before the agent chooses and so measures
   nothing about an agent. The file it writes ranks puzzles from the easiest,
   which is the opposite direction to the win fraction, and carries the bin
   each one filled beside it: see ``accepted_in_order`` and ``puzzle_json``.

DIFFICULTY here is ``analysis``'s: the fraction of complete legal plays that
win, a win being ``llm_score > human_score``. ``self-check`` runs this module's
counter and ``analysis.analyze_puzzle`` over the shipped suite and requires them
to agree, which is what says the two are the same measurement.

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
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, replace
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

# Resamples behind a forecast, and re-enumerations of one puzzle behind the
# timing spread. Both are cheap next to the prior they read.
BOOTSTRAP_TRIALS = 2000
TIMING_REPEATS = 3


# --- Generating one puzzle ---


def _random_queue(rng, shop, gold):
    """A placement queue the scripted opponent can afford and fully place.

    Squares are distinct and on the opponent's own rows, every type is in its
    shop, and the running total never exceeds its gold, so no placement is
    refused and none is left unconsumed. A queue that costs more than its gold
    is placed up to the budget and the rest is silently dropped, which is a
    puzzle harder than it reads as; ``check_queue_lands`` is what stops this
    from emitting one.
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


def check_queue_lands(puzzle):
    """Raise unless every queued opponent placement reaches the board.

    A queue entry can be consumed and refused (unaffordable, off-shop, or onto
    a taken square) or never consumed at all (the opponent is marked done once
    it can afford nothing), and either way the puzzle fields fewer units than it
    reads as. Counting what landed catches both.

    One play is enough: the opponent's gold, queue and occupancy never touch
    agent state, and the two sides place on disjoint rows, so what it fields is
    the same under every play. Only the placement orders differ.
    """
    result = prep.simulate_prep(puzzle, next(prep.enumerate_plays(puzzle)))
    if len(result.opponent_units) != len(puzzle.opponent_placements):
        raise ValueError(
            "puzzle %s queues %d opponent placements but fields %d (%d refused): %s"
            % (
                puzzle.id,
                len(puzzle.opponent_placements),
                len(result.opponent_units),
                len(result.refused),
                puzzle.opponent_placements,
            )
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
    fields, not about the ones it lists. ``draw`` is where generated puzzles are
    held to the stronger property, and ``self-check`` reports it for the shipped
    ones.
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
    """A random puzzle whose opponent queue lands, measured."""
    puzzle = random_puzzle(rng, puzzle_id)
    check_queue_lands(puzzle)
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
    ``prep.load_puzzles``, and grouping on ``tier`` recovers the bins the
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


def suite_json(run):
    """The accepted puzzles as a loadable suite, plus the bins behind it."""
    return {
        "bin_edges": list(run.edges),
        "puzzles": [
            puzzle_json(candidate, rank, tier)
            for rank, tier, candidate in accepted_in_order(run)
        ],
    }


def write_suite(run, path):
    """Write the suite and read it back through the loader the game uses.

    ``prep.load_puzzles`` is the port of ``puzzle_loader.gd``, so a file it
    reads back as the puzzles it was written from is a file the game's loader
    accepts. Writing a suite the study cannot load is the failure this catches,
    and one comparison against the candidates in memory is cheap enough to
    always run.
    """
    with open(path, "w") as handle:
        json.dump(suite_json(run), handle, indent=2)

    expected = [
        replace(candidate.puzzle, difficulty=rank)
        for rank, _tier, candidate in accepted_in_order(run)
    ]
    if prep.load_puzzles(path) != expected:
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
            "puzzles": suite_json(run)["puzzles"],
        },
    }


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

    edges = bin_edges(difficulties[0], difficulties[-1], args.suite_bins)
    quotas = bin_quotas(args.suite_size, args.suite_bins)
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
        random.Random(args.seed + 1),
        edges,
        quotas,
        args.suite_cap,
        suite_trace if args.verbose else None,
    )
    short = report_suite(run)

    if args.suite_out:
        written = write_suite(run, args.suite_out)
        print(
            "  wrote %d puzzles to %s, reloaded through prep.load_puzzles"
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


def _self_check(args):
    """Hold ``evaluate`` to ``analysis.analyze_puzzle`` on the shipped suite.

    Also reports what each shipped queue actually fields, which is the property
    ``check_queue_lands`` exists to hold generated puzzles to. All three shipped
    queues land, so this is a fixture that means what it reads as; a line here
    saying otherwise means the suite has drifted.
    """
    failed = False
    for puzzle in prep.load_puzzles(args.puzzles):
        mine = evaluate(puzzle)
        theirs = analysis.analyze_puzzle(puzzle)
        agree = (
            mine.play_count == theirs.play_count and mine.win_count == theirs.win_count
        )
        failed = failed or not agree
        print(
            "puzzle %s: generate %d/%d = %.4f, analysis %d/%d = %.4f  %s"
            % (
                puzzle.id,
                mine.win_count,
                mine.play_count,
                mine.difficulty,
                theirs.win_count,
                theirs.play_count,
                theirs.difficulty,
                "agree" if agree else "DISAGREE",
            )
        )
        try:
            check_queue_lands(puzzle)
            print("  queue: all %d placements land" % len(puzzle.opponent_placements))
        except ValueError as error:
            print("  queue: %s" % error)
    return 1 if failed else 0


def main():
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
    study.add_argument("--suite-bins", type=int, default=6)
    study.add_argument(
        "--suite-cap", type=int, default=300, help="enumerations before the suite gives up"
    )
    study.add_argument("--suite-out", help="write the accepted suite here")
    study.add_argument("--record-out", help="write every measurement here as JSON")
    study.add_argument("--verbose", action="store_true", help="a line per candidate on stderr")
    study.set_defaults(handler=_study)

    check = sub.add_parser(
        "self-check", help="require this module's difficulty to match analysis's"
    )
    check.add_argument("--puzzles", default=prep.DEFAULT_PUZZLE_PATH)
    check.set_defaults(handler=_self_check)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
