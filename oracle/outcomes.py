"""Does the oracle's computed difficulty predict what an agent actually did?

That is validation gate L10, and it is one question with an x-axis and a y-axis.
The x-axis is ``analysis.PuzzleAnalysis.difficulty``, computed by enumerating a
puzzle's whole action space. The y-axis is what an agent scored on that puzzle,
read out of a game log by ``runlog.score_run``. This module joins the two over a
suite of puzzles and says, per arm, whether the ordering on one predicts the
ordering on the other.

READ THE NAME OF THE X-AXIS CAREFULLY. ``difficulty`` is the fraction of
complete legal plays that WIN, so a HIGH value is an EASY puzzle. Nothing here
flips it, because flipping it silently is how a sign error survives three
sessions. Every correlation below is against the metric as computed, and the
direction each outcome is expected to move in is fixed in ``_OUTCOMES`` before
any data is read.

DIFFICULTY IS NOT THE RANDOM AGENT'S WIN PROBABILITY, and no check here assumes
it is. It is P(win) under sampling uniform over COMPLETE PLAYS. ``LlmFallback``
samples uniformly over STEPS, a random affordable type and a random empty square
each turn, which is a different distribution over the same plays. MEASURED, AND
REPRODUCIBLE BY THE COMMAND BELOW: on the three shipped puzzles, difficulty
0.0318 / 0.0037 / 0.0430 against stepwise win rates 0.0310 / 0.0182 / 0.0896,
which is 0.98, 4.9 and 2.1 times difficulty. The two agree on one puzzle and are
five times apart on another, and nothing fixes the direction. The Monte Carlo
standard error at 20,000 plays and a rate near 0.03 is 0.0012, so the 4.9x and
the 2.1x are far outside the sampling noise and the 0.98x is inside it.

    python3 -B oracle/outcomes.py stepwise

is what produced those numbers: 20,000 stepwise-sampled plays per shipped
puzzle, seed 20260910, one stream per puzzle named by the puzzle so a puzzle's
figure does not depend on which puzzles were sampled before it. So the null
arm's win rate is not predicted to equal difficulty. It is predicted to be
MONOTONE in it, and that is all this module tests.

FOUR DESIGN POINTS, each of which changes the answer:

1. THE RESAMPLING UNIT IS THE ATTEMPT, NEVER THE PLACEMENT. Placements inside
   one attempt share a board and a prefix, so they are not independent draws. A
   bootstrap over placements reports an interval far narrower than the data
   supports; the self-check measures that gap on a fixture rather than asserting
   it. A resampled attempt brings all of its placements.

2. THE PERMUTATION TEST IS ENUMERATED, NOT SAMPLED. Five puzzles is 120
   orderings, so the exact null distribution of the rank correlation is walked
   in full and the p-value is exact. THE SMALLEST ONE-SIDED p ATTAINABLE AT n=5
   IS 1/120 = 0.0083. That is the floor of the instrument, not a strong result:
   it says a perfect monotone ordering is detectable and that nothing finer is.
   THE FLOOR RISES WITH ANYTHING THAT SHRINKS THE NUMBER OF DISTINGUISHABLE
   ORDERINGS, AND FEWER PUZZLES COMES FIRST: 3 puzzles is 1/6 = 0.1667 and
   already above 0.05 with nothing tied at all, while 4 is 1/24 = 0.0417 and
   below it. Ties raise it further. The floor is printed beside every p, and
   where it exceeds 0.05 the report names which of the two put it there rather
   than blaming ties for a column that has none.

3. THE HEADLINE IS A RANK CORRELATION, NOT PEARSON. Five points, and no claim
   that the relationship is linear; L10 asks whether difficulty PREDICTS, which
   is a question about monotonicity. Ties are handled by midranks and the
   correlation is Pearson's applied to those midranks, which is the definition
   that stays correct when ranks tie; the 1 - 6*sum(d^2)/(n^3-n) shortcut does
   not, and is not used.

4. THE PRIMARY ANALYSIS OF A MODEL ARM USES MODEL-CHOSEN PLACEMENTS ONLY,
   because ``game_controller`` falls back to ``LlmFallback.pick_random_placement``
   whenever the model's answer cannot be applied, and charging that placement's
   regret to the model measures a blend of a model and a coin. Both the
   model-chosen and the all-placement figures are computed for every arm and
   both are rows of the outcomes table; only the arm's primary one is counted in
   its bottom line, and where the attribution changes the verdict both verdicts
   are printed side by side, so an arm where the choice decides the answer says
   so rather than reporting one of the two. THE RANDOM ARM IS THE EXCEPTION AND IS
   DECLARED, NOT INFERRED: it is 100% fallback by construction, so it is the
   null curve rather than a contaminated model, and it is analysed on all of its
   placements. ``--null`` is what says which arm that is.

THE NULL CURVE IS NOT OPTIONAL. Without it a difficulty-to-regret slope could
just as well be the puzzles getting structurally harder as a model responding to
difficulty. So a comparison holding model arms and no ``--null`` refuses, and
every model arm is additionally reported as a per-puzzle difference against the
null with its own bootstrap interval and its own exact test. THAT DIFFERENCE
REMOVES THE PUZZLES' OWN STRUCTURE AND DOES NOT REMOVE THE HEADROOM: what an arm
can win back is bounded by what the null gave up, and that bound tightens
towards zero at the easy end on its own. ``_DIFFERENCE_DIRECTION`` derives the
side the test is run on from exactly that, and the report says which of the two
explanations it has ruled out and which it has not.

AN ARM THAT DID NOT PLAY THE WHOLE SUITE HAS NOT ANSWERED THE QUESTION FOR THE
SUITE. ``runlog.load_run`` carries both the suite it read the log against and
the attempt the run stopped part way through, and this module reports both per
arm: how many of the suite's puzzles the arm played, which ones it did not, and
whether the log ends mid-attempt. A killed run reduces, tests and prints exactly
like a finished one, so the coverage line goes above every table and again into
the bottom line rather than being left for a reader to infer from a row count.

WHAT IS LEFT OPEN, DELIBERATELY, AND THE THREE COLUMNS THAT ARE ONE
MEASUREMENT. A play's value is the final score margin, a small integer whose
range differs per puzzle: gen1 spans -2 to 2 and gen13 spans -1 to 5. The same
regret is therefore a different fraction of what each puzzle could cost, and
more than one normalizer is defensible. THERE ARE EXACTLY THREE REGRET COLUMNS
IN THIS REPORT AND THEY ARE ONE QUANTITY UNDER THREE NORMALIZERS:

    mean whole-play regret                 divided by nothing
    mean placement regret                  divided by play length
    mean whole-play regret / value span    divided by the puzzle's value range

THE SECOND IS NOT AN INDEPENDENT OUTCOME, and this module used to print it as
though it were. Placement regrets telescope over the prefixes of a play, so they
sum to that play's whole-play regret, and over a puzzle

    mean placement regret = sum(whole-play regrets) / placements
                          = mean whole-play regret / placements per attempt.

Checked against the pilot's null arm: gen1 2.70 / (24/10) = 1.125 and gen0
1.30 / (29/10) = 0.448, which are the figures that column reports. The divisor
is the arm's mean play length on that puzzle, set by the puzzle's gold and shop
AND by which units the agent bought, since a cheaper unit leaves gold for
another placement. So it is a per-puzzle, per-arm normalizer, it is partly under
the agent's own control, and it is not the raw column measured better.

NORMALIZING CHANGES THE ANSWER. Dividing each puzzle by its own positive number
is not a monotone transform of the column across puzzles, so the three can rank
the puzzles differently and can return opposite verdicts. On the pilot's null
arm they do: rho -0.410 raw, -1.000 by play length, -0.821 by span, which is
DOES NOT PREDICT against PREDICTS AT THE FLOOR. WHICH OF THE THREE IS THE
STUDY'S OUTCOME IS NOT DECIDED HERE, so none of them is starred, all three are
reported, and the bottom line counts them as one quantity and says so.

More placements per attempt does narrow the bootstrap interval, because more
observations sit behind the same mean. That is a real and separate benefit and
it is not the point estimate moving: under this normalizer the point estimate is
the raw column divided by a per-puzzle number, and a narrower interval around it
is not evidence that the division is the right one.

Run it:

    python3 -B oracle/outcomes.py compare \
        --null random=<game_*.json> --arm luna=<game_*.json> \
        --puzzles godot/puzzles/pilot_suite.json --artifacts <dir>
    python3 -B oracle/outcomes.py self-check
    python3 -B oracle/outcomes.py stepwise

BUILD THE ARTIFACTS FIRST. With no landscape artifact for the suite, every arm
re-enumerates all five puzzles from scratch, twice: once for the value ranges
and once inside ``runlog.score_run``. On the pilot suite that is about 70
seconds per pass. ``python3 -B oracle/analysis.py --puzzles <suite> --out-dir
<dir>`` once makes all of it free.
"""

import argparse
import itertools
import math
import random
import sys
from typing import NamedTuple

import analysis
import engine
import generate
import prep
import runlog

# The same 2,000 resamples generate.py prices its acceptance rules with. Reused
# rather than re-chosen so two modules of this study do not quietly report
# intervals built from different amounts of resampling.
BOOTSTRAP_TRIALS = generate.BOOTSTRAP_TRIALS

# A 95% interval, read off the resample distribution by generate.quantile, which
# is nearest-rank: every endpoint printed is a value some resample actually
# produced, and never an interpolation between two of them.
CI_LOW = 0.025
CI_HIGH = 0.975

# Fixed so a re-run of the same logs prints the same intervals. It is an
# argument because a reader who wants to see how much of an interval's last
# digit is the seed should be able to move it.
DEFAULT_SEED = 1010


def stream(seed, *labels):
    """A resample stream named by what it is resampling.

    One shared generator would make an arm's interval depend on which arms were
    named before it on the command line, so adding a fourth arm would silently
    reprint the first three with different endpoints. Seeding per arm from the
    seed and the arm's own name makes every interval a function of the seed and
    the thing measured, and of nothing else.
    """
    return random.Random("%d:%s" % (seed, ":".join(labels)))

# Enumerating the null distribution costs n! rank correlations. Eight puzzles is
# 40,320 of them and takes under a second; nine is 362,880 and the honest answer
# there is a sampled test, which this module does not implement. It refuses
# rather than silently switching methods, because "exact p" is a promise.
EXACT_LIMIT = 40320

# Rank correlations come out of floating point arithmetic, so two orderings that
# are the same statistic can differ in the last bit. Every comparison against
# the observed value is made with this slack, which can only ever make a p-value
# larger.
_EPSILON = 1e-12


# --- Statistics, from scratch ---


def mean(values):
    """The arithmetic mean, or None over nothing.

    Written out rather than imported because oracle/ computes its own
    statistics; the None is what lets a caller print "no data" instead of
    dividing by zero three frames up.
    """
    values = list(values)
    return sum(values) / len(values) if values else None


def midranks(values):
    """Ranks from 1, with tied values sharing the mean of the ranks they span.

    Midranks are what make the rank correlation below correct under ties. Three
    values tied at positions 2, 3 and 4 all rank 3.0, so the rank column keeps
    the same total it would have had untied and no tie is broken by input order.
    """
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        stop = start
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[start]]:
            stop += 1
        share = (start + stop) / 2.0 + 1.0
        for position in range(start, stop + 1):
            ranks[order[position]] = share
        start = stop + 1
    return ranks


def spearman(xs, ys):
    """Spearman's rank correlation, as Pearson's applied to the midranks.

    This is the definition, and it is the one that stays correct when ranks tie.
    The familiar 1 - 6*sum(d^2)/(n^3-n) form is an algebraic shortcut that
    assumes every rank is distinct, and using it on a column where two puzzles
    scored the same would report a correlation neither variable supports.

    Returns None when either column has no spread at all, because a constant
    column has no ordering to correlate: that is a statement about the data and
    it must not arrive as a zero, which reads as "measured, and unrelated".
    """
    rank_x = midranks(xs)
    rank_y = midranks(ys)
    mean_x = mean(rank_x)
    mean_y = mean(rank_y)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(rank_x, rank_y))
    spread_x = math.sqrt(sum((a - mean_x) ** 2 for a in rank_x))
    spread_y = math.sqrt(sum((b - mean_y) ** 2 for b in rank_y))
    if spread_x == 0.0 or spread_y == 0.0:
        return None
    return covariance / (spread_x * spread_y)


class TestResult(NamedTuple):
    """One exact permutation test of a rank correlation.

    ``p_one`` is one-sided in ``direction``, which is fixed before the data is
    read. ``floor`` is the smallest one-sided p ANY arrangement of this outcome
    column could have produced, which is 1/orderings when nothing ties and
    larger when something does; printed beside p it is what stops 0.0083 being
    read as a result driven by volume rather than by the only ordering the
    instrument can resolve.
    """

    rho: float
    p_one: float
    p_two: float
    floor: float
    orderings: int
    direction: int

    @property
    def at_floor(self):
        return self.rho is not None and self.p_one <= self.floor + _EPSILON


def permutation_test(xs, ys, direction):
    """The exact null distribution of Spearman's rho, by walking every pairing.

    With n puzzles there are n! ways to attach the difficulty labels to the
    outcomes, every one of them equally likely under the null that difficulty
    says nothing, so the null distribution is enumerable rather than samplable
    and the p-value is exact rather than an estimate. The observed pairing is
    itself one of the n!, which is why p can never come out below 1/n!.

    ``direction`` is +1 where the outcome is predicted to rise with the
    difficulty metric and -1 where it is predicted to fall. It is an argument
    rather than something read off the sign of the observed correlation, because
    a one-sided test whose side is chosen after seeing the data is a two-sided
    test reported at half its p.
    """
    orderings = math.factorial(len(xs))
    if orderings > EXACT_LIMIT:
        raise ValueError(
            "%d puzzles is %d orderings, past the %d this module will enumerate. "
            "It reports an exact p or none, so it will not fall back to a sampled "
            "one here" % (len(xs), orderings, EXACT_LIMIT)
        )
    observed = spearman(xs, ys)
    null = [spearman(xs, list(pairing)) for pairing in itertools.permutations(ys)]
    if observed is None:
        # Every pairing of a constant column gives the same non-correlation, so
        # no arrangement is more extreme than any other and the honest p is 1.
        return TestResult(None, 1.0, 1.0, 1.0, orderings, direction)
    signed = [value * direction for value in null]
    seen = observed * direction
    extreme = sum(1 for value in signed if value >= seen - _EPSILON)
    best = max(signed)
    return TestResult(
        rho=observed,
        p_one=extreme / orderings,
        p_two=sum(1 for value in null if abs(value) >= abs(observed) - _EPSILON)
        / orderings,
        floor=sum(1 for value in signed if value >= best - _EPSILON) / orderings,
        orderings=orderings,
        direction=direction,
    )


class Interval(NamedTuple):
    """A bootstrap interval, with the resamples that could not produce a value.

    ``censored`` is separate rather than dropped quietly: a resample of attempts
    that happened to draw no placement at all cannot be averaged in, and how
    often that happened is the reader's only sign that the interval rests on
    fewer than ``BOOTSTRAP_TRIALS`` values.
    """

    low: float
    high: float
    censored: int


def pooled_mean(units):
    """The mean over every number in every unit, or None if there are none.

    Pooling rather than averaging the per-unit means, because the outcome is a
    mean per placement and attempts do not all hold the same number of
    placements. An attempt that contributed no placement contributes nothing to
    either the numerator or the denominator, so it moves the estimate not at all
    while still being a unit the bootstrap can draw.
    """
    total = 0.0
    count = 0
    for unit in units:
        total += sum(unit)
        count += len(unit)
    return total / count if count else None


def _interval(values, censored):
    values.sort()
    if not values:
        return None
    return Interval(
        generate.quantile(values, CI_LOW), generate.quantile(values, CI_HIGH), censored
    )


def bootstrap_ci(units, rng, trials=BOOTSTRAP_TRIALS):
    """A 95% interval on ``pooled_mean``, resampling UNITS with replacement.

    THE UNIT IS THE ATTEMPT AND EVERY UNIT IS A TUPLE OF THAT ATTEMPT'S NUMBERS.
    Drawing placements instead would treat the placements of one attempt as
    independent draws when they share a board and a prefix, and would report an
    interval far narrower than the data supports; the self-check builds a
    fixture where the two differ by a factor of about the square root of the
    placements per attempt and requires the attempt interval to be the wider.

    A whole-play outcome is one number per attempt, so it arrives here as
    one-element tuples and goes through the same path. There is one resampling
    rule in this module and this is it.
    """
    if not units:
        return None
    size = len(units)
    values = []
    censored = 0
    for _ in range(trials):
        drawn = pooled_mean([units[rng.randrange(size)] for _ in range(size)])
        if drawn is None:
            censored += 1
        else:
            values.append(drawn)
    return _interval(values, censored)


def bootstrap_difference(units_a, units_b, rng, trials=BOOTSTRAP_TRIALS):
    """A 95% interval on ``pooled_mean(a) - pooled_mean(b)``, resampled apart.

    The two arms played the same puzzles but are different runs, so the
    resamples are independent: one draw of a's attempts against one draw of b's.
    An interval that excludes zero says the two arms differ on that puzzle by
    more than either arm's own attempt-to-attempt spread accounts for.
    """
    if not units_a or not units_b:
        return None
    size_a, size_b = len(units_a), len(units_b)
    values = []
    censored = 0
    for _ in range(trials):
        left = pooled_mean([units_a[rng.randrange(size_a)] for _ in range(size_a)])
        right = pooled_mean([units_b[rng.randrange(size_b)] for _ in range(size_b)])
        if left is None or right is None:
            censored += 1
        else:
            values.append(left - right)
    return _interval(values, censored)


# --- Turning scored placements into per-puzzle outcomes ---


class PuzzleOutcome(NamedTuple):
    """What one arm did on one puzzle, with the puzzle's x-axis beside it.

    IT CARRIES ITS OWN RESAMPLING UNITS. ``model_units``, ``all_units`` and
    ``play_units`` are one tuple per ATTEMPT holding that attempt's numbers, so
    every mean below is a pooled mean over them and every interval is a
    bootstrap over them. A caller that wants a further interval, such as the
    difference between two arms, resamples the same units rather than inventing
    a second unit of its own.

    Both regret means are always present: ``mean_regret_model`` charges only the
    placements the log says the model itself made, ``mean_regret_all`` charges
    every placement the agent made including the fallback's. Which is primary
    depends on the arm, and both are printed either way.
    """

    puzzle_id: str
    difficulty: float
    worst_value: int
    best_value: int
    attempts: int
    wins: int
    placements: int
    model_placements: int
    pure_attempts: int
    pure_wins: int
    wilson: tuple
    model_units: tuple
    all_units: tuple
    play_units: tuple
    ci_regret_model: Interval
    ci_regret_all: Interval
    ci_play_regret: Interval

    @property
    def win_rate(self):
        return self.wins / self.attempts

    @property
    def mean_regret_model(self):
        return pooled_mean(self.model_units)

    @property
    def mean_regret_all(self):
        return pooled_mean(self.all_units)

    @property
    def mean_play_regret(self):
        return pooled_mean(self.play_units)

    @property
    def placements_per_attempt(self):
        """The divisor that turns whole-play regret into placement regret.

        It is a property of the puzzle AND of what the arm bought: gold and shop
        bound how many placements a complete play can hold, and an agent that
        buys cheaper units fits more of them in. So it differs between arms on
        the same puzzle, which is what stops it being a puzzle-level constant.
        """
        return self.placements / self.attempts if self.attempts else None

    @property
    def value_span(self):
        """The widest whole-play regret this puzzle can charge.

        V* over the empty board is ``best_value`` and the worst complete play is
        ``worst_value``, so no play of this puzzle can give up more than the
        difference. It is the natural normalizer and it is offered, never
        substituted: see the module docstring.
        """
        return self.best_value - self.worst_value

    @property
    def normalized_play_regret(self):
        raw = self.mean_play_regret
        if raw is None or not self.value_span:
            return None
        return raw / self.value_span


def _by_attempt(rows):
    """The rows of one puzzle regrouped into the attempts they came from.

    Every row of an attempt repeats that attempt's value and whole-play regret,
    so this is what turns a placement table back into plays; ``config`` is in
    the key because one log holds several configs and their attempt numbers
    restart.
    """
    attempts = {}
    for row in rows:
        attempts.setdefault((row.config, row.attempt), []).append(row)
    return [attempts[key] for key in sorted(attempts)]


def puzzle_outcome(rows, landscape, rng):
    """One arm's outcome on one puzzle, from that puzzle's scored placements."""
    attempts = _by_attempt(rows)
    model_units = tuple(
        tuple(row.regret for row in attempt if row.chooser == runlog.MODEL)
        for attempt in attempts
    )
    all_units = tuple(tuple(row.regret for row in attempt) for attempt in attempts)
    # One number per attempt, wrapped so it goes through the same pooled mean
    # and the same attempt-level bootstrap as the placement columns. There is
    # one resampling rule in this module and this is how a whole-play outcome
    # obeys it.
    play_units = tuple((attempt[0].whole_play_regret,) for attempt in attempts)
    # A win is the margin the game recorded being positive, which is
    # analysis.py's own definition of a winning play and the one difficulty
    # counts. Every row of an attempt carries that attempt's value, so the first
    # row of each is asked once.
    wins = sum(1 for attempt in attempts if attempt[0].value > 0)
    pure = [
        attempt
        for attempt in attempts
        if all(row.chooser == runlog.MODEL for row in attempt)
    ]
    return PuzzleOutcome(
        puzzle_id=rows[0].puzzle_id,
        difficulty=landscape.difficulty,
        worst_value=landscape.worst_value,
        best_value=landscape.best_value,
        attempts=len(attempts),
        wins=wins,
        placements=len(rows),
        model_placements=sum(len(unit) for unit in model_units),
        pure_attempts=len(pure),
        pure_wins=sum(1 for attempt in pure if attempt[0].value > 0),
        wilson=generate.wilson_interval(wins, len(attempts)),
        model_units=model_units,
        all_units=all_units,
        play_units=play_units,
        ci_regret_model=bootstrap_ci(model_units, rng),
        ci_regret_all=bootstrap_ci(all_units, rng),
        ci_play_regret=bootstrap_ci(play_units, rng),
    )


class Arm(NamedTuple):
    """One run, named by the caller, with its per-puzzle outcomes.

    ``is_null`` is declared on the command line and never inferred from the
    fallback rate. An arm that is 100% fallback because it had no API key is the
    null curve; an arm that is 100% fallback because every one of the model's
    answers was rejected is a broken model arm, and the two are identical in the
    log. Only the person who ran them knows which happened.

    ``suite_ids`` is the suite file's own puzzle list and ``unfinished`` names the
    attempt the run stopped part way through, both carried from the ``Run`` so
    that a partial run cannot be reduced, tested and printed as a finished one.
    ``landscapes`` holds the puzzles this arm played, keyed by id, so the suite
    report can be assembled from the union across arms rather than from whichever
    log was named first.
    """

    name: str
    path: str
    is_null: bool
    suite_ids: tuple
    landscapes: dict
    unfinished: tuple
    outcomes: tuple
    placements: int
    model_placements: int
    fallback_placements: int
    unstated_placements: int
    attempts: int

    @property
    def fallback_rate(self):
        return self.fallback_placements / self.placements if self.placements else None

    @property
    def played_ids(self):
        return tuple(item.puzzle_id for item in self.outcomes)

    @property
    def missing_ids(self):
        """The suite's puzzles this arm has no outcome for, in suite order."""
        played = set(self.played_ids)
        return tuple(key for key in self.suite_ids if key not in played)

    @property
    def primary_is_model_chosen(self):
        """The null curve is scored on everything; a model arm on its own choices."""
        return not self.is_null


def build_arm(name, path, is_null, suite_path, artifacts, seed):
    """Score one log and reduce it to per-puzzle outcomes.

    The landscapes are fetched a second time here rather than threaded out of
    ``score_run``, which does not return them. That is a re-read of the
    artifacts and free once they exist; with no artifacts it is a second full
    enumeration of the suite, which the module docstring says to avoid by
    building them.
    """
    rng = stream(seed, name)
    run = runlog.load_run(path, suite_path)
    rows = runlog.score_run(run, artifacts)
    landscapes = runlog.landscapes_for(run, artifacts)
    by_puzzle = {}
    for row in rows:
        by_puzzle.setdefault(row.puzzle_id, []).append(row)
    outcomes = tuple(
        puzzle_outcome(by_puzzle[puzzle_id], landscapes[puzzle_id], rng)
        for puzzle_id in sorted(by_puzzle, key=lambda key: landscapes[key].difficulty)
    )
    by_model = sum(1 for row in rows if row.chooser == runlog.MODEL)
    by_fallback = sum(1 for row in rows if row.chooser == runlog.FALLBACK)
    return Arm(
        name=name,
        path=str(run.path),
        is_null=is_null,
        suite_ids=tuple(puzzle.id for puzzle in run.suite_puzzles),
        landscapes=landscapes,
        unfinished=tuple(attempt.name for attempt in run.unfinished),
        outcomes=outcomes,
        placements=len(rows),
        model_placements=by_model,
        fallback_placements=by_fallback,
        unstated_placements=len(rows) - by_model - by_fallback,
        attempts=sum(outcome.attempts for outcome in outcomes),
    )


# --- The three outcomes, and the direction each is predicted to move ---


class Outcome(NamedTuple):
    """One column of the outcomes table, and what is known about it in advance.

    ``direction`` is +1 where the outcome is predicted to RISE with the
    difficulty metric. Remember the metric is the fraction of plays that win, so
    its high end is the EASY end: a win rate rises with it and a regret falls.

    ``normalizer`` names what the raw quantity was divided by and is printed in
    the row. Three of the five rows are one quantity under three different
    normalizers, and saying so in the row itself is what stops them being read
    as three findings.

    ``best`` is the value a column takes when there is nothing left to improve:
    1 for a win rate, 0 for a regret. A column constant AT that value is
    saturated, which is a substantive finding about the suite's ceiling; a
    column constant anywhere else is flat, which is not the same statement.
    """

    label: str
    direction: int
    normalizer: str
    best: float
    of: object


_OUTCOMES = (
    Outcome("win rate", +1, "none", 1.0, lambda outcome: outcome.win_rate),
    Outcome(
        "mean placement regret (model-chosen)",
        -1,
        "play length",
        0.0,
        lambda outcome: outcome.mean_regret_model,
    ),
    Outcome(
        "mean placement regret (all placements)",
        -1,
        "play length",
        0.0,
        lambda outcome: outcome.mean_regret_all,
    ),
    Outcome(
        "mean whole-play regret", -1, "none", 0.0, lambda outcome: outcome.mean_play_regret
    ),
    Outcome(
        "mean whole-play regret / value span",
        -1,
        "value span",
        0.0,
        lambda outcome: outcome.normalized_play_regret,
    ),
)

# L10 asks two things of an arm: did it win, and how much did it give up. The
# second is reported under ALL THREE of its normalizers, because the choice
# between them is open (see the module docstring) and starring one of them would
# be making it. So the bottom line counts four columns, states which three of
# them are one quantity, and never reports a normalizer as a second finding.
_WIN_RATE = "win rate"
_RAW_REGRET = "mean whole-play regret"
_SPAN_REGRET = "mean whole-play regret / value span"


def _counted_labels(arm):
    """The four columns the bottom line counts, in the order it prints them.

    Only the play-length column can be filtered by chooser, so it is the only
    place design point 4's attribution rule applies: a model arm is judged on
    the placements its model chose and the null curve on every placement it
    made, which is the same arithmetic over the set that is actually the null.
    ATTRIBUTION IS A CHOICE THIS MODULE HAS MADE AND STATES. The normalizer is
    not, and none of the three is preferred here.
    """
    play_length = (
        "mean placement regret (model-chosen)"
        if arm.primary_is_model_chosen
        else "mean placement regret (all placements)"
    )
    return (_WIN_RATE, _RAW_REGRET, play_length, _SPAN_REGRET)


# The predicted direction of the ARM-MINUS-NULL difference in whole-play regret,
# worked out from the definitions and not from the data.
#
# Difficulty is the fraction of complete legal plays that WIN, so its HIGH end is
# the EASY end. Whole-play regret is V* minus the play's value and so is never
# negative, which makes the null's mean regret on a puzzle exactly how much that
# puzzle punishes a random play. An arm cannot do better than give up nothing, so
# its difference from the null is bounded below by minus the null's own regret.
# At the easy end of the axis a random play already gives up little, that bound
# is close to zero and there is almost nothing for an arm to win back; at the
# hard end the bound is wide and the difference has room to be large and
# negative. THE DIFFERENCE IS THEREFORE PREDICTED TO RISE TOWARDS ZERO ALONG THE
# DIFFICULTY AXIS, and the one-sided test is run on +1. It was -1, which is the
# side the definitions rule out, so the test could not fire whatever the data
# did.
_DIFFERENCE_DIRECTION = +1


class Column(NamedTuple):
    """One outcome column of one arm, and the test that was run on it.

    ``values`` is the column itself, kept because a verdict has to tell a column
    constant at the best value it could take from one that is merely constant.
    ``result`` is None when fewer than three puzzles had a value here, which is
    an absence of measurement rather than a measured absence of relationship;
    everything downstream is built so those two can never print the same way.
    """

    outcome: Outcome
    result: TestResult
    values: tuple
    used: int
    dropped: int


class Verdict(NamedTuple):
    """What one column came to, as two facts and as the sentence to print.

    ``tested`` is whether the instrument could have fired on this column at all
    and ``predicted`` is whether it did. They are separate fields because a
    bottom line assembled by matching the first word of ``text`` cannot tell "no
    relationship" from "no measurement", and that is the distinction a reader
    quotes.
    """

    tested: bool
    predicted: bool
    text: str


def relationship(arm, outcome):
    """The exact test of one outcome against difficulty, over this arm's puzzles.

    Puzzles with no value for the outcome are dropped and counted, because the
    n! floor printed beside the p-value has to be the floor of the test that was
    actually run. A model arm that made no model-chosen placement on a puzzle
    contributes nothing to that column, and pretending otherwise with a zero
    would report the strongest possible performance on the puzzle it did worst.
    """
    pairs = [
        (item.difficulty, outcome.of(item))
        for item in arm.outcomes
        if outcome.of(item) is not None
    ]
    dropped = len(arm.outcomes) - len(pairs)
    ys = tuple(y for _, y in pairs)
    if len(pairs) < 3:
        return Column(outcome, None, ys, len(pairs), dropped)
    xs = [x for x, _ in pairs]
    return Column(
        outcome, permutation_test(xs, list(ys), outcome.direction), ys, len(pairs), dropped
    )


def _cannot_fire_cause(column):
    """Why this column's smallest attainable p is above 0.05, which is usually n.

    The floor is 1/n! with nothing tied and larger when something ties, so at
    n=3 it is 1/6 = 0.1667 and above 0.05 with every value distinct, while at
    n=4 it is 1/24 = 0.0417 and below it. Reading every floor above 0.05 as ties
    told a reader that a column with no ties in it had them, which is the one
    thing a reader cannot check without the column in front of them.
    """
    result = column.result
    untied = 1.0 / result.orderings
    if untied > 0.05:
        cause = (
            "only %d puzzles have a value in this column, so %d! = %d pairings put the "
            "smallest attainable p at %.4f with nothing tied at all"
            % (column.used, column.used, result.orderings, untied)
        )
        if result.floor > untied + _EPSILON:
            cause += ", and ties in it raise that to %.4f" % result.floor
    else:
        cause = (
            "%d puzzles would put the smallest attainable p at 1/%d = %.4f, and TIES in "
            "this column raise it to %.4f"
            % (column.used, result.orderings, untied, result.floor)
        )
        tied_value = max(column.values) if column.outcome.direction > 0 else min(column.values)
        at_best = sum(
            1 for value in column.values if abs(value - column.outcome.best) <= _EPSILON
        )
        if at_best > 1 and abs(tied_value - column.outcome.best) <= _EPSILON:
            cause += (
                " because %d of the %d puzzles sit at the best attainable value of %.3f, "
                "which is this suite's ceiling rather than an arbitrary tie"
                % (at_best, column.used, column.outcome.best)
            )
    return cause + ", above 0.05, so no ordering of it could have been called"


def verdict(column):
    """The plain statement, decided by a rule and not by reading the number.

    Three ways a column can be untestable and three ways it can be tested. The
    untestable ones are named apart: too few puzzles to run the test, a constant
    column, and a test whose floor sits above 0.05. A constant column splits
    again on whether the constant is the best value the column could take, since
    a win rate of 1.000 on every puzzle says the easy end of this suite does not
    tell this arm from a perfect player, which is a finding, while a column flat
    anywhere else is not.

    Of the testable ones: an ordering the instrument resolves perfectly, one it
    resolves at the conventional 0.05, and one it cannot separate from chance.
    At n=5 with no ties the middle level admits only rho >= 0.9, so it is one
    step wide; that is the instrument, and the printed floor is what says so.
    """
    result = column.result
    if result is None:
        return Verdict(
            False,
            False,
            "NOT TESTED: %d of the %d puzzles this arm played have a value in this "
            "column and the exact test needs at least 3"
            % (column.used, column.used + column.dropped),
        )
    if result.rho is None:
        value = column.values[0]
        if abs(value - column.outcome.best) <= _EPSILON:
            return Verdict(
                False,
                False,
                "NOT TESTED, SATURATED: the outcome is %.3f on every puzzle, which is "
                "the best value it can take. This arm is indistinguishable from a "
                "perfect player across every puzzle it played, which is a finding about "
                "the ceiling of this suite and NOT a measured absence of relationship"
                % value,
            )
        return Verdict(
            False,
            False,
            "NOT TESTED, FLAT: the outcome is %.3f on every puzzle, so it has no "
            "ordering to correlate. It is not at the best attainable value of %.3f, so "
            "this is a flat column and not a ceiling" % (value, column.outcome.best),
        )
    if result.floor > 0.05:
        return Verdict(False, False, "NOT TESTED, CANNOT FIRE: " + _cannot_fire_cause(column))
    if result.at_floor and abs(result.rho) >= 1.0 - _EPSILON:
        return Verdict(
            True,
            True,
            "PREDICTS: perfectly monotone in the predicted direction, p at the floor",
        )
    if result.p_one <= 0.05:
        return Verdict(True, True, "PREDICTS: monotone enough for p <= 0.05 one-sided")
    return Verdict(True, False, "DOES NOT PREDICT at this n")


# --- Reporting ---


def _grid(headers, rows, indent="  "):
    cells = [list(headers)] + [list(row) for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    for index, row in enumerate(cells):
        print(indent + "  ".join(value.ljust(width) for value, width in zip(row, widths)))
        if index == 0:
            print(indent + "  ".join("-" * width for width in widths))


def _num(value, template="%.3f"):
    return "n/a" if value is None else template % value


def _ci(interval, template="%.3f"):
    if interval is None:
        return "n/a"
    text = ("[" + template + ", " + template + "]") % (interval.low, interval.high)
    return text + (" %d censored" % interval.censored if interval.censored else "")


def suite_landscapes(arms):
    """Every landscape any arm read, keyed by puzzle id.

    The union rather than one arm's, because a puzzle one arm skipped is still a
    puzzle of the suite and the arm that did play it knows its difficulty.
    """
    landscapes = {}
    for arm in arms:
        landscapes.update(arm.landscapes)
    return landscapes


def _report_suite(arms, suite_path):
    """The suite as the suite file states it, not as the first log happened to be.

    ``run.suite_puzzles`` is that file's own list, and it is what the n behind
    every caveat below has to come from. Reading it off ``arms[0].outcomes``
    instead restated the suite as whatever that one log contained, so a puzzle no
    arm reached vanished from the description of the suite under a heading naming
    the suite file.
    """
    suite_ids = arms[0].suite_ids
    disagreeing = [arm.name for arm in arms if arm.suite_ids != suite_ids]
    landscapes = suite_landscapes(arms)
    known = sorted(
        (key for key in suite_ids if key in landscapes),
        key=lambda key: landscapes[key].difficulty,
    )
    unplayed = [key for key in suite_ids if key not in landscapes]
    print("suite %s" % suite_path)
    if disagreeing:
        print(
            "  THE ARMS WERE NOT ALL READ AGAINST THIS SUITE (%s were not), so the "
            "puzzle list below is %s's and the others are describing something else"
            % (", ".join(disagreeing), arms[0].name)
        )
    print(
        "%d puzzles IN THE SUITE FILE, ordered by the difficulty metric: %s"
        % (
            len(suite_ids),
            ", ".join("%s %.4f" % (key, landscapes[key].difficulty) for key in known),
        )
    )
    if unplayed:
        print(
            "  %d OF THEM WERE PLAYED BY NO ARM IN THIS RUN AND ARE IN NO TABLE BELOW: "
            "%s. No landscape was read for them, so this report says nothing at all "
            "about them and the suite is not measured."
            % (len(unplayed), ", ".join(unplayed))
        )
    print(
        "THE METRIC IS THE FRACTION OF COMPLETE LEGAL PLAYS THAT WIN, SO ITS HIGH END "
        "IS THE EASY END: a win rate is predicted to RISE along this axis and a regret "
        "to FALL. It is not the random agent's win probability and nothing here "
        "assumes it is; see the module docstring."
    )
    _grid(
        ("puzzle", "difficulty", "value range", "span"),
        [
            (
                key,
                "%.4f" % landscapes[key].difficulty,
                "%d to %d" % (landscapes[key].worst_value, landscapes[key].best_value),
                "%d" % (landscapes[key].best_value - landscapes[key].worst_value),
            )
            for key in known
        ]
        + [(key, "not played", "-", "-") for key in unplayed],
    )
    spans = {key: landscapes[key].best_value - landscapes[key].worst_value for key in known}
    widest = max(known, key=lambda key: spans[key])
    narrowest = min(known, key=lambda key: spans[key])
    print(
        "  the span is the widest whole-play regret each puzzle can charge. RAW REGRET "
        "IS THEREFORE NOT COMPARABLE ACROSS THESE PUZZLES: the same regret is a "
        "different fraction of what %s, which spans %d, and %s, which spans %d, could "
        "have cost."
        % (widest, spans[widest], narrowest, spans[narrowest])
    )
    print(
        "  THERE ARE THREE REGRET COLUMNS BELOW AND THEY ARE ONE QUANTITY UNDER THREE "
        "NORMALIZERS: divided by nothing, divided by the arm's play length on that "
        "puzzle (which is all that \"mean placement regret\" is, and the arm block says "
        "so with the arithmetic), and divided by this span. THIS STUDY HAS NOT CHOSEN "
        "BETWEEN THEM, so none of the three is starred, all three are reported, and "
        "each arm's bottom line counts them as one quantity."
    )
    print(
        "  %d bootstrap resamples, drawing ATTEMPTS with replacement so a drawn attempt "
        "brings all of its placements; 95%% interval by nearest rank." % BOOTSTRAP_TRIALS
    )


def _report_coverage(arm, landscapes):
    """How much of the suite this arm actually played, above everything else.

    A run killed at its API-error limit is reduced, tested and given a verdict
    exactly like a finished one, and every table in the block below looks
    complete either way. So this goes first, it names the puzzles that are
    missing, and it says where on the difficulty axis they sat when another arm
    reached them, because the ones a run does not get to are not missing at
    random.
    """
    missing = arm.missing_ids
    if missing:
        named = ", ".join(
            "%s (difficulty %.4f)" % (key, landscapes[key].difficulty)
            if key in landscapes
            else "%s (no landscape read by any arm)" % key
            for key in missing
        )
        print(
            "  INCOMPLETE COVERAGE: THIS ARM PLAYED %d OF THE SUITE'S %d PUZZLES. "
            "MISSING: %s. NO TABLE OR VERDICT BELOW IS A MEASUREMENT OF THE SUITE; "
            "every one of them describes only the %d puzzles this arm reached."
            % (len(arm.outcomes), len(arm.suite_ids), named, len(arm.outcomes))
        )
    else:
        print(
            "  coverage: played all %d of the suite's puzzles" % len(arm.suite_ids)
        )
    if arm.unfinished:
        print(
            "  THE RUN STOPPED PART WAY THROUGH %s, which states no outcome and is not "
            "scored. An ablation that hits its API-error limit ends this way, so this "
            "line is the difference between a run that finished and one that was cut."
            % "; ".join(arm.unfinished)
        )


def _report_arm(arm, landscapes):
    print()
    print(
        "ARM %s  (%s)  %s"
        % (arm.name, "NULL CURVE" if arm.is_null else "model", arm.path)
    )
    _report_coverage(arm, landscapes)
    print(
        "  %d attempts, %d placements: the model chose %d (%.1f%%), "
        "LlmFallback.pick_random_placement chose %d (%.1f%%)%s"
        % (
            arm.attempts,
            arm.placements,
            arm.model_placements,
            100.0 * arm.model_placements / arm.placements,
            arm.fallback_placements,
            100.0 * arm.fallback_placements / arm.placements,
            ", %d state nothing" % arm.unstated_placements
            if arm.unstated_placements
            else "",
        )
    )
    if arm.is_null:
        print(
            "  DECLARED THE NULL CURVE, so it is analysed on ALL of its placements: a "
            "fallback placement here is the null's own choice and not contamination. "
            "Its primary placement-regret column is the all-placements one."
        )
        if arm.model_placements:
            print(
                "  BUT %d of its placements say the model chose them, which a null arm "
                "should not have. Either the wrong log was named --null or the run had "
                "an API key it was not supposed to have." % arm.model_placements
            )
    else:
        print(
            "  A MODEL ARM, so its primary placement-regret column is the model-chosen "
            "one: a fallback placement is a random baseline's choice and charging its "
            "regret to the model measures a blend. Both columns are printed and both "
            "verdicts are given below."
        )
        if not arm.model_placements:
            print(
                "  BUT THE MODEL CHOSE NOTHING IN THIS RUN. Every placement is the "
                "fallback's, so its primary column is empty and this arm measures the "
                "same thing the null curve does. It was declared a model arm, so it is "
                "not relabelled here."
            )
    print()
    _grid(
        (
            "puzzle",
            "diff",
            "att",
            "win",
            "rate",
            "Wilson 95%",
            "play regret",
            "boot 95%",
            "/span",
            "pure att",
        ),
        [
            (
                item.puzzle_id,
                "%.4f" % item.difficulty,
                "%d" % item.attempts,
                "%d" % item.wins,
                "%.3f" % item.win_rate,
                "[%.3f, %.3f]" % item.wilson,
                _num(item.mean_play_regret, "%.2f"),
                _ci(item.ci_play_regret, "%.2f"),
                _num(item.normalized_play_regret),
                "%d (%d won)" % (item.pure_attempts, item.pure_wins),
            )
            for item in arm.outcomes
        ],
    )
    print(
        "  pure att is the attempts in which EVERY placement was the model's. A win "
        "rate and a whole-play regret are properties of a whole attempt and cannot be "
        "filtered by chooser, so where that count is below the attempt count the two "
        "columns left of it describe a mixture of the model and the fallback."
    )
    print()
    _grid(
        (
            "puzzle",
            "placements",
            "per attempt",
            "by model",
            "regret (model)",
            "boot 95%",
            "regret (all)",
            "boot 95%",
        ),
        [
            (
                item.puzzle_id,
                "%d" % item.placements,
                "%.2f" % item.placements_per_attempt,
                "%d" % item.model_placements,
                _num(item.mean_regret_model, "%.3f"),
                _ci(item.ci_regret_model),
                _num(item.mean_regret_all, "%.3f"),
                _ci(item.ci_regret_all),
            )
            for item in arm.outcomes
        ],
    )
    _report_placement_identity(arm)
    print()
    return _report_relationships(arm)


def _report_placement_identity(arm):
    """Say, as loudly as the span normalizer is said, what this column is.

    It is the column that carried the report's verdict, and it was the only
    normalizer that was not disclosed. Printing the arithmetic on this arm's own
    two extreme rows is what makes it checkable on the page rather than believed.
    """
    print(
        "  MEAN PLACEMENT REGRET IS WHOLE-PLAY REGRET DIVIDED BY PLAY LENGTH. IT IS NOT "
        "A SECOND MEASUREMENT. Placement regrets telescope over the prefixes of a play, "
        "so they sum to that play's whole-play regret and, over a puzzle,"
    )
    print("      mean placement regret = sum(whole-play regrets) / placements")
    print("                            = mean whole-play regret / placements per attempt.")
    checkable = [
        item
        for item in arm.outcomes
        if item.mean_play_regret is not None and item.placements_per_attempt
    ]
    if checkable:
        most = max(checkable, key=lambda item: item.placements_per_attempt)
        least = min(checkable, key=lambda item: item.placements_per_attempt)
        print(
            "      %s: %.2f / %.2f = %.3f, and %s: %.2f / %.2f = %.3f, which are the "
            "regret (all) rows above."
            % (
                least.puzzle_id,
                least.mean_play_regret,
                least.placements_per_attempt,
                least.mean_play_regret / least.placements_per_attempt,
                most.puzzle_id,
                most.mean_play_regret,
                most.placements_per_attempt,
                most.mean_play_regret / most.placements_per_attempt,
            )
        )
    print(
        "  THE DIVISOR IS THIS ARM'S OWN PLAY LENGTH ON THAT PUZZLE, set by the puzzle's "
        "gold and shop AND by what the agent bought, since a cheaper unit leaves gold "
        "for another placement. So it differs between arms on one puzzle, it is partly "
        "under the agent's control, and dividing by it is a per-puzzle normalizer "
        "exactly as the value span is. It is not a monotone transform of the raw "
        "column: it can and does reorder the puzzles."
    )
    print(
        "  MORE PLACEMENTS PER ATTEMPT ALSO NARROWS THE BOOTSTRAP INTERVAL, which is a "
        "real and separate benefit: more observations sit behind the same mean. That is "
        "the interval moving, not the point estimate, and it is not evidence that the "
        "division is the right one. The identity is exact for the regret (all) column; "
        "the model-chosen column is the same sum restricted to the model's own "
        "placements and equals it wherever the model chose every placement."
    )


def _report_relationships(arm):
    """Every column, then the two questions L10 asks, then the bottom line.

    Returns what the block spent in tests, for the multiple-comparison
    disclosure the run prints at the end.
    """
    counted = _counted_labels(arm)
    columns = {}
    rows = []
    for outcome in _OUTCOMES:
        column = relationship(arm, outcome)
        columns[outcome.label] = (column, verdict(column))
        result = column.result
        rows.append(
            (
                outcome.label,
                outcome.normalizer,
                "rises" if outcome.direction > 0 else "falls",
                _num(result.rho if result else None, "%+.3f"),
                "%.4f" % result.p_one if result else "n/a",
                "%.4f" % result.p_two if result else "n/a",
                "%.4f" % result.floor if result else "n/a",
                "%d%s" % (column.used, " (%d dropped)" % column.dropped if column.dropped else ""),
                "yes" if outcome.label in counted else "",
            )
        )
    print("  DIFFICULTY AGAINST EACH OUTCOME, exact permutation test over every pairing")
    _grid(
        (
            "outcome",
            "divided by",
            "predicted",
            "rho",
            "p 1-sided",
            "p 2-sided",
            "p floor",
            "n",
            "counted",
        ),
        rows,
    )
    print(
        "  THE THREE ROWS WHOSE OUTCOME NAMES A REGRET ARE ONE QUANTITY UNDER THE THREE "
        "NORMALIZERS IN THE \"divided by\" COLUMN, not three findings. Read down that "
        "column before reading across any row."
    )
    print(
        "  counted marks the four columns the bottom line counts: the win rate, and "
        "regret under each of its three normalizers. The two placement-regret rows "
        "differ only in ATTRIBUTION, which design point 4 decides and this module "
        "states; the NORMALIZER is the open choice and none of the three is preferred."
    )
    example = next(
        (column.result for column, _ in columns.values() if column.result is not None),
        None,
    )
    if example is not None:
        print(
            "  the p-values are EXACT, not sampled: all %d pairings of %d puzzles were "
            "walked. THE SMALLEST ONE-SIDED p ATTAINABLE HERE IS 1/%d = %.4f, so a "
            "perfectly monotone ordering is the finest thing this suite can resolve and "
            "%.4f is the floor of the instrument rather than a result driven by volume. "
            "The p floor column is that number for each column's own n and ties, and "
            "where it exceeds 0.05 the test could not have fired whatever the data did."
            % (
                example.orderings,
                len(arm.outcomes),
                example.orderings,
                1.0 / example.orderings,
                1.0 / example.orderings,
            )
        )
        print(
            "  the one-sided side is fixed before the data is read, per the predicted "
            "column; the two-sided p is beside it for a reader who does not accept that."
        )
    _report_bottom_line(arm, columns, counted)
    _report_split_disagreement(arm, columns)
    tests = sum(1 for column, _ in columns.values() if column.result is not None)
    could_fire = sum(
        1
        for column, _ in columns.values()
        if column.result is not None and column.result.floor <= 0.05
    )
    intervals = sum(
        1
        for item in arm.outcomes
        for interval in (item.ci_play_regret, item.ci_regret_model, item.ci_regret_all)
        if interval is not None
    )
    print(
        "  MULTIPLE COMPARISONS IN THIS BLOCK: %d exact one-sided permutation tests at "
        "alpha 0.05, of which %d were on columns whose floor is at or below 0.05 and so "
        "could ever have fired, plus %d bootstrap 95%% intervals printed above. Nothing "
        "here is corrected for that and no correction is implied; the count is stated "
        "so a reader can apply their own." % (tests, could_fire, intervals)
    )
    return tests, could_fire, intervals


def _report_bottom_line(arm, columns, counted):
    """The one sentence a reader quotes, saying what actually happened.

    It counted only labels beginning "PREDICTS", so CANNOT FIRE, a saturated
    column and too-few-puzzles all arrived as non-predictions and an arm on which
    nothing was measurable read "predicts 0 of the 3". Tested, predicted and
    untestable are three counts here and are printed as three.
    """
    print()
    print(
        "  BOTTOM LINE for %s. L10 asks this arm two things, whether it won and how much "
        "it gave up, and the second is counted under all three of its normalizers "
        "because the choice between them is open." % arm.name
    )
    for label in counted:
        print("    %-40s %s" % (label + ":", columns[label][1].text))
    tested = [label for label in counted if columns[label][1].tested]
    predicted = [label for label in counted if columns[label][1].predicted]
    untested = [label for label in counted if not columns[label][1].tested]
    print()
    if not tested:
        print(
            "  NOTHING WAS MEASURED FOR %s: none of the %d headline columns could be "
            "tested at all, so this arm returns NO VERDICT on whether difficulty "
            "predicts its performance. That is an absent measurement and NOT a measured "
            "null." % (arm.name, len(counted))
        )
    else:
        print(
            "  %d headline columns: %d could be tested, %d of those %d predicted, and %d "
            "could not be tested at all."
            % (len(counted), len(tested), len(predicted), len(tested), len(untested))
        )
    if untested:
        print(
            "  the untested ones and why: %s"
            % "; ".join(
                "%s (%s)" % (label, columns[label][1].text.split(":")[0])
                for label in untested
            )
        )
    print(
        "  THE THREE REGRET COLUMNS ARE ONE QUANTITY UNDER THREE NORMALIZERS, so these "
        "are counts of columns and not of independent findings."
    )
    if arm.missing_ids:
        print(
            "  AND THIS BOTTOM LINE IS ABOUT THE %d PUZZLES THIS ARM PLAYED, NOT ABOUT "
            "THE SUITE: it did not reach %s."
            % (len(arm.outcomes), ", ".join(arm.missing_ids))
        )
    if arm.is_null:
        print(
            "  THIS ARM IS THE NULL CURVE, so a relationship here is the five puzzles "
            "getting structurally easier or harder for an agent that is not "
            "responding to anything. It is the baseline a model arm is differenced "
            "against, and on its own it is evidence about the suite and not about a "
            "model."
        )


def _report_split_disagreement(arm, columns):
    """Say when the chooser split is what decided the answer.

    The brief's rule, kept literally: if dropping the fallback placements changes
    the verdict, both numbers are printed rather than the primary one alone.
    """
    model = columns["mean placement regret (model-chosen)"]
    every = columns["mean placement regret (all placements)"]
    if model[0].result is None or every[0].result is None:
        # One of the two columns had nothing to test, which is an absence rather
        # than a disagreement about attribution. The null curve is always here,
        # by construction, and the lines above have already said so.
        return
    if model[1].text == every[1].text:
        return
    print(
        "  THE CHOOSER SPLIT DECIDES THIS ARM'S PLACEMENT-REGRET ANSWER, so both are "
        "stated. Fallback rate %.1f%%. On the model's own placements: rho %s, one-sided "
        "p %s, %s. On every placement the agent made: rho %s, one-sided p %s, %s."
        % (
            100.0 * arm.fallback_rate,
            _num(model[0].result.rho, "%+.3f"),
            "%.4f" % model[0].result.p_one,
            model[1].text,
            _num(every[0].result.rho, "%+.3f"),
            "%.4f" % every[0].result.p_one,
            every[1].text,
        )
    )


def difference_relationship(deltas):
    """The exact test of the arm-minus-null difference against difficulty.

    One place, so that the side the test is run on is the side
    ``_DIFFERENCE_DIRECTION`` derives and the self-check can hold it to that.
    """
    return permutation_test(
        [x for x, _ in deltas], [y for _, y in deltas], _DIFFERENCE_DIRECTION
    )


def _report_against_null(arm, null, seed):
    """One model arm as a per-puzzle difference from the null curve.

    This is the part that removes "the puzzles get structurally harder". A slope
    against difficulty in the arm's own numbers is consistent with that and with
    the arm responding to difficulty; the same slope in the DIFFERENCE from a
    random agent on the same puzzles is not consistent with the first, because
    the null met the same structure. WHAT IT DOES NOT REMOVE is the headroom, and
    ``_DIFFERENCE_DIRECTION`` is where that is written down.

    Returns the tests and intervals it spent, for the run's disclosure.
    """
    print()
    print("ARM %s AGAINST THE NULL CURVE %s" % (arm.name, null.name))
    rng = stream(seed, arm.name, "vs", null.name)
    by_id = {item.puzzle_id: item for item in null.outcomes}
    shared = [item for item in arm.outcomes if item.puzzle_id in by_id]
    if not shared:
        print("  no puzzle appears in both arms, so there is nothing to difference")
        return 0, 0
    if len(shared) < len(arm.outcomes):
        print(
            "  %d of this arm's %d puzzles are in the null curve; the rest are dropped"
            % (len(shared), len(arm.outcomes))
        )
    rows = []
    deltas = []
    for item in shared:
        base = by_id[item.puzzle_id]
        # Whole-play regret, because it is the outcome both arms have on the
        # same footing: a placement-regret difference would compare the model's
        # chosen placements against the null's, which are different in number
        # per attempt as well as in what chose them.
        difference = item.mean_play_regret - base.mean_play_regret
        deltas.append((item.difficulty, difference))
        rows.append(
            (
                item.puzzle_id,
                "%.4f" % item.difficulty,
                "%.2f" % item.mean_play_regret,
                "%.2f" % base.mean_play_regret,
                "%+.2f" % difference,
                _ci(bootstrap_difference(item.play_units, base.play_units, rng), "%+.2f"),
                "%.3f -> %.3f" % (base.win_rate, item.win_rate),
            )
        )
    _grid(
        (
            "puzzle",
            "difficulty",
            "play regret",
            "null",
            "difference",
            "boot 95% on the difference",
            "win rate null -> arm",
        ),
        rows,
    )
    print(
        "  a difference interval that excludes 0 is a puzzle where this arm and a "
        "random agent differ by more than either arm's attempt-to-attempt spread."
    )
    if len(deltas) < 3:
        print(
            "  the two arms share %d puzzles and the exact test needs at least 3, so "
            "the difference was NOT TESTED against difficulty. Nothing here is a null "
            "result about it." % len(deltas)
        )
        return 0, len(shared)
    result = difference_relationship(deltas)
    column = Column(
        Outcome(
            "arm minus null whole-play regret",
            _DIFFERENCE_DIRECTION,
            "none",
            0.0,
            None,
        ),
        result,
        tuple(y for _, y in deltas),
        len(deltas),
        len(arm.outcomes) - len(deltas),
    )
    print(
        "  difficulty against the DIFFERENCE in whole-play regret, predicted to RISE: "
        "rho %s, one-sided p %.4f (floor %.4f, %d pairings). %s"
        % (
            _num(result.rho, "%+.3f"),
            result.p_one,
            result.floor,
            result.orderings,
            verdict(column).text,
        )
    )
    print(
        "  THE PREDICTED SIDE IS +1 AND IS DERIVED, NOT FITTED: whole-play regret is "
        "never negative, so what an arm can win back from the null is bounded by what "
        "the null itself gave up, and at the easy end of the axis a random play gives "
        "up little. The difference is therefore squeezed towards zero as difficulty "
        "rises."
    )
    print(
        "  WHAT THIS RULES OUT AND WHAT IT DOES NOT. Differencing removes the puzzles "
        "getting structurally harder, because the null met the same five. It does NOT "
        "remove that shrinking headroom, which produces the same rise with no arm "
        "responding to anything at all. Separating those two needs the difference "
        "scaled by the null's own regret, and this module does not compute it."
    )
    return 1, len(shared)


# --- Self-check ---
#
# EVERY CASE BELOW HAS AN ANSWER THAT DOES NOT COME FROM THIS MODULE. The Wilson
# endpoints are the published ones for those counts, the tied correlation is
# computed by hand in the comment beside it, the permutation counts are derived
# combinatorially rather than read off the enumeration, and the two bootstrap
# fixtures have resample distributions small enough to write down. A statistic
# checked only against itself would agree with itself while being wrong.


class _Landscape(NamedTuple):
    """The three fields ``puzzle_outcome`` reads off a PuzzleAnalysis.

    A fixture rather than a real landscape because the layer under this one has
    its own self-check: ``analysis.py`` and ``generate.py`` hold each other to
    the same difficulty, ``runlog.py`` holds a reconstructed play to the battle
    the game recorded, and what is left for this module to be wrong about is the
    arithmetic it does on rows that are already right.
    """

    difficulty: float
    worst_value: int
    best_value: int


def _fixture_rows(puzzle_id, plays):
    """ScoredPlacement rows for one puzzle, from (value, [(chooser, regret)...]).

    The whole-play regret is the sum of the placement regrets, which is what
    ``analysis.score_play`` makes it: the regrets telescope over the prefixes,
    so a fixture that set them independently would be a fixture of a game that
    does not exist.
    """
    rows = []
    for attempt, (value, placements) in enumerate(plays, 1):
        whole = sum(regret for _, regret in placements)
        for number, (chooser, regret) in enumerate(placements, 1):
            rows.append(
                runlog.ScoredPlacement(
                    puzzle_id=puzzle_id,
                    config="FIXTURE",
                    attempt=attempt,
                    difficulty=0.0,
                    value=value,
                    whole_play_regret=whole,
                    number=number,
                    placement="A@0,%d" % number,
                    chooser=chooser,
                    regret=regret,
                )
            )
    return rows


def _fixture_arm(name, is_null, puzzles, rng):
    """An Arm assembled from fixture rows, through the real reduction."""
    outcomes = []
    rows_total = []
    for puzzle_id, landscape, plays in puzzles:
        rows = _fixture_rows(puzzle_id, plays)
        rows_total.extend(rows)
        outcomes.append(puzzle_outcome(rows, landscape, rng))
    by_model = sum(1 for row in rows_total if row.chooser == runlog.MODEL)
    by_fallback = sum(1 for row in rows_total if row.chooser == runlog.FALLBACK)
    return Arm(
        name=name,
        path="fixture",
        is_null=is_null,
        suite_ids=tuple(puzzle_id for puzzle_id, _, _ in puzzles),
        landscapes={puzzle_id: landscape for puzzle_id, landscape, _ in puzzles},
        unfinished=(),
        outcomes=tuple(outcomes),
        placements=len(rows_total),
        model_placements=by_model,
        fallback_placements=by_fallback,
        unstated_placements=len(rows_total) - by_model - by_fallback,
        attempts=sum(outcome.attempts for outcome in outcomes),
    )


def _monotone_arm(name, is_null, chooser, win_counts, rng):
    """Five puzzles of ten attempts, whose wins are ``win_counts`` in file order.

    Difficulty ascends with the list, so a win_counts that ascends is a
    perfectly monotone arm and any other order is not. Placement regret is made
    to mirror the wins, so one fixture drives every headline outcome at once.
    """
    puzzles = []
    for index, wins in enumerate(win_counts):
        plays = []
        for attempt in range(10):
            won = attempt < wins
            regret = 0 if won else 5 - index
            plays.append((1 if won else -1, [(chooser, regret), (chooser, regret)]))
        puzzles.append(
            ("p%d" % index, _Landscape(0.1 + 0.2 * index, -2, 2 + index), plays)
        )
    return _fixture_arm(name, is_null, puzzles, rng)


def _fixture_column(values, direction=+1, best=1.0, used=None):
    """One Column over difficulty 1..n, for the cases that are about ``verdict``.

    ``used`` is separate so a column with fewer values than the arm had puzzles
    can be built, which is what the "too few puzzles" branch is about.
    """
    outcome = Outcome("fixture", direction, "none", best, None)
    total = len(values) if used is None else used
    if len(values) < 3:
        return Column(outcome, None, tuple(values), len(values), total - len(values))
    xs = list(range(1, len(values) + 1))
    return Column(
        outcome,
        permutation_test(xs, list(values), direction),
        tuple(values),
        len(values),
        total - len(values),
    )


def _self_check(args):
    """Hold every statistic here to an input whose answer is known without it."""
    failed = []

    def expect(name, ok, detail=""):
        print("%-58s %s" % (name, "ok" if ok else "FAILED"))
        if not ok:
            print("    %s" % detail)
            failed.append(name)

    def close(a, b, tolerance=1e-9):
        return a is not None and abs(a - b) <= tolerance

    # 1. Wilson, against the endpoints published for these counts. 0 of 10 is
    # the case a normal approximation gets visibly wrong: it reports an interval
    # of zero width, and Wilson reports 0 to 0.2775.
    low, high = generate.wilson_interval(0, 10)
    expect(
        "wilson 0/10 is the published 0.0000 to 0.2775",
        close(low, 0.0, 1e-9) and close(high, 0.2775, 1e-4),
        "got %.5f to %.5f" % (low, high),
    )
    low, high = generate.wilson_interval(5, 10)
    expect(
        "wilson 5/10 is the published 0.2366 to 0.7634",
        close(low, 0.2366, 1e-4) and close(high, 0.7634, 1e-4),
        "got %.5f to %.5f" % (low, high),
    )

    # 2. Midranks. Two values tied across ranks 1 and 2 both take 1.5, and the
    # column still totals 1+2+3+4+5.
    ranks = midranks([3, 1, 1, 5, 4])
    expect(
        "midranks share a tie and keep the rank total",
        ranks == [3.0, 1.5, 1.5, 5.0, 4.0] and sum(ranks) == 15.0,
        "got %r" % ranks,
    )

    # 3. The three degenerate correlations, each known by construction.
    expect(
        "spearman of a perfectly ordered pair is +1",
        close(spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]), 1.0),
    )
    expect(
        "spearman of a reversed pair is -1",
        close(spearman([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]), -1.0),
    )
    expect(
        "spearman against a constant column is undefined, not zero",
        spearman([1, 2, 3, 4, 5], [7, 7, 7, 7, 7]) is None,
    )

    # 4. Ties, computed by hand. y ranks are 1.5, 1.5, 3, 4, 5 against x ranks
    # 1..5. Covariance of the centred ranks is 3 + 1.5 + 0 + 1 + 4 = 9.5, the x
    # spread is sqrt(10) and the y spread is sqrt(9.5), so rho = 9.5/sqrt(95) =
    # 0.9746794. The 1 - 6*sum(d^2)/(n^3-n) shortcut gives 0.975 here, which is
    # close enough to look right and is not the same number.
    expect(
        "spearman under ties is 9.5/sqrt(95), by midranks and not the shortcut",
        close(spearman([1, 2, 3, 4, 5], [1, 1, 3, 4, 5]), 9.5 / math.sqrt(95.0), 1e-12),
        "got %r" % spearman([1, 2, 3, 4, 5], [1, 1, 3, 4, 5]),
    )

    # 5. The exact null. 5! = 120 pairings, and the perfectly ordered one is the
    # single most extreme of them, so its one-sided p is 1/120 and that is also
    # the floor.
    perfect = permutation_test([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], +1)
    expect(
        "n=5 enumerates 120 pairings and the floor is 1/120 = 0.0083",
        perfect.orderings == 120 and close(perfect.p_one, 1 / 120.0)
        and close(perfect.floor, 1 / 120.0) and close(perfect.rho, 1.0),
        "got %r" % (perfect,),
    )
    # 6. A known-p case derived combinatorially. Swapping the last two ranks
    # gives sum(d^2) = 2 and rho = 1 - 12/120 = 0.9. The pairings at least that
    # extreme are exactly the identity and the four adjacent transpositions,
    # each of which also has sum(d^2) = 2, so there are 5 of them and p = 5/120.
    swapped = permutation_test([1, 2, 3, 4, 5], [1, 2, 3, 5, 4], +1)
    expect(
        "rho 0.9 at n=5 has exact one-sided p 5/120 = 0.0417",
        close(swapped.rho, 0.9) and close(swapped.p_one, 5 / 120.0),
        "got rho %r p %r" % (swapped.rho, swapped.p_one),
    )
    # 7. Direction is an argument, not something read off the data. The reversed
    # pair is the least extreme pairing in the rising direction, so every one of
    # the 120 is at least as extreme and p is 1. Two-sided it is 2/120, because
    # exactly two pairings reach |rho| = 1: the ordered one and this one.
    reversed_up = permutation_test([1, 2, 3, 4, 5], [5, 4, 3, 2, 1], +1)
    reversed_down = permutation_test([1, 2, 3, 4, 5], [5, 4, 3, 2, 1], -1)
    expect(
        "a reversed pair reads p 1.0 rising, 1/120 falling, 2/120 two-sided",
        close(reversed_up.p_one, 1.0) and close(reversed_down.p_one, 1 / 120.0)
        and close(reversed_up.p_two, 2 / 120.0),
        "got %r, %r, %r"
        % (reversed_up.p_one, reversed_down.p_one, reversed_up.p_two),
    )
    # 8. Ties raise the floor above 0.05, and the test must say so rather than
    # report a p it could never have reached. With outcomes 1,1,1,2,2 the two
    # highest values can sit in the top two slots in 2! * 3! = 12 of the 120
    # pairings, and every one of those 12 attains the maximum rho.
    tied_column = _fixture_column([1, 1, 1, 2, 2], best=9.0)
    tied = tied_column.result
    tied_verdict = verdict(tied_column)
    expect(
        "a tied outcome puts the floor at 12/120 = 0.1, and the verdict blames ties",
        close(tied.floor, 12 / 120.0)
        and tied_verdict.text.startswith("NOT TESTED, CANNOT FIRE")
        and "TIES in this column" in tied_verdict.text
        and "ceiling" not in tied_verdict.text
        and not tied_verdict.tested,
        "floor %r verdict %r" % (tied.floor, tied_verdict.text),
    )
    # 8a. THE SAME FLOOR FOR A DIFFERENT REASON. A win rate tied at 1.000 on four
    # of five puzzles is a suite whose easy end does not discriminate, and the
    # message has to separate that from a tie anywhere else in the column.
    ceiling = verdict(_fixture_column([0.7, 1.0, 1.0, 1.0, 1.0], best=1.0))
    expect(
        "ties AT the best attainable value are named as the suite's ceiling",
        ceiling.text.startswith("NOT TESTED, CANNOT FIRE")
        and "4 of the 5 puzzles sit at the best attainable value" in ceiling.text
        and "ceiling" in ceiling.text,
        "got %r" % ceiling.text,
    )
    # 8b. THE OTHER WAY A FLOOR GETS ABOVE 0.05, AND THE COMMON ONE. Three
    # puzzles is 3! = 6 pairings, so the untied floor is already 1/6 = 0.1667.
    # The column below has no tie in it at all, and the message must not say it
    # does. Four puzzles is 1/24 = 0.0417 and passes, which is what makes 3 the
    # boundary rather than a general small-n complaint.
    thin = verdict(_fixture_column([1, 2, 3], used=5))
    expect(
        "a 3-puzzle column cannot fire on n alone, and the cause names n, not ties",
        thin.text.startswith("NOT TESTED, CANNOT FIRE")
        and "only 3 puzzles" in thin.text
        and "TIES" not in thin.text
        and not thin.tested,
        "got %r" % thin.text,
    )
    expect(
        "the same column at 4 puzzles has floor 1/24 = 0.0417 and does fire",
        close(_fixture_column([1, 2, 3, 4]).result.floor, 1 / 24.0)
        and verdict(_fixture_column([1, 2, 3, 4])).tested,
        "got %r" % (_fixture_column([1, 2, 3, 4]).result,),
    )
    # 9. A constant outcome has no ordering, so no pairing is more extreme. A
    # constant at the BEST attainable value is a saturated column and says
    # something; a constant anywhere else says nothing, and the two must not
    # arrive in the same words.
    flat = _fixture_column([4, 4, 4, 4, 4], best=1.0)
    expect(
        "a constant outcome tests as rho None and p 1.0",
        flat.result.rho is None and flat.result.p_one == 1.0
        and verdict(flat).text.startswith("NOT TESTED, FLAT"),
    )
    saturated = verdict(_fixture_column([1.0, 1.0, 1.0, 1.0, 1.0], best=1.0))
    expect(
        "a win rate of 1.000 everywhere reads as SATURATED, not as the same flat column",
        saturated.text.startswith("NOT TESTED, SATURATED")
        and "ceiling" in saturated.text
        and not saturated.tested
        and not saturated.predicted,
        "got %r" % saturated.text,
    )
    expect(
        "a regret of 0.000 everywhere is saturated too, on the same rule",
        verdict(_fixture_column([0.0] * 5, direction=-1, best=0.0)).text.startswith(
            "NOT TESTED, SATURATED"
        ),
    )
    # 9c. Too few puzzles to run the test at all is a third kind of untested, and
    # it is not a verdict about the data.
    absent = verdict(_fixture_column([1, 2], used=5))
    expect(
        "2 of 5 puzzles with a value reads as NOT TESTED and neither tested nor predicted",
        absent.text.startswith("NOT TESTED:") and not absent.tested
        and not absent.predicted,
        "got %r" % absent.text,
    )

    # 10. A degenerate bootstrap sample. Every resample of a sample with one
    # value is that value, so the interval is a point and nothing is censored.
    rng = random.Random(args.seed)
    point = bootstrap_ci(((5,),) * 8, rng)
    expect(
        "a bootstrap of a constant sample is the point, not an interval",
        point == Interval(5.0, 5.0, 0),
        "got %r" % (point,),
    )
    # 11. A two-attempt sample whose whole resample distribution is writable:
    # drawing 2 of {0, 10} gives mean 0 a quarter of the time, 5 a half and 10 a
    # quarter. A quarter of 2000 is 500 draws at each end, far past the 50 the
    # 2.5% and 97.5% ranks sit at, so both endpoints are the extreme values.
    spread = bootstrap_ci(((0,), (10,)), rng)
    expect(
        "a bootstrap of {0, 10} reaches both ends, as its 1/4 tails require",
        spread.low == 0.0 and spread.high == 10.0 and spread.censored == 0,
        "got %r" % (spread,),
    )
    # 12. THE DESIGN POINT, MEASURED AND ASSERTED AT WHAT IT CLAIMS. Ten attempts
    # of five identical placements, five attempts all 0 and five all 10.
    #
    # Both widths are computable without this module. An attempt-unit resample
    # draws 10 of the 10 attempts, so its mean is 10*k/10 = k with k ~ Bin(10,
    # 0.5), whose 2.5% and 97.5% nearest-rank quantiles are 2 and 8: width 6.00.
    # A placement-unit resample draws 50 of the 50 placements, so its mean is
    # 10*k/50 with k ~ Bin(50, 0.5), whose quantiles are 18 and 32: width 2.80.
    # The ratio is 15/7 = 2.14, near the sqrt(5) = 2.24 the design point names
    # asymptotically and not equal to it, because both distributions are
    # discrete at this n.
    #
    # ASSERTED AS A BAND AROUND sqrt(5), NOT AS "OVER 1.5X". The old assertion
    # passed at 1.6, so the unit rule could have half broken and still read ok;
    # a reversion to placement units puts the ratio at 1.0 and a band of one
    # quantile step either way separates the two without failing on the seed.
    attempts = tuple((0,) * 5 for _ in range(5)) + tuple((10,) * 5 for _ in range(5))
    placements = tuple((value,) for unit in attempts for value in unit)
    by_attempt = bootstrap_ci(attempts, rng)
    by_placement = bootstrap_ci(placements, rng)
    width_attempt = by_attempt.high - by_attempt.low
    width_placement = by_placement.high - by_placement.low
    ratio = width_attempt / width_placement
    expect(
        "the attempt-unit interval is sqrt(5) = 2.24x the placement-unit one, to 1 step",
        1.9 <= ratio <= 2.5,
        "attempts %.3f wide, placements %.3f wide, ratio %.3f"
        % (width_attempt, width_placement, ratio),
    )
    expect(
        "and both widths are the binomial quantile spreads, 6.00 and 2.80",
        close(width_attempt, 6.0, 1e-9) and close(width_placement, 2.8, 1e-9),
        "attempts %.3f wide, placements %.3f wide" % (width_attempt, width_placement),
    )
    print(
        "    attempt-unit interval %s is %.2fx the width of the placement-unit "
        "interval %s, which is what a placement-unit bootstrap would have "
        "understated it by"
        % (_ci(by_attempt, "%.2f"), ratio, _ci(by_placement, "%.2f"))
    )
    # 13. A difference bootstrap of two identical samples straddles zero, and of
    # two separated ones does not.
    same = bootstrap_difference(((1,), (1,), (1,)), ((1,), (1,), (1,)), rng)
    apart = bootstrap_difference(((9,),) * 6, ((1,),) * 6, rng)
    expect(
        "a difference bootstrap is 0 on identical samples and 8 on separated ones",
        same == Interval(0.0, 0.0, 0) and apart == Interval(8.0, 8.0, 0),
        "got %r and %r" % (same, apart),
    )

    # 14. The chooser split, on rows built so the two attributions cannot agree:
    # every model placement gives up 0 and every fallback placement gives up 9.
    mixed = _fixture_rows(
        "split",
        [(1, [(runlog.MODEL, 0), (runlog.FALLBACK, 9)]) for _ in range(4)],
    )
    outcome = puzzle_outcome(mixed, _Landscape(0.5, -2, 2), rng)
    expect(
        "the model-chosen mean charges the model nothing and the pooled mean 4.5",
        close(outcome.mean_regret_model, 0.0) and close(outcome.mean_regret_all, 4.5)
        and outcome.model_placements == 4 and outcome.pure_attempts == 0,
        "model %r all %r pure %d"
        % (outcome.mean_regret_model, outcome.mean_regret_all, outcome.pure_attempts),
    )
    # 15. Whole-play regret is an attempt-level outcome and is NOT filtered by
    # chooser, because an attempt has one outcome that both choosers produced.
    # Each attempt above gave up 0 + 9.
    expect(
        "whole-play regret stays unfiltered at 9, and win rate at 1.0",
        close(outcome.mean_play_regret, 9.0) and close(outcome.win_rate, 1.0),
        "%r %r" % (outcome.mean_play_regret, outcome.win_rate),
    )
    # 16. The normalizer divides by the puzzle's own span and is offered beside
    # the raw number, never in place of it. Span here is 2 - -2 = 4.
    expect(
        "regret over span divides by this puzzle's own range and not a pooled one",
        close(outcome.normalized_play_regret, 9.0 / 4.0),
        "got %r" % outcome.normalized_play_regret,
    )

    # 17. The whole reduction, end to end, on an arm built to be perfect and one
    # built to be scrambled. Wins rise with difficulty in the first and do not in
    # the second, and nothing but the ordering differs between them.
    perfect_arm = _monotone_arm(
        "perfect", False, runlog.MODEL, [0, 2, 5, 8, 10], rng
    )
    scrambled_arm = _monotone_arm(
        "scrambled", False, runlog.MODEL, [5, 10, 0, 8, 2], rng
    )
    perfect_win = relationship(perfect_arm, _OUTCOMES[0])
    expect(
        "a perfectly ordered arm reports rho +1 at the 1/120 floor on 5 puzzles",
        perfect_win.used == 5 and close(perfect_win.result.rho, 1.0)
        and close(perfect_win.result.p_one, 1 / 120.0)
        and verdict(perfect_win).text.startswith("PREDICTS: perfectly monotone")
        and verdict(perfect_win).tested and verdict(perfect_win).predicted,
        "%r %s" % (perfect_win.result, verdict(perfect_win).text),
    )
    scrambled_win = relationship(scrambled_arm, _OUTCOMES[0])
    expect(
        "a scrambled arm is TESTED and does not predict, which is not the same as untested",
        verdict(scrambled_win).text.startswith("DOES NOT PREDICT")
        and verdict(scrambled_win).tested and not verdict(scrambled_win).predicted,
        "%r %s" % (scrambled_win.result, verdict(scrambled_win).text),
    )
    # 18. Regret is tested in the falling direction, so the same perfect arm has
    # to come out at the floor there too and with the opposite sign.
    perfect_regret = relationship(perfect_arm, _OUTCOMES[1])
    expect(
        "the same arm's placement regret tests at the floor in the falling direction",
        close(perfect_regret.result.rho, -1.0)
        and close(perfect_regret.result.p_one, 1 / 120.0),
        "%r" % (perfect_regret.result,),
    )
    # 19. A puzzle with nothing in a column is dropped and counted, not zeroed.
    # A zero there would be the best possible regret on the puzzle the model
    # never played.
    null_arm = _monotone_arm("all-fallback", True, runlog.FALLBACK, [0, 2, 5, 8, 10], rng)
    empty_model = relationship(null_arm, _OUTCOMES[1])
    expect(
        "an arm with no model-chosen placements drops all 5 rather than scoring 0",
        empty_model.result is None and empty_model.dropped == 5 and empty_model.used == 0,
        "%r dropped %d used %d"
        % (empty_model.result, empty_model.dropped, empty_model.used),
    )
    expect(
        "the null curve's counted placement column is the all-placements one",
        _counted_labels(null_arm)[2] == "mean placement regret (all placements)"
        and _counted_labels(perfect_arm)[2]
        == "mean placement regret (model-chosen)",
    )
    # 19b. THE COUNTED SET IS FOUR COLUMNS AND NO NORMALIZER IS PREFERRED. Two
    # questions, and regret under each of its three normalizers, so the choice
    # the output calls open is not closed by which column carries a star.
    counted = _counted_labels(perfect_arm)
    normalizers = [
        outcome.normalizer for outcome in _OUTCOMES if outcome.label in counted
    ]
    expect(
        "the counted set is the win rate plus all three regret normalizers, none starred",
        counted[0] == "win rate" and len(counted) == 4
        and sorted(normalizers) == ["none", "none", "play length", "value span"],
        "%r %r" % (counted, normalizers),
    )
    # 20. Attempts are the unit at the reduction layer too: ten attempts of two
    # placements each must count as ten, not twenty.
    expect(
        "the reduction counts attempts as attempts and placements as placements",
        perfect_arm.attempts == 50 and perfect_arm.placements == 100
        and perfect_arm.outcomes[0].attempts == 10,
        "%d attempts, %d placements" % (perfect_arm.attempts, perfect_arm.placements),
    )
    # 20b. THE UNDISCLOSED NORMALIZER, HELD TO THE IDENTITY THE REPORT PRINTS.
    # Every attempt above is two placements, so placements per attempt is 2 and
    # the placement column has to be the whole-play column halved, exactly.
    scaled = perfect_arm.outcomes[1]
    expect(
        "mean placement regret is mean whole-play regret over placements per attempt",
        close(scaled.placements_per_attempt, 2.0)
        and close(
            scaled.mean_regret_all,
            scaled.mean_play_regret / scaled.placements_per_attempt,
        ),
        "play %r / %r vs placement %r"
        % (scaled.mean_play_regret, scaled.placements_per_attempt, scaled.mean_regret_all),
    )
    # 20c. AND THAT DIVISOR IS NOT A CONSTANT, which is why dividing by it can
    # reorder the puzzles. Three attempts of one placement beside three of five
    # is 3.0 per attempt on one puzzle against 1.0 on another, with the same
    # whole-play regret of 5 on both: the raw column ties and the normalized one
    # does not.
    long_rows = _fixture_rows("long", [(1, [(runlog.MODEL, 1)] * 5) for _ in range(3)])
    short_rows = _fixture_rows("short", [(1, [(runlog.MODEL, 5)]) for _ in range(3)])
    long_puzzle = puzzle_outcome(long_rows, _Landscape(0.5, -2, 2), rng)
    short_puzzle = puzzle_outcome(short_rows, _Landscape(0.9, -2, 2), rng)
    expect(
        "two puzzles tied on whole-play regret are separated by the play-length divisor",
        close(long_puzzle.mean_play_regret, short_puzzle.mean_play_regret)
        and close(long_puzzle.mean_regret_all, 1.0)
        and close(short_puzzle.mean_regret_all, 5.0),
        "%r %r vs %r %r"
        % (
            long_puzzle.mean_play_regret,
            long_puzzle.mean_regret_all,
            short_puzzle.mean_play_regret,
            short_puzzle.mean_regret_all,
        ),
    )
    # 20d. COVERAGE IS CARRIED, NOT INFERRED FROM THE ROWS. An arm built over
    # three puzzles of a five-puzzle suite has to name the two it did not play,
    # because every table it prints looks the same either way.
    partial = perfect_arm._replace(
        suite_ids=perfect_arm.suite_ids + ("p5", "p6"), unfinished=("puzzle p6 attempt 1",)
    )
    expect(
        "an arm that played 5 of a 7-puzzle suite names the 2 it missed",
        partial.missing_ids == ("p5", "p6") and perfect_arm.missing_ids == (),
        "%r" % (partial.missing_ids,),
    )
    # 20e. THE DIFFERENCE TEST'S SIDE, HELD TO THE DERIVATION. An arm whose
    # advantage over the null shrinks towards zero as the puzzle gets easier is
    # the predicted shape, so it must test at the floor; the opposite shape must
    # read p 1.0. Wired to -1 this was exactly backwards.
    shrinking = [(0.1, -3.0), (0.3, -2.0), (0.5, -1.5), (0.7, -0.5), (0.9, 0.5)]
    widening = [(x, -y) for x, y in shrinking]
    expect(
        "an advantage shrinking towards 0 as difficulty rises tests at the 1/120 floor",
        close(difference_relationship(shrinking).rho, 1.0)
        and close(difference_relationship(shrinking).p_one, 1 / 120.0)
        and close(difference_relationship(widening).p_one, 1.0),
        "shrinking %r widening %r"
        % (difference_relationship(shrinking), difference_relationship(widening)),
    )
    # 21. The exact test is a promise, so it refuses a suite it cannot enumerate
    # rather than switching to a sampled one.
    try:
        permutation_test(list(range(9)), list(range(9)), +1)
    except ValueError as error:
        expect("nine puzzles is refused rather than sampled", True)
        print("    %s" % error)
    else:
        expect("nine puzzles is refused rather than sampled", False, "it did not refuse")

    print()
    if failed:
        print("%d CHECKS FAILED: %s" % (len(failed), "; ".join(failed)))
        return 1
    print("every check passed, each against an answer this module did not compute")
    return 0


# --- The stepwise agent, which is not the distribution difficulty is over ---

# The seed and the sample size behind the stepwise win rates the module
# docstring quotes. Named here rather than left in the docstring so the command
# and the prose cannot drift apart.
STEPWISE_SEED = 20260910
STEPWISE_PLAYS = 20000


def stepwise_play(puzzle, rng):
    """One complete legal play, drawn a random affordable type and empty square
    at a time.

    This is ``LlmFallback.pick_random_placement``'s rule, and it is a DIFFERENT
    distribution over the same plays from the uniform-over-complete-plays one
    ``difficulty`` counts: a short play and a long one are equally likely here
    per step, not per play. The stopping rule is ``prep.enumerate_plays``', so
    every play this returns is a key of the landscape and a play that drifted
    from the rule raises rather than being scored.

    ``equivalence.random_play`` is the same rule against the engine that module
    is sweeping, which is a module-level global it installs at run time. Calling
    it here would mean either importing under whichever engine that sweep last
    chose or reaching into its globals, so the rule is written out once more
    against the shipped engine instead. Unifying the two means moving it down
    into ``prep``, which is a change to a module this one does not own.
    """
    types = tuple(dict.fromkeys(puzzle.llm_shop))
    gold = puzzle.llm_gold
    used = set()
    play = []
    while True:
        affordable = [item for item in types if gold >= engine.UNIT_COSTS[item]]
        free = [square for square in prep.LLM_SQUARES if square not in used]
        if not affordable or not free:
            return tuple(play)
        unit_type = rng.choice(affordable)
        square = rng.choice(free)
        gold -= engine.UNIT_COSTS[unit_type]
        used.add(square)
        play.append(prep.Placement(unit_type, square))


def _stepwise(args):
    """Difficulty against the stepwise agent's measured win rate, per puzzle."""
    suite = prep.load_suite(args.puzzles)
    rows = []
    for puzzle in suite.puzzles():
        # Enumerated here rather than read from an artifact directory, so the
        # figure the module docstring quotes cannot come from a stale one. The
        # shipped suite is 11,550 plays and about 1.3 seconds all told.
        landscape = analysis.analyze_puzzle(puzzle)
        rng = stream(args.seed, puzzle.id)
        wins = 0
        for _ in range(args.plays):
            key = analysis.encode_play(stepwise_play(puzzle, rng))
            if landscape.play_values[key] > 0:
                wins += 1
        rate = wins / args.plays
        error = math.sqrt(rate * (1.0 - rate) / args.plays)
        rows.append(
            (
                puzzle.id,
                "%.4f" % landscape.difficulty,
                "%.4f" % rate,
                "+- %.4f" % error,
                "%.2fx" % (rate / landscape.difficulty) if landscape.difficulty else "n/a",
            )
        )
    print(
        "DIFFICULTY IS P(win) UNDER SAMPLING UNIFORM OVER COMPLETE PLAYS. The stepwise "
        "column is P(win) under a random affordable type and a random empty square each "
        "turn, which is LlmFallback's rule and a different distribution over the same "
        "plays."
    )
    print(
        "%d plays per puzzle, seed %d, one stream per puzzle named by the puzzle so a "
        "figure does not depend on which puzzles were sampled before it."
        % (args.plays, args.seed)
    )
    _grid(("puzzle", "difficulty", "stepwise", "std error", "ratio"), rows)
    print(
        "  the std error is the binomial one at this sample size, and it is what says "
        "which of the ratios is a real gap and which is sampling noise. THE NULL ARM'S "
        "WIN RATE IS NOT PREDICTED TO EQUAL DIFFICULTY; it is predicted to be MONOTONE "
        "in it, and that is all the comparison tests."
    )
    return 0


# --- CLI ---


def _arm_spec(text):
    name, sep, path = text.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(
            "%r is not NAME=PATH. The log does not record which model played it, so "
            "the name is yours to give" % text
        )
    return (name, path)


def _compare(args):
    specs = [(name, path, True) for name, path in args.null] + [
        (name, path, False) for name, path in args.arm
    ]
    if not specs:
        print("no arms given: pass at least one --null or --arm", file=sys.stderr)
        return 1
    names = [name for name, _, _ in specs]
    if len(set(names)) != len(names):
        print("two arms share a name, so the report could not tell them apart",
              file=sys.stderr)
        return 1
    if args.arm and not args.null:
        print(
            "model arms were given and no --null. THE NULL CURVE IS NOT OPTIONAL: "
            "without a random agent on the same puzzles, a difficulty-to-regret slope "
            "is equally well explained by the puzzles getting structurally harder, and "
            "this module will not print a comparison that cannot tell those apart",
            file=sys.stderr,
        )
        return 1

    arms = []
    for name, path, is_null in specs:
        try:
            arms.append(
                build_arm(name, path, is_null, args.puzzles, args.artifacts, args.seed)
            )
        except (
            runlog.RunNotMeasurable,
            prep.SuiteNotMeasurable,
            analysis.ArtifactNotCurrent,
            OSError,
        ) as error:
            print("arm %s (%s): %s" % (name, path, error), file=sys.stderr)
            print("nothing compared", file=sys.stderr)
            return 1

    print("L10: DOES THE ORACLE'S COMPUTED DIFFICULTY PREDICT OBSERVED PERFORMANCE?")
    print()
    _report_suite(arms, args.puzzles)
    landscapes = suite_landscapes(arms)
    tests = could_fire = intervals = differences = 0
    for arm in arms:
        spent = _report_arm(arm, landscapes)
        tests += spent[0]
        could_fire += spent[1]
        intervals += spent[2]
    nulls = [arm for arm in arms if arm.is_null]
    for arm in arms:
        if not arm.is_null:
            for null in nulls:
                spent = _report_against_null(arm, null, args.seed)
                tests += spent[0]
                could_fire += spent[0]
                differences += spent[1]
    _report_multiplicity(tests, could_fire, intervals, differences)
    return 0


def _report_multiplicity(tests, could_fire, intervals, differences):
    """What the whole run spent, counted rather than estimated.

    No correction is applied and none is implied. A reader who wants one needs
    the number of tests that were actually run, and a report that prints a
    verdict per arm and never says how many verdicts it printed does not give
    them that.
    """
    inflation = 1.0 - 0.95 ** could_fire if could_fire else 0.0
    print()
    print("MULTIPLE COMPARISONS ACROSS THIS WHOLE RUN")
    print(
        "  %d exact one-sided permutation tests at alpha 0.05, of which %d were on "
        "columns whose floor is at or below 0.05 and so could ever have rejected. %d "
        "bootstrap 95%% intervals were printed, %d of them the arm-minus-null "
        "differences that are read for whether they exclude zero."
        % (tests, could_fire, intervals + differences, differences)
    )
    print(
        "  NOTHING ABOVE IS CORRECTED FOR THIS AND NO CORRECTION IS IMPLIED. Were the "
        "%d tests that could fire independent, alpha 0.05 would give a %.0f%% chance of "
        "at least one spurious rejection in this run. THEY ARE NOT INDEPENDENT: three "
        "of the columns per arm are one quantity under three normalizers and every arm "
        "is tested against the same difficulty axis, so that figure is an upper bound "
        "on the inflation and not an estimate of it."
        % (could_fire, 100.0 * inflation)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Test whether computed difficulty predicts what agents scored."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    compare = sub.add_parser(
        "compare", help="per-puzzle outcomes and the difficulty relationship, per arm"
    )
    compare.add_argument(
        "--null",
        action="append",
        default=[],
        type=_arm_spec,
        metavar="NAME=PATH",
        help="a run with no model in it, whose placements are all LlmFallback's. "
        "It is the null curve and it is required whenever a model arm is given",
    )
    compare.add_argument(
        "--arm",
        action="append",
        default=[],
        type=_arm_spec,
        metavar="NAME=PATH",
        help="a model run. Repeatable; the log does not record the model, so NAME is "
        "whatever you call it",
    )
    compare.add_argument(
        "--puzzles",
        default=prep.DEFAULT_PUZZLE_PATH,
        help="the suite every arm was played on (default: the game's own suite)",
    )
    compare.add_argument(
        "--artifacts",
        default=analysis.DEFAULT_OUT_DIR,
        help="this suite's landscapes (default: oracle/artifacts). Build them first: "
        "a puzzle with no artifact is enumerated once per arm, twice over",
    )
    compare.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="the bootstrap's seed. Every arm gets its own stream seeded from this "
        "and its name, so an arm's intervals do not change when another arm is added "
        "beside it (default: %d)" % DEFAULT_SEED,
    )
    compare.set_defaults(handler=_compare)

    check = sub.add_parser(
        "self-check",
        help="hold every statistic here to an input whose answer is known without it",
    )
    check.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="the bootstrap's seed"
    )
    check.set_defaults(handler=_self_check)

    step = sub.add_parser(
        "stepwise",
        help="difficulty against the measured win rate of LlmFallback's own sampler, "
        "which is what says the two are not the same number",
    )
    step.add_argument(
        "--puzzles",
        default=prep.DEFAULT_PUZZLE_PATH,
        help="the suite to measure (default: the game's own suite)",
    )
    step.add_argument(
        "--plays",
        type=int,
        default=STEPWISE_PLAYS,
        help="stepwise plays sampled per puzzle (default: %d)" % STEPWISE_PLAYS,
    )
    step.add_argument(
        "--seed",
        type=int,
        default=STEPWISE_SEED,
        help="the sampler's seed (default: %d, which is the one the module docstring's "
        "figures were measured at)" % STEPWISE_SEED,
    )
    step.set_defaults(handler=_stepwise)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
