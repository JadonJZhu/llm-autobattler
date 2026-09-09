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

An output directory holds the analysis of exactly one suite. The CLI writes one
``puzzle_<id>.json`` per puzzle and a ``suite.json`` naming the suite file they
were built from, and it removes any artifact left over from a suite analysed
there before.

``load_analysis`` refuses an artifact whose numbers are not the numbers the
reader would get by running the analysis now. Three things decide those numbers:
the puzzle definition, which the artifact carries; the suite file, which the
manifest names and which is re-read and re-loaded on every read, since a copy
taken when the artifact was written would agree with it forever; and the code,
which every artifact records as ``code``, the sha256 of the source of every
module this one reaches by import. So a reader who did not run the analysis
cannot score plays against a landscape of another puzzle, of a suite the file no
longer states, or of rules this code no longer implements.
"""

import argparse
import ast
import hashlib
import importlib.util
import json
import sys
import sysconfig
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import NamedTuple

import engine
import prep

# (plays, wins) for each puzzle in the game's own suite, which is no longer the
# study's experimental suite but the fixture the oracle is checked against. The
# three play counts were agreed on by a hand derivation, by this enumeration, and
# by driving all 11,550 plays through the real headless TurnManager, Shop and
# GameBoard. The three win counts are what this module's landscape pass measured
# over the shipped file on 2026-09-08, and generate.py's separate counter agrees
# with all six under ``generate.py self-check``.
#
# They detect change rather than establish correctness: a mismatch means the
# puzzle file, the prep port or the engine moved under the study, which
# invalidates every landscape built before the move, so the CLI writes nothing at
# all rather than artifacts that silently describe a different game. An id named
# here and missing from the shipped suite is the same failure wearing a rename,
# so it is fatal too.
#
# The play count is an agent-side number: it follows from the agent's gold and
# shop and from nothing the opponent does. The win count is what carries the
# opponent, so a moved unit, a swapped type or a changed opponent shop that still
# fields every listed unit is caught here and nowhere else. An opponent that does
# NOT field what it lists is caught by prep.check_queue_lands instead, and
# anything the loader discarded, at any level, by prep.Suite.puzzles; both are
# properties rather than golden numbers and hold for any suite, shipped or
# generated.
EXPECTED_COUNTS = {"1": (3240, 103), "2": (1080, 4), "3": (7230, 311)}

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "artifacts"

# What the CLI writes into the output directory, and the only names it removes
# from one. The manifest names the suite file, which is what ties a directory to
# a suite rather than to a set of filenames: generate.py names its puzzles by
# attempt number, so two suites at different seeds both hold a "gen1" and the
# name says nothing about which.
MANIFEST_NAME = "suite.json"
ARTIFACT_GLOB = "puzzle_*.json"

# The source of every number in an artifact. Its bytes ARE the version, so
# nothing has to be remembered or bumped and no edit to any of it can go
# unrecorded. It is deliberately blunt: a comment moved anywhere in it reads as
# a different oracle and costs a re-run, which is the price of a fingerprint
# that cannot be wrong in the other direction.
#
# Which files those are is read out of the import statements rather than listed
# here, because a list is only ever right about the code that existed when it
# was written: a module split out of engine or prep later would hold rules that
# decide the numbers and be fingerprinted by nobody.
#
# REACHED BY IMPORT FROM THIS MODULE is the membership rule, not loaded beside
# it. A module can only change these numbers if this one can call into it, and
# an import written inside a function body is an import statement like any
# other, so following the statements covers a module reached only lazily. The
# other direction matters as much: generate.py and equivalence.py import this
# module, and are loaded whenever they are the command being run, but nothing
# here can reach them and none of their code decides a number. Hashing what
# happens to be loaded would make an artifact written by generate.py unreadable
# by analysis.py, which is a false alarm rather than a caught change.
#
# A name is resolved to the file this interpreter has for it, so a run against a
# different copy of prep or engine fingerprints that copy. What resolves into
# the interpreter's own library tree is left out, so THE FINGERPRINT COVERS THIS
# PROJECT'S CODE AND NOT THE PYTHON IT RUNS ON: a standard library or installed
# package that changed under the oracle reads as unchanged here.
_INTERPRETER_LIBRARY = tuple(
    Path(sysconfig.get_paths()[location]).resolve()
    for location in ("stdlib", "platstdlib", "purelib", "platlib")
)


def _imported_modules(source, path):
    """What one source file imports, as ``(module, names taken out of it)``.

    ``ast.walk`` reaches an import wherever it is written, so an import inside a
    function body counts the same as one at the top of the file. The names of a
    ``from X import Y`` come back beside X because Y may itself be a module, and
    are only worth resolving when X turns out to be ours.
    """
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, ()
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ImportError(
                    "%s uses a relative import, which the oracle's flat layout "
                    "cannot run and this cannot resolve to a file" % path
                )
            yield node.module, tuple(alias.name for alias in node.names)


def _source_file(name, required, importer):
    """The file behind a module name, or None if it is not this project's code.

    ``sys.modules`` is asked first so that a module already imported is
    fingerprinted as the copy that was imported, which is what equivalence.py's
    ``--engine`` substitutes. A name the source states as a module and this
    cannot resolve is a hole in the fingerprint, so it is raised rather than
    passed over; a ``from X import Y`` name is not required to be one.
    """
    module = sys.modules.get(name)
    if module is not None:
        origin = getattr(module, "__file__", None)
    else:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            if required:
                raise ImportError(
                    "%s imports %s, which nothing on this interpreter resolves, so "
                    "the code behind the numbers cannot be fingerprinted whole"
                    % (importer, name)
                )
            return None
        origin = spec.origin
    if origin is None:
        # Built in, frozen, or a namespace package: no source to hash.
        return None
    origin = Path(origin).resolve()
    if any(origin.is_relative_to(location) for location in _INTERPRETER_LIBRARY):
        return None
    return origin


def _code_fingerprint():
    """sha256 over the source of every module these numbers can come from.

    Ordered by content, so the fingerprint is a function of the code and of
    nothing else: not of where the files sit, not of the order they were
    imported in, not of which command was run.
    """
    sources = {}
    pending = [Path(__file__)]
    while pending:
        path = pending.pop().resolve()
        if path in sources:
            continue
        source = path.read_bytes()
        sources[path] = source
        for name, attributes in _imported_modules(source, path):
            found = _source_file(name, True, path)
            if found is None:
                # Not ours, so nothing inside it is ours either.
                continue
            if found not in sources:
                pending.append(found)
            for attribute in attributes:
                submodule = _source_file("%s.%s" % (name, attribute), False, path)
                if submodule is not None and submodule not in sources:
                    pending.append(submodule)
    digest = hashlib.sha256()
    for source in sorted(sources.values()):
        digest.update(hashlib.sha256(source).digest())
    return digest.hexdigest()


CODE_FINGERPRINT = _code_fingerprint()

_KEY_SEPARATOR = "|"

_TIMING_METHOD = (
    "enumeration_seconds: perf_counter around the whole landscape pass "
    "(enumerate, build board, resolve battle, record). "
    "simulation_seconds: perf_counter around a pass of engine.run_battle over "
    "pre-built boards from an evenly spaced sample of the puzzle's plays, "
    "divided by the sample size, best of several passes."
)


def is_shipped_suite(path):
    """Whether ``path`` is the game's own suite, the one the counts describe.

    EXPECTED_COUNTS holds the measured counts of the shipped puzzles and of no
    others, so the shipped file is exactly where every id in it must be present
    and match. A suite from anywhere else has no expected counts; a generated one
    is instead checked against the counts it records for itself, which is what
    ``recorded_counts`` reads.
    """
    return Path(path).resolve() == Path(prep.DEFAULT_PUZZLE_PATH).resolve()


def recorded_counts(path):
    """The play and win counts a suite file records for its own puzzles, by id.

    ``generate.py`` writes ``play_count`` and ``win_count`` beside every puzzle
    it accepts, from its own enumeration of that puzzle. Checking them against
    this module's enumeration is two independent counts of one action space, so a
    disagreement means one of the two enumerations is wrong. A file that records
    neither, the shipped suite among them, yields nothing here and is checked
    against EXPECTED_COUNTS alone.
    """
    with open(path) as handle:
        root = json.load(handle)
    raw_puzzles = root.get("puzzles", []) if isinstance(root, dict) else []

    counts = {}
    for raw in raw_puzzles:
        if isinstance(raw, dict) and "play_count" in raw and "win_count" in raw:
            counts[str(raw.get("id", "")).strip()] = (
                raw["play_count"],
                raw["win_count"],
            )
    return counts


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

    This is the definition in full as ``prep.load_suite`` produced it, so a
    landscape can be matched against the suite it claims to describe instead of
    being taken on trust. It does not fingerprint the prep port or the engine;
    the play-count check is what catches those changing.

    ``loader_difficulty`` is the integer ``difficulty`` field as
    ``prep.load_suite`` produced it, which is the only difficulty either loader
    reads. It is not the win fraction the artifact reports as ``difficulty``, and
    carries a different name so the two cannot be confused for each other. What
    it counts is a rank within one file, 1 for the easiest by win fraction to N
    for the hardest. The shipped puzzles each carry the field and are ranked that
    way across the three of them; a suite from ``generate.py`` ranks its accepted
    puzzles the same way and keeps its acceptance bin in a separate ``tier``
    field neither loader reads, which the shipped suite has no counterpart for. A
    file that omits the field falls to the loader's default of 1 throughout. So
    it identifies a puzzle within its own file and means nothing across files.
    """
    return {
        "id": puzzle.id,
        "loader_difficulty": puzzle.difficulty,
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

    Requires the puzzle to field every opponent placement it lists, then
    enumerates once, verifies the decomposition over every play, and measures
    the per-simulation cost. The queue check is here rather than in the CLI
    because this is where a puzzle becomes a value landscape, so no caller can
    reach a landscape of a puzzle that quietly fields fewer units than it reads
    as.

    Raises ``prep.QueueDoesNotLand`` for such a puzzle rather than returning a
    landscape of it, because every number below would then describe a different
    puzzle from the one the suite file states.
    """
    prep.check_queue_lands(puzzle)
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
    """The analysis as the JSON a later stage consumes without re-enumerating.

    ``puzzle`` is the definition the numbers were computed from and ``code`` the
    oracle that computed them. Together with the suite file the manifest names,
    they are what ``load_analysis`` holds the numbers to.
    """
    return {
        "puzzle_id": analysis.puzzle_id,
        "puzzle": analysis.puzzle,
        "code": CODE_FINGERPRINT,
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


class ArtifactNotCurrent(ValueError):
    """An artifact does not describe what a reader of it would compute now."""


def manifest(suite_path):
    """What ``suite.json`` records about the directory it sits in.

    The suite file the artifacts beside it were built from, and nothing else.
    Copying the puzzle definitions in here as well would put a second answer
    beside the file's own, written by the run that wrote the artifacts and so
    agreeing with them whatever the file later says.
    """
    return {"suite": str(Path(suite_path).resolve())}


def _described_suite(manifest_path):
    """The suite an output directory describes, loaded as the reader has it now.

    Returns the suite file's path and its puzzles. The manifest names the file;
    the puzzles come out of that file through ``prep.load_suite``, so what an
    artifact is compared against is the suite as it stands and as the game's own
    loader reads it, rather than anything recorded alongside the artifact.
    """
    try:
        with open(manifest_path) as handle:
            suite_path = json.load(handle)["suite"]
    except FileNotFoundError:
        raise ArtifactNotCurrent(
            "%s has no %s, so nothing says which suite the artifacts in it belong to"
            % (manifest_path.parent, MANIFEST_NAME)
        ) from None
    except (json.JSONDecodeError, KeyError) as error:
        detail = (
            "it has no 'suite' key"
            if isinstance(error, KeyError)
            else "it is not JSON: %s" % error
        )
        raise ArtifactNotCurrent(
            "%s does not read as a manifest, %s, so nothing names the suite the "
            "artifacts beside it were built from. A run killed while writing it "
            "leaves this; re-run analysis.py over the suite"
            % (manifest_path, detail)
        ) from None

    try:
        return suite_path, prep.load_suite(suite_path).puzzles()
    except FileNotFoundError:
        raise ArtifactNotCurrent(
            "%s names %s as the suite these artifacts describe, and that file is "
            "not there, so nothing can say whether they still describe it"
            % (manifest_path, suite_path)
        ) from None
    except prep.SuiteNotMeasurable as error:
        raise ArtifactNotCurrent(
            "the artifacts in %s cannot be held to the suite they name: %s"
            % (manifest_path.parent, error)
        ) from None


def _definition_diff(built_from, stated):
    """Every field where two fingerprints of one puzzle differ, with both values."""
    return "; ".join(
        "%s is %s in the artifact and %s in the file"
        % (field, built_from.get(field), stated.get(field))
        for field in sorted(set(built_from) | set(stated))
        if built_from.get(field) != stated.get(field)
    )


def load_analysis(path):
    """A PuzzleAnalysis read back from an artifact, ready to score plays.

    Raises ``ArtifactNotCurrent`` unless the numbers in the artifact are the
    numbers this code would compute from the suite file it now has. Three things
    decide them and all three are checked: the oracle that computed them, which
    the artifact records as ``code``; the puzzle the suite file states today,
    which is read back through the loader rather than taken from anything the
    analysis run wrote; and membership, since an artifact of a puzzle the file
    no longer lists is left over from an earlier suite.

    The code fingerprint is hashed once when this module is imported, so a call
    costs a re-read of the suite file and nothing more, which is well under a
    millisecond against the artifact's own JSON. Reading a landscape back stays
    the cheap path it has to be.
    """
    path = Path(path)
    with open(path) as handle:
        data = json.load(handle)

    built_by = data.get("code")
    if built_by != CODE_FINGERPRINT:
        raise ArtifactNotCurrent(
            "%s was written by %s and this oracle is %.12s, so the source of some "
            "module behind these numbers has changed since and the numbers in it may "
            "describe an enumeration or rules this code no longer holds. Re-run "
            "analysis.py over the suite"
            % (
                path,
                "an oracle fingerprinted %.12s" % built_by
                if built_by
                else "an oracle that recorded no fingerprint",
                CODE_FINGERPRINT,
            )
        )

    suite_path, puzzles = _described_suite(path.parent / MANIFEST_NAME)
    stated = {puzzle.id: puzzle_fingerprint(puzzle) for puzzle in puzzles}

    expected = stated.get(data["puzzle_id"])
    if expected is None:
        raise ArtifactNotCurrent(
            "%s describes puzzle %s, which %s does not list (it lists %s). It is "
            "left over from an earlier suite analysed into this directory"
            % (
                path,
                data["puzzle_id"],
                suite_path,
                ", ".join(sorted(stated)),
            )
        )
    if expected != data["puzzle"]:
        raise ArtifactNotCurrent(
            "%s was built from a definition of puzzle %s that %s no longer states: "
            "%s. Its landscape describes a puzzle the suite does not"
            % (
                path,
                data["puzzle_id"],
                suite_path,
                _definition_diff(data["puzzle"], expected),
            )
        )

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
        help="directory to hold this suite's artifacts (default: oracle/artifacts). "
        "It is managed, not appended to: suite.json and any puzzle_*.json left "
        "from another suite are removed",
    )
    args = parser.parse_args()

    shipped = is_shipped_suite(args.puzzles)
    recorded = recorded_counts(args.puzzles)

    try:
        puzzles = prep.load_suite(args.puzzles).puzzles()
    except prep.SuiteNotMeasurable as error:
        print("%s" % error, file=sys.stderr)
        print("no artifacts written", file=sys.stderr)
        return 1

    analyses = []
    miscounted = []
    disagreed = []
    unlanded = []
    for puzzle in puzzles:
        try:
            analysis = analyze_puzzle(puzzle)
        except prep.QueueDoesNotLand as error:
            unlanded.append(error)
            continue
        analyses.append(analysis)

        counted = (analysis.play_count, analysis.win_count)
        expected = EXPECTED_COUNTS.get(puzzle.id) if shipped else None
        if expected is not None and counted != expected:
            miscounted.append((puzzle.id, counted, expected))

        own = recorded.get(puzzle.id)
        if own is not None and own != counted:
            disagreed.append((puzzle.id, counted, own))

        print("puzzle %s" % analysis.puzzle_id)
        print("  %d complete legal plays" % analysis.play_count)
        if shipped and expected is None:
            print("  counts unchecked: this id is new to the shipped suite")
        if own == counted:
            print("  play and win counts agree with the suite file's own record")
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

    suite_ids = {puzzle.id for puzzle in puzzles}
    absent = sorted(set(EXPECTED_COUNTS) - suite_ids) if shipped else []
    if not shipped:
        checked = sum(1 for analysis in analyses if analysis.puzzle_id in recorded)
        if checked:
            print(
                "%s is not the shipped suite, so the expected counts do not apply; "
                "%d of %d puzzles were checked against the counts the file records "
                "for itself" % (args.puzzles, checked, len(analyses))
            )
        else:
            print(
                "counts unchecked: %s is not the shipped suite and records no "
                "counts of its own" % args.puzzles
            )

    if miscounted or absent or disagreed or unlanded:
        for error in unlanded:
            print("not analysed: %s" % error, file=sys.stderr)
        for puzzle_id, counted, expected in miscounted:
            print(
                "puzzle %s enumerated %d plays of which %d win, expected %d and %d: "
                "the puzzle file, the prep port or the engine has changed and this "
                "landscape describes a different game"
                % (puzzle_id, counted[0], counted[1], expected[0], expected[1]),
                file=sys.stderr,
            )
        for puzzle_id in absent:
            print(
                "puzzle %s has expected counts but is not in the suite, so it went "
                "unchecked" % puzzle_id,
                file=sys.stderr,
            )
        for puzzle_id, counted, own in disagreed:
            print(
                "puzzle %s enumerated %d plays of which %d win, but the suite file "
                "records %d and %d: this enumeration and the one that generated the "
                "file disagree about the same puzzle"
                % (puzzle_id, counted[0], counted[1], own[0], own[1]),
                file=sys.stderr,
            )
        print("no artifacts written", file=sys.stderr)
        return 1

    return write_artifacts(Path(args.out_dir), args.puzzles, analyses)


def write_artifacts(out_dir, suite_path, analyses):
    """Make ``out_dir`` the analysis of exactly this suite and nothing else.

    The manifest goes first, so that a run interrupted part way through leaves a
    directory ``load_analysis`` refuses rather than one that vouches for
    artifacts it no longer holds. Then every artifact of an earlier suite is
    removed, because a landscape of a puzzle this suite does not contain has
    nothing in the directory to contradict it and reads as current. Only
    ``suite.json`` and ``puzzle_*.json`` are ever removed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / MANIFEST_NAME
    manifest_path.unlink(missing_ok=True)

    written = {"puzzle_%s.json" % analysis.puzzle_id for analysis in analyses}
    for stale in sorted(out_dir.glob(ARTIFACT_GLOB)):
        if stale.name not in written:
            stale.unlink()
            print("removed %s, which is not part of this suite" % stale)

    for analysis in analyses:
        out_path = out_dir / ("puzzle_%s.json" % analysis.puzzle_id)
        with open(out_path, "w") as handle:
            json.dump(artifact(analysis), handle, indent=1, sort_keys=True)
        print("wrote %s" % out_path)

    with open(manifest_path, "w") as handle:
        json.dump(manifest(suite_path), handle, indent=1, sort_keys=True)
    print("wrote %s, which is what says these artifacts are %s's" % (manifest_path, suite_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
