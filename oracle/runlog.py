"""Read one Godot game log back into the oracle, as plays it can charge regret to.

``godot/scripts/game_logger.gd`` writes one file per session holding every
attempt of every puzzle of every config, and every entry in it names the attempt
it belongs to. This turns that file into, per attempt, the ordered sequence of
``prep.Placement`` the model itself made, which is the shape
``analysis.score_play`` charges a regret to. That is the whole bridge between
what a model did in the game and what the oracle says it gave up.

A log can fail to describe what happened in a dozen ways, and every one of them
produces a play that scores rather than an error. So loading follows
``prep.load_suite``'s shape: what was kept comes back alongside a description of
everything the file stated and was not kept, and ``Run.attempts`` refuses to
hand over any of the plays unless that list is empty. It is the route everything
here scores through, and it is not a wall: ``Run.kept`` is a plain field of a
plain record holding the same attempts, so a caller that reads it goes around
the refusal. That the record is readable is the point of it, and what the
refusal is is a rule this module keeps rather than one it enforces on others.
The one thing on that list that is not a loss is the attempt a run stopped part
way through, which is a real state the game writes deliberately and is described
at ``Run.unfinished``.

The check that makes a reconstruction evidence rather than an assertion is the
replay. A play is right only if it reproduces the battle that was played, and
the log records that battle's own outcome, so ``prep.build_board`` followed by
``engine.run_battle`` is held to the six score fields, the winner, and the
number of battle steps the game recorded, on every attempt, with no way to
switch it off. It is what establishes the row/col convention and which actor is
the agent, neither of which can be settled by reading the GDScript, since the
game writes ``{"row": pos.x, "col": pos.y}`` out of a ``Vector2i`` and the field
names are the only thing that says which component is which.

The replay does not establish placement order on its own. ``engine.py`` makes
battle priority type-first and breaks ties on placement_order, so order reaches
the battle only where it decides which of two equal-priority units acts first,
and a play whose order is otherwise scrambled replays identically. What carries
order is the numbering: every prep entry states the ``TurnManager.turn_number``
it was made on, and ``_reconstruct`` requires those to be 1..n in file order, so
a log cannot state the placements in an order the game did not make them in.
Where order does reach the battle the replay does hold it, and the self-check
carries a fixture built so that it must.

Not every placement in a run is the model's. ``game_controller`` falls back to
``LlmFallback.pick_random_placement`` whenever the model's answer cannot be
applied, and it logs what the fallback did as an ordinary agent prep entry
carrying the same fields, so a run can charge most of its per-placement regret
to a random baseline and still read as a run of a model. The ``chooser`` field
is the only thing that separates the two. It is read per placement, carried into
the output rows, and reported as a rate, and it is never inferred: a log that
does not state it is a log that says nothing about who chose, which is not the
same as saying the model did. Nothing here filters on it, and ``_chooser_rate``
says so where it says the rate.

What none of this reaches is which units the puzzle's shops offered; the limit
is stated in full at ``_against_the_puzzle``.

The opponent's placements are held to the same standard, and that is worth
naming separately, because it is the one thing here that tests ``prep.py``'s own
logic against the real game. ``equivalence.py`` sweeps the battle engine and
says in its own docstring what that leaves out: prep's turn order and
affordability rule have no Godot counterpart on that path. They have one here.
The log states which units the scripted opponent actually fielded and in what
order, and ``prep.simulate_prep`` has to agree with it.

Run it:

    python3 -B oracle/runlog.py score --log <game_*.json>
    python3 -B oracle/runlog.py self-check
"""

import argparse
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import analysis
import engine
import prep

# turn_manager.gd logs the model's own placements under "llm" and the scripted
# opponent's under "human", through apply_llm_prep_placement and
# apply_human_prep_placement respectively.
AGENT = "llm"
OPPONENT = "human"

# What an agent prep entry's "chooser" may say. game_controller applies the
# model's own answer where it can and calls LlmFallback.pick_random_placement
# where it cannot, and both routes place through turn_manager's single
# apply_llm_prep_placement, so the two are indistinguishable in every other field.
MODEL = "model"
FALLBACK = "fallback"
_CHOOSERS = (MODEL, FALLBACK)

# A log written before the game recorded the field states no chooser at all.
# That reads as unstated everywhere here, and never as the model.
UNSTATED = None

# GameLogger._SCORE_FIELDS. engine.run_battle's "final" record carries the same
# six names, which is what lets a replay be compared to a log field by field.
SCORE_FIELDS = (
    "llm_score",
    "human_score",
    "llm_remaining",
    "human_remaining",
    "llm_escaped",
    "human_escaped",
)

# turn_manager._end_game's winner labels against engine._winner_of's.
_WINNER_FROM_LABEL = {"LLM": "llm", "Human": "human", "Tie": "tie"}
_LABEL_FROM_WINNER = {winner: label for label, winner in _WINNER_FROM_LABEL.items()}

# The squares each side may place on. GameBoard.is_position_valid_for refuses the
# rest, so a log stating one is a log stating a placement the game did not make.
_SQUARES_OF = {
    AGENT: frozenset(prep.LLM_SQUARES),
    OPPONENT: frozenset(
        (row, col) for row in engine.OPPONENT_ROWS for col in range(engine.COLS)
    ),
}


class RunNotMeasurable(ValueError):
    """A game log cannot be measured as a record of the run it describes."""


# ``_end_of_battle``'s one reason for an attempt that has no game_over entry,
# named so ``load_run`` can recognise it as itself rather than match on its text.
_NO_RESULT = (
    "never reached a game_over entry, so the file does not state how it ended. An "
    "ablation that stops itself part way through an attempt leaves exactly this: "
    "game_controller._on_ablation_completed saves the log, so the attempt's "
    "placements reach disk and its outcome never does"
)


class _Made(NamedTuple):
    """One prep placement as the file states it, before it means anything."""

    index: int
    actor: str
    placement: prep.Placement
    gold_remaining: int
    chooser: str


@dataclass(frozen=True)
class Attempt:
    """One attempt of one puzzle under one config, as the log states it.

    ``play`` is the agent's own placements in the order it made them, ready for
    ``analysis.score_play``. ``choosers`` runs alongside it, one per placement,
    saying whether the model or ``LlmFallback.pick_random_placement`` made that
    one, or ``UNSTATED`` where the file does not say. ``opponent`` is the
    scripted opponent's placements, in its order, kept because it is what the
    log states about the puzzle itself; the opponent chooses nothing and has no
    choosers. ``observed`` is the game_over entry's six scores and its winner.

    ``dropped`` describes, one string each, everything the file stated about
    this attempt that did not survive: a placement that could not be read, a
    count the game contradicts, a replay that does not reproduce the recorded
    battle. An attempt carrying any drop is an attempt the file does not
    describe, and ``Run.attempts`` is where that becomes fatal.

    ``play_all_attempts`` is the stopping rule the attempt was played under, as
    ``GameLogger.begin_puzzle_attempt`` stamped it: True where the puzzle played
    its whole cap, False where it stopped at its first solve, and None where the
    file does not say, which is every log written before the game recorded it. It
    is not part of the play and changes no regret; what it decides is whether a
    count of attempts means the same thing on two different puzzles.
    """

    puzzle_id: str
    config: str
    number: int
    play: tuple
    choosers: tuple
    opponent: tuple
    observed: dict
    dropped: tuple = ()
    play_all_attempts: bool = None

    @property
    def name(self):
        return "puzzle %s config %s attempt %d" % (
            self.puzzle_id,
            self.config,
            self.number,
        )


@dataclass(frozen=True)
class Run:
    """What ``load_run`` made of one game log against one suite file.

    ``kept`` is the attempts it read. ``dropped`` describes the entries the file
    listed that belong to no attempt this could name. ``free_play_entries``
    counts entries the file itself declares are not part of any puzzle attempt;
    they are out of scope rather than lost, which is exactly what
    GameLogger's ``_FREE_PLAY_IDENTITY`` exists to make distinguishable.

    ``unfinished`` holds the attempt the run stopped part way through, if it has
    one. It is the last block in the file, its placements are on disk and its
    outcome is not, and it is out of scope rather than lost: it states no play to
    score and makes no claim about one. An ablation that hits its API-error limit
    ends this way by design, so treating it as a loss would refuse every complete
    attempt the run did play. ``load_run`` is where the distinction is drawn and
    says on what.

    ``suite_puzzles`` is the suite the log is being read against, carried here so
    that scoring cannot re-read the file and get a second answer.
    """

    path: str
    suite_path: str
    suite_puzzles: tuple
    kept: tuple
    dropped: tuple
    free_play_entries: int = 0
    unfinished: tuple = ()

    def attempts(self):
        """Every attempt the file describes, or a refusal to hand over any.

        A run is measurable only if nothing the file stated about its attempts
        was discarded or contradicted. Losses arrive at two levels and neither
        is distinguished here: an entry that names no attempt, and an attempt
        that does not hold together. A measurement of the file minus either is
        a measurement of a run that was not played.

        A log listing no attempt is the third way, and it is not a discard. It
        produces no rows and no disagreement, so it reads as a clean pass having
        measured nothing. A log whose every attempt is one the run stopped part
        way through says the same thing and is refused for the same reason.
        """
        losses = list(self.dropped)
        for attempt in self.kept:
            losses.extend(
                "%s %s" % (attempt.name, reason) for reason in attempt.dropped
            )
        if losses:
            raise RunNotMeasurable(
                "%s does not read as a record of the run it describes: %s. Scoring it "
                "would charge regrets to plays the file does not state"
                % (self.path, "; ".join(losses))
            )
        if not self.kept:
            # What the file does hold instead, so that pointing this at a
            # free-play log or at a run that stopped in its first attempt says
            # which of the two it was.
            aside = []
            if self.unfinished:
                aside.append(
                    "the run stopped part way through %s"
                    % "; ".join(attempt.name for attempt in self.unfinished)
                )
            if self.free_play_entries:
                aside.append(
                    "%d of its entries declare themselves free play, which belongs to "
                    "no puzzle" % self.free_play_entries
                )
            raise RunNotMeasurable(
                "%s states no puzzle attempt the run played to an outcome%s, so "
                "scoring it would score nothing and report that as a pass"
                % (self.path, " (%s)" % "; ".join(aside) if aside else "")
            )
        return self.kept


# --- Reading the file ---


def _read_entries(path):
    """The entries the file lists, or one reason the whole file is not a log.

    ``GameLogger.save_log`` stores ``JSON.stringify`` of a flat array of entry
    dictionaries and nothing else, so a root of any other shape is not a game
    log whatever else it may be.

    A path that cannot be read at all comes back the same way. Naming the wrong
    file is the ordinary way to get this wrong, and the file being absent, being
    a directory, or holding bytes that are not text says the same thing about it
    as a root of the wrong shape does: this is not the log it was called on.
    """
    try:
        with open(path) as handle:
            root = json.load(handle)
    except OSError as error:
        return (), (
            "%s cannot be read (%s), so it states no entries at all"
            % (path, error.strerror or error),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return (), (
            "%s does not read as JSON text (%s), so it states no entries at all. "
            "GameLogger.save_log writes JSON.stringify of the whole entry array; a "
            "file that does not decode is a different file or a truncated write"
            % (path, error),
        )
    if not isinstance(root, list):
        return (), (
            "the root of %s is %s, not the array of entries GameLogger.save_log "
            "writes, so nothing in it can be attributed to an attempt"
            % (path, type(root).__name__),
        )
    return root, ()


def _identity(entry, index):
    """The ``(puzzle id, config, attempt)`` an entry names, or why it names none.

    ``GameLogger.begin_puzzle_attempt`` stamps all four identity fields onto
    every following entry, and ``begin_free_play_game`` stamps ``play_mode`` on
    its own so that a free-play entry can never read as a puzzle entry whose
    identity went missing. So an entry carrying neither is one that lost its
    identity, and it is dropped rather than skipped.
    """
    mode = entry.get("play_mode")
    puzzle_id = entry.get("puzzle_id")
    config = entry.get("config")
    number = entry.get("attempt")
    readable = (
        mode == "puzzle"
        and isinstance(puzzle_id, str)
        and puzzle_id.strip()
        and isinstance(config, str)
        and config.strip()
        and isinstance(number, int)
        and not isinstance(number, bool)
        and number >= 1
    )
    if not readable:
        return None, (
            "entry %d names no puzzle attempt and does not declare itself free play "
            "(play_mode %r, puzzle_id %r, config %r, attempt %r), so nothing in the "
            "file says which attempt it belongs to"
            % (index, mode, puzzle_id, config, number)
        )
    return (puzzle_id.strip(), config.strip(), number), None


@dataclass
class _Draft:
    """One attempt's entries as the file lists them, before any check."""

    puzzle_id: str
    config: str
    number: int
    play_all_attempts: bool = None
    prep_entries: list = field(default_factory=list)
    battle_entries: int = 0
    result: dict = None
    dropped: list = field(default_factory=list)

    @property
    def name(self):
        return "puzzle %s config %s attempt %d" % (
            self.puzzle_id,
            self.config,
            self.number,
        )


def _group(entries):
    """The file's entries as one draft per attempt, in the order it states them.

    An attempt is one contiguous block opened by exactly one ``attempt_start``:
    ``begin_puzzle_attempt`` logs that entry and sets the identity every
    following entry is stamped with, so entries of two attempts cannot
    interleave and no identity can be opened twice. Either would otherwise merge
    into one draft and read as a single longer attempt whose counts and play
    both happen to be wrong, so a reopened identity drops its whole second block
    rather than folding it in. Both an ``attempt_start`` and a change of
    identity open a block, because an attempt whose start entry went missing
    still has to be read and a repeat of a whole block never changes identity.
    """
    drafts = []
    by_identity = {}
    reopened = set()
    dropped = []
    free_play = 0
    current_identity = None
    current_draft = None

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            dropped.append(
                "entry %d is %s, not a dictionary, so nothing in it says which "
                "attempt it belongs to" % (index, type(entry).__name__)
            )
            continue
        if entry.get("play_mode") == "free_play":
            free_play += 1
            continue
        identity, reason = _identity(entry, index)
        if identity is None:
            dropped.append(reason)
            continue

        if identity != current_identity or entry.get("event") == "attempt_start":
            current_identity = identity
            existing = by_identity.get(identity)
            if existing is None:
                # Read off the entry that opens the block: every entry of an
                # attempt carries it, and a block can open on a change of
                # identity rather than on an attempt_start.
                stated = entry.get("play_all_attempts")
                current_draft = _Draft(
                    *identity,
                    play_all_attempts=stated if isinstance(stated, bool) else None,
                )
                by_identity[identity] = current_draft
                drafts.append(current_draft)
            else:
                current_draft = None
                if identity not in reopened:
                    reopened.add(identity)
                    dropped.append(
                        "the file states %s in two separate blocks, the second from "
                        "entry %d; an attempt is how a play is named in every row of "
                        "the output, so two cannot share one name"
                        % (existing.name, index)
                    )
        if current_draft is None:
            continue

        if entry.get("phase") == "prep":
            current_draft.prep_entries.append((index, entry))
        elif entry.get("phase") == "battle":
            current_draft.battle_entries += 1
        elif entry.get("event") == "game_over":
            if current_draft.result is None:
                current_draft.result = entry
            else:
                current_draft.dropped.append(
                    "states a second game_over at entry %d, so the file does not say "
                    "which of them the attempt ended on" % index
                )

    return drafts, dropped, free_play


# --- What one attempt has to hold together against ---


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _reconstruct(draft):
    """The prep placements the attempt states, in order, and what could not be read.

    ``chooser`` is read here too, because it is stated per placement and this is
    where a placement becomes one. Its two guards are the whole of what this
    module can say about the field: that the agent's placements state one of the
    two values or nothing, and that the opponent's state none. Whether the value
    a log gives is the truth about that placement is a claim only the game can
    make, and nothing in the log can be replayed against it.

    ``turn_number`` on a prep entry is ``TurnManager.turn_number``, which counts
    both sides' placements from 1 and increments once per placement. Requiring
    the entries to carry exactly 1..n in file order is what says they reached
    this in the order the game made them: a merge, a sort, or entries pulled
    from two attempts all break it, and placement order is load-bearing because
    battle_engine.gd breaks priority ties with it.
    """
    made = []
    reasons = []
    for index, entry in draft.prep_entries:
        actor = entry.get("actor")
        if actor not in _SQUARES_OF:
            reasons.append(
                "entry %d is a prep placement by %r, which is neither the agent (%r) "
                "nor the scripted opponent (%r), so nothing says whose play it is "
                "part of" % (index, actor, AGENT, OPPONENT)
            )
            continue

        chooser = entry.get("chooser")
        if actor == AGENT and chooser is not UNSTATED and chooser not in _CHOOSERS:
            reasons.append(
                "entry %d states chooser %r, which is neither %r nor %r, so nothing in "
                "it says whether the model or the random fallback made this placement"
                % (index, chooser, MODEL, FALLBACK)
            )
            continue
        if actor == OPPONENT and chooser is not UNSTATED:
            reasons.append(
                "entry %d attributes a placement by the scripted opponent to the "
                "chooser %r, and the opponent's placements are the puzzle's own and "
                "are chosen by nothing, so the file is not describing the game this "
                "reads" % (index, chooser)
            )
            continue

        label = str(entry.get("unit_type", "")).upper().strip()
        try:
            unit_type = engine.label_to_type(label)
        except ValueError:
            reasons.append(
                "entry %d places the unreadable unit type '%s', so what the %s bought "
                "there is not stated" % (index, label, actor)
            )
            continue

        position = entry.get("position")
        row = position.get("row") if isinstance(position, dict) else None
        col = position.get("col") if isinstance(position, dict) else None
        if not _is_int(row) or not _is_int(col):
            reasons.append(
                "entry %d states its position as %r rather than the {row, col} pair "
                "GameLogger._prep_placement_fields writes, so the square it names is not "
                "stated" % (index, position)
            )
            continue
        if (row, col) not in _SQUARES_OF[actor]:
            reasons.append(
                "entry %d places %s on (%d, %d), which is not a square the %s may "
                "place on, so the game did not make this placement"
                % (index, label, row, col, actor)
            )
            continue

        gold = entry.get("gold_remaining")
        if not _is_int(gold):
            reasons.append(
                "entry %d states its gold_remaining as %r rather than a number, so "
                "nothing in it says what the placement cost" % (index, gold)
            )
            continue

        made.append(
            _Made(index, actor, prep.Placement(unit_type, (row, col)), gold, chooser)
        )

    numbering = [entry.get("turn_number") for _, entry in draft.prep_entries]
    if not reasons and numbering != list(range(1, len(numbering) + 1)):
        reasons.append(
            "states its prep entries under turn numbers %s rather than the 1..%d "
            "TurnManager counts them off in, so the file does not state the order "
            "the placements were made in" % (numbering, len(numbering))
        )

    play = tuple(item.placement for item in made if item.actor == AGENT)
    choosers = tuple(item.chooser for item in made if item.actor == AGENT)
    opponent = tuple(item.placement for item in made if item.actor == OPPONENT)
    return tuple(made), play, choosers, opponent, tuple(reasons)


def _end_of_battle(draft):
    """The scores and winner the attempt ended on, and what the file left unstated.

    ``turn_manager._end_game`` writes the game_over entry from the battle's own
    final step, so it is the game's statement of what the play produced and the
    only thing a replay can be held to.
    """
    if draft.result is None:
        return {}, (_NO_RESULT,)

    reasons = []
    observed = {}
    missing = [name for name in SCORE_FIELDS if not _is_int(draft.result.get(name))]
    if missing:
        reasons.append(
            "ends on a game_over stating no readable %s, so the battle it records "
            "cannot be compared with the one this play produces"
            % ", ".join(missing)
        )
    else:
        observed = {name: draft.result[name] for name in SCORE_FIELDS}

    label = draft.result.get("winner")
    if label not in _WINNER_FROM_LABEL:
        reasons.append(
            "ends on the winner %r, which is none of the labels turn_manager._end_game "
            "writes (%s), so the file does not state who won"
            % (label, ", ".join(sorted(_WINNER_FROM_LABEL)))
        )
    else:
        observed["winner"] = _WINNER_FROM_LABEL[label]

    return observed, tuple(reasons)


def _against_what_the_game_states(draft):
    """Hold the entries counted here to the totals the game recorded for them.

    ``log_game_result`` is handed ``turn_number`` and ``battle_step_number``,
    which the game counted as it played, so they are an independent statement of
    how many entries this attempt should have. An entry lost to a truncated
    write, or one attributed to the wrong attempt, changes the count on this side
    and not on that one.
    """
    reasons = []
    for name, counted, what in (
        ("total_prep_turns", len(draft.prep_entries), "prep placements"),
        ("total_battle_steps", draft.battle_entries, "battle steps"),
    ):
        stated = draft.result.get(name)
        if not _is_int(stated):
            reasons.append(
                "ends on a game_over stating no %s, so nothing in the file says how "
                "many %s it should hold" % (name, what)
            )
        elif stated != counted:
            reasons.append(
                "states %d %s and its own game_over counted %d, so the file holds a "
                "different attempt from the one the game played"
                % (counted, what, stated)
            )
    return tuple(reasons)


def _against_the_puzzle(draft, made, play, opponent, observed, puzzles, suite_path):
    """Hold the attempt to the puzzle the suite states it was played on.

    Four things in order, each of which would otherwise pass silently:

    The puzzle has to be one the suite lists, or nothing states the board these
    placements were made against.

    Each side's ``gold_remaining`` has to follow from its starting gold and what
    it bought. Shop.purchase is what wrote those numbers, so they are the game's
    own statement of the unit types, independent of the labels this read.

    The play has to be a complete legal play. ``prep.simulate_prep`` is the same
    rule ``prep.enumerate_plays`` walks, so a play failing it is a play the
    landscape has no value for at all.

    The opponent has to have fielded what ``prep.simulate_prep`` says it fields,
    in that order. This is the check that puts prep's turn order and
    affordability rule against the real game, which equivalence.py's sweep of
    the battle engine does not reach.

    Then the replay, which is the point of the module and is last because it is
    only meaningful once the rest holds.

    What none of the four reaches is shop membership, and that gap is real
    rather than an oversight. The gold states what each placement cost and
    ``simulate_prep`` states that everything bought was on sale, so a shop that
    LOST a unit the play bought refuses here. A unit ADDED to a shop and never
    bought is stated by nothing in the log: the board, the costs, the opponent
    and the battle are all identical with it and without it. The one place an
    unbought shop entry could leak into the record is prep ending when nothing
    is affordable, which cannot see a unit no cheaper than the cheapest already
    on sale, and every unit costs 1 or 2. So there is no check here to build.
    It matters because the landscape does move: adding D to the shipped puzzle
    1's llm_shop leaves every check in this module passing and takes the puzzle
    from 103 winning plays of 3240 to 151 of 3420, difficulty 0.0318 to 0.0442
    (measured 2026-09-09). What catches that is the artifact fingerprint in
    ``landscapes_for``, and only until analysis.py is re-run over the edited
    suite. Scoring a run against a suite file that is not the one it was played
    on is outside what this module can establish.
    """
    puzzle = puzzles.get(draft.puzzle_id)
    if puzzle is None:
        return (
            "names a puzzle %s does not list (it lists %s), so nothing states the "
            "board these placements were made against; the suite changed after the "
            "run, or the run was played on another one"
            % (suite_path, ", ".join(sorted(puzzles)) or "none"),
        )

    gold = {AGENT: puzzle.llm_gold, OPPONENT: puzzle.opponent_gold}
    for item in made:
        gold[item.actor] -= engine.UNIT_COSTS[item.placement.unit_type]
        if gold[item.actor] != item.gold_remaining:
            return (
                "entry %d leaves the %s on %d gold and Shop.purchase recorded %d, so "
                "the unit bought there was not the %s this read"
                % (
                    item.index,
                    item.actor,
                    gold[item.actor],
                    item.gold_remaining,
                    engine.TYPE_LABELS[item.placement.unit_type],
                ),
            )

    try:
        result = prep.simulate_prep(puzzle, play)
    except ValueError as error:
        return (
            "reconstructs to %s, which is not a complete legal play of puzzle %s: %s. "
            "The landscape holds no value for a play the game could not have produced"
            % (analysis.encode_play(play) or "an empty play", puzzle.id, error),
        )

    fielded = tuple(
        prep.Placement(unit_type, pos) for pos, unit_type, _ in result.opponent_units
    )
    if fielded != opponent:
        return (
            "records the opponent fielding %s and puzzle %s fields %s, so the file "
            "states a different puzzle from the one the suite does"
            % (
                analysis.encode_play(opponent) or "nothing",
                puzzle.id,
                analysis.encode_play(fielded) or "nothing",
            ),
        )

    # No play of this board can reach engine.run_battle's 200-step cap, so the
    # replay always comes back finished and there is nothing here to check that
    # against. Every step of a battle removes a unit or moves one a row closer
    # to the edge it escapes off, and the only step that does neither is a pass,
    # which the other side cannot also make without ending the battle. A 4x3
    # board holds at most 12 units, which is at most 60 removals-and-advances
    # and at most that many passes between them: 121 steps against a cap of 200.
    # Measured 2026-09-10: the longest battle over all 11,550 plays of the
    # shipped suite is 20 steps, and over 200,000 boards with all 12 squares
    # filled, which prep cannot build, 40. If the board or the cap ever moves,
    # an aborted replay stops at the cap and the battle-length comparison below
    # is what refuses it.
    final = engine.run_battle(prep.build_board(puzzle, play))["final"]
    # How long the battle ran is a seventh thing the game recorded about this
    # play, independent of what it scored: a board that is subtly wrong can
    # still reach the same six scores, over a different number of steps.
    # total_battle_steps is an integer here, and equal to the battle entries
    # counted in this attempt, because _against_what_the_game_states held it to
    # both before this ran.
    recorded = dict(observed, steps=draft.result["total_battle_steps"])
    differ = [
        "%s %s replayed against %s recorded" % (name, final[name], recorded[name])
        for name in SCORE_FIELDS + ("winner", "steps")
        if final[name] != recorded[name]
    ]
    if differ:
        return (
            "reconstructs to %s, and the oracle's replay of that play does not "
            "reproduce the battle the game recorded (%s), so it is not the play that "
            "was made" % (analysis.encode_play(play), "; ".join(differ)),
        )
    return ()


def _finish(draft, puzzles, suite_path):
    """One draft as an Attempt, carrying everything about it that did not hold.

    The checks stop at the first level that fails, because every later one reads
    the result of an earlier one: a placement that could not be read makes the
    play, the counts and the replay all disagree, and three restatements of one
    fault are noise rather than three findings.
    """
    made, play, choosers, opponent, reasons = _reconstruct(draft)
    observed, result_reasons = _end_of_battle(draft)
    reasons = tuple(draft.dropped) + reasons + result_reasons
    if not reasons:
        reasons = _against_what_the_game_states(draft)
    if not reasons:
        reasons = _against_the_puzzle(
            draft, made, play, opponent, observed, puzzles, suite_path
        )
    return Attempt(
        puzzle_id=draft.puzzle_id,
        config=draft.config,
        number=draft.number,
        play=play,
        choosers=choosers,
        opponent=opponent,
        observed=observed,
        dropped=tuple(reasons),
        play_all_attempts=draft.play_all_attempts,
    )


def load_run(path, suite_path=prep.DEFAULT_PUZZLE_PATH):
    """Read one game log against the suite it was played on.

    The suite comes through ``prep.load_suite(...).puzzles()``, so a suite file
    that does not load as the suite it describes refuses here, named, before any
    play is attributed to a puzzle out of it. A suite path that cannot be read
    at all refuses the same way and as the same type, since it is the same
    mistake one step earlier: ``prep.load_suite`` opens the file itself and
    reports a missing or undecodable one as the exception of whoever opened it.
    """
    try:
        suite = prep.load_suite(suite_path)
    except OSError as error:
        raise prep.SuiteNotMeasurable(
            "%s cannot be read (%s), so nothing states the puzzles this run was "
            "played on" % (suite_path, error.strerror or error)
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise prep.SuiteNotMeasurable(
            "%s does not read as JSON text (%s), so nothing states the puzzles this "
            "run was played on" % (suite_path, error)
        ) from None
    puzzles = {puzzle.id: puzzle for puzzle in suite.puzzles()}
    entries, fatal = _read_entries(path)
    if fatal:
        return Run(str(path), str(suite_path), tuple(puzzles.values()), (), fatal)

    drafts, dropped, free_play = _group(entries)
    kept = []
    unfinished = []
    for position, draft in enumerate(drafts, 1):
        attempt = _finish(draft, puzzles, suite_path)
        # An attempt with nothing wrong with it but a missing outcome, and
        # nothing after it in the file, is where the run stopped rather than an
        # entry that went missing. ``save_log`` rewrites the whole array from
        # memory and ``log_game_result`` is the statement immediately before the
        # save that follows a battle, so the file cannot hold a finished
        # attempt's placements without its game_over. An attempt in this state
        # anywhere but last therefore did lose an entry, and stays fatal.
        if position == len(drafts) and attempt.dropped == (_NO_RESULT,):
            unfinished.append(attempt)
            continue
        kept.append(attempt)
    return Run(
        path=str(path),
        suite_path=str(suite_path),
        suite_puzzles=tuple(puzzles.values()),
        kept=tuple(kept),
        dropped=tuple(dropped),
        free_play_entries=free_play,
        unfinished=tuple(unfinished),
    )


# --- Scoring a run ---


class ScoredPlacement(NamedTuple):
    """One placement of one attempt, with what it was worth and what it gave up.

    Per-placement regret is the study's primary outcome, so the row is the
    placement rather than the attempt; everything above it repeats down the
    rows it belongs to. ``chooser`` is on the row for the same reason: the
    regret is charged to whatever made this placement, and that is the model
    only where the log says so.
    """

    puzzle_id: str
    config: str
    attempt: int
    difficulty: float
    value: int
    whole_play_regret: int
    number: int
    placement: str
    chooser: str
    regret: int

    @property
    def chooser_label(self):
        """``chooser`` as a reader of the table reads it.

        A row is never blank here. A log that states nothing about a placement
        prints as unstated, which is a different claim from the model having
        made it, and the two must not look alike in a column someone scans.
        """
        return self.chooser if self.chooser is not UNSTATED else "unstated"


def landscapes_for(run, out_dir=analysis.DEFAULT_OUT_DIR):
    """One value landscape per distinct puzzle the run's attempts were played on.

    Read back from an artifact where one exists and enumerated where none does,
    once per puzzle either way; the shipped suite's smallest puzzle is 1,080
    plays and its largest 7,230, so re-enumerating per attempt would repeat the
    whole landscape nine times over a nine-attempt log.

    ``analysis.load_analysis`` holds an artifact to the suite its own directory
    names. That is not the suite this run was read against unless the two were
    pointed at the same file, so the fingerprint is compared again here against
    the puzzle the run actually used. Without it, an artifact directory built
    from a different file that happens to use the same puzzle ids would charge
    these plays regrets from another puzzle's landscape. The difference is
    described by the same helper analysis.py describes its own with, which names
    both values rather than only the field: which of the two moved is what says
    whether to re-run analysis.py or fix the suite.
    """
    stated = {puzzle.id: puzzle for puzzle in run.suite_puzzles}
    out_dir = Path(out_dir)
    landscapes = {}
    for attempt in run.attempts():
        if attempt.puzzle_id in landscapes:
            continue
        puzzle = stated[attempt.puzzle_id]
        path = out_dir / ("puzzle_%s.json" % puzzle.id)
        if path.exists():
            try:
                landscape = analysis.load_analysis(path)
            except OSError as error:
                raise analysis.ArtifactNotCurrent(
                    "%s cannot be read (%s), so nothing in it states this puzzle's "
                    "landscape" % (path, error.strerror or error)
                ) from None
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise analysis.ArtifactNotCurrent(
                    "%s does not read as JSON text (%s), so it is not an artifact "
                    "analysis.py wrote. A run killed part way through writing it "
                    "leaves this; re-run analysis.py over the suite" % (path, error)
                ) from None
            expected = analysis.puzzle_fingerprint(puzzle)
            if landscape.puzzle != expected:
                raise analysis.ArtifactNotCurrent(
                    "%s holds a landscape of puzzle %s built from a definition %s does "
                    "not state: %s. The run was played on that file, so scoring it from "
                    "this artifact would charge its plays regrets from a different "
                    "puzzle. Re-run analysis.py over the suite the run was played on"
                    % (
                        path,
                        puzzle.id,
                        run.suite_path,
                        # Reached by its private name deliberately: analysis.py
                        # hashes its own source into CODE_FINGERPRINT, so
                        # renaming this helper would stale every artifact
                        # already written, for a name.
                        analysis._definition_diff(landscape.puzzle, expected),
                    )
                )
        else:
            landscape = analysis.analyze_puzzle(puzzle)
        landscapes[puzzle.id] = landscape
    return landscapes


def score_run(run, out_dir=analysis.DEFAULT_OUT_DIR):
    """Every placement of every attempt in the run, with its regret.

    The landscape's value for a play is compared with the margin the game
    observed. The two are computed from different things, the landscape by
    enumeration or from an artifact and the margin by the game itself, so an
    artifact that reads as current while holding stale numbers shows up here
    rather than as a plausible regret.
    """
    landscapes = landscapes_for(run, out_dir)
    rows = []
    for attempt in run.attempts():
        landscape = landscapes[attempt.puzzle_id]
        score = analysis.score_play(landscape, attempt.play)
        margin = attempt.observed["llm_score"] - attempt.observed["human_score"]
        if score.value != margin:
            raise RunNotMeasurable(
                "%s of %s: the landscape values this play at %d and the game recorded "
                "a margin of %d, so the landscape scoring it is not a landscape of the "
                "battle that was played"
                % (attempt.name, run.path, score.value, margin)
            )
        for number, (placement, chooser, regret) in enumerate(
            zip(attempt.play, attempt.choosers, score.placement_regrets), 1
        ):
            rows.append(
                ScoredPlacement(
                    puzzle_id=attempt.puzzle_id,
                    config=attempt.config,
                    attempt=attempt.number,
                    difficulty=landscape.difficulty,
                    value=score.value,
                    whole_play_regret=score.whole_play_regret,
                    number=number,
                    placement=analysis.encode_placement(placement),
                    chooser=chooser,
                    regret=regret,
                )
            )
    return tuple(rows)


# --- CLI ---

_COLUMNS = (
    ("puzzle", "puzzle_id", "%s"),
    ("config", "config", "%s"),
    ("attempt", "attempt", "%d"),
    ("difficulty", "difficulty", "%.4f"),
    ("value", "value", "%d"),
    ("play_regret", "whole_play_regret", "%d"),
    ("n", "number", "%d"),
    ("placement", "placement", "%s"),
    ("chooser", "chooser_label", "%s"),
    ("regret", "regret", "%d"),
)


def _table(rows):
    cells = [[title for title, _, _ in _COLUMNS]]
    cells.extend(
        [template % getattr(row, name) for _, name, template in _COLUMNS]
        for row in rows
    )
    widths = [max(len(column[index]) for column in cells) for index in range(len(_COLUMNS))]
    for line in cells:
        print("  ".join(value.ljust(width) for value, width in zip(line, widths)))


_RULE_NAMES = {True: "whole cap", False: "stop at first solve", None: "unstated"}


def _stopping_rule(attempts):
    """What the log says about how many attempts each puzzle was given.

    It belongs beside the per-puzzle means and not further down, because it is
    what says whether two of those means are the same measurement. Under
    stop-on-solve a puzzle contributes attempts until it wins one, so a puzzle
    the agent solves contributes fewer of them, and the ones it contributes are
    the ones before its win. A mean over those is a mean over a set the outcome
    chose.
    """
    stated = {attempt.play_all_attempts for attempt in attempts}
    if stated == {True}:
        return (
            "every puzzle played its whole attempt cap, so each contributed a number "
            "of attempts its own outcome did not decide"
        )
    if stated == {False}:
        return (
            "every puzzle stopped at its first solve, so how many attempts a puzzle "
            "contributed was decided by its own outcome and these means are not "
            "comparable across puzzles"
        )
    if stated == {None}:
        return (
            "this log does not state whether puzzles stopped at their first solve, so "
            "whether these means count comparable numbers of attempts is unstated; it "
            "was written before the game recorded the stopping rule"
        )
    return (
        "the attempts in this log were not all played under one stopping rule (%s), so "
        "these means mix puzzles given a fixed number of attempts with puzzles given "
        "as many as their outcome allowed"
        % ", ".join(sorted(_RULE_NAMES[value] for value in stated))
    )


def _chooser_rate(rows):
    """How many of the agent's placements the model itself made.

    It belongs beside the per-puzzle means for the same reason the stopping rule
    does: it is what says what those means are means of. game_controller falls
    back to LlmFallback.pick_random_placement whenever the model's answer cannot
    be applied, the fallback's placements carry regret in the table above
    exactly as the model's do, and a run where that happened often is a run
    whose primary outcome is part model and part coin.

    The limit on that: nothing here is filtered. Every placement is scored and
    none is left out, because whether an analysis pools the fallback placements,
    splits them out or drops them is a decision about the study and cannot be
    taken by a module whose whole input is a log. This makes the mixture
    visible; it does not act on it.
    """
    total = len(rows)
    by_model = sum(1 for row in rows if row.chooser == MODEL)
    by_fallback = sum(1 for row in rows if row.chooser == FALLBACK)
    unstated = total - by_model - by_fallback
    if unstated == total:
        return (
            "this log states what chose none of the %d placements above, so how many "
            "of them the model itself made is unstated rather than all or none of "
            "them; it was written before the game recorded the chooser"
            % total
        )
    return (
        "the model itself made %d of the agent's %d placements (%.1f%%) and "
        "LlmFallback.pick_random_placement made %d%s. Every one of them is scored "
        "above and none is excluded: whether to pool the fallback placements, split "
        "them out or drop them is a decision about the study, not one a reader of a "
        "log can take"
        % (
            by_model,
            total,
            100.0 * by_model / total,
            by_fallback,
            ", and %d of them state nothing" % unstated if unstated else "",
        )
    )


def _score(args):
    try:
        run = load_run(args.log, args.puzzles)
        attempts = run.attempts()
        rows = score_run(run, args.artifacts)
    except (
        RunNotMeasurable,
        prep.SuiteNotMeasurable,
        analysis.ArtifactNotCurrent,
    ) as error:
        print("%s" % error, file=sys.stderr)
        print("nothing scored", file=sys.stderr)
        return 1

    print("run   %s" % run.path)
    print("suite %s" % run.suite_path)
    print(
        "%d attempts, %d placements by the agent, %d entries outside any puzzle attempt"
        % (len(attempts), len(rows), run.free_play_entries)
    )
    print(
        "every attempt's reconstructed play replayed to the six scores, the winner "
        "and the battle length its game_over records"
    )
    if run.unfinished:
        print(
            "the run stopped part way through %s, which states no outcome and is not "
            "scored below"
            % "; ".join(attempt.name for attempt in run.unfinished)
        )
    print()
    _table(rows)
    print()
    print(_stopping_rule(attempts))
    print(_chooser_rate(rows))
    for puzzle_id in sorted({row.puzzle_id for row in rows}):
        mine = [row for row in rows if row.puzzle_id == puzzle_id]
        # One entry per attempt: every row of an attempt repeats its whole-play
        # regret, so the dictionary is what turns the rows back into plays.
        regrets = {
            (row.config, row.attempt): row.whole_play_regret for row in mine
        }
        print(
            "puzzle %s: difficulty %.4f, %d attempts, mean whole-play regret %.2f, "
            "%d won"
            % (
                puzzle_id,
                mine[0].difficulty,
                len(regrets),
                sum(regrets.values()) / len(regrets),
                sum(1 for row in mine if row.number == 1 and row.value > 0),
            )
        )
    return 0


# --- Self-check ---

_FIXTURE_PUZZLE = {
    "id": "fixture",
    "difficulty": 1,
    "llm_shop": ["A", "B"],
    "llm_gold": 2,
    "opponent_shop": ["A"],
    "opponent_gold": 2,
    "opponent_placements": [
        {"type": "A", "row": 2, "col": 0},
        {"type": "A", "row": 2, "col": 1},
    ],
}

# Two squares that are still the agent's when their row and column are swapped,
# holding different unit types, so a reader that took the Vector2i components in
# order rather than by their field names builds a different board and not an
# illegal one. That is the only shape of that fault a square check cannot see.
_FIXTURE_PLAY = (prep.Placement(engine.A, (0, 1)), prep.Placement(engine.B, (1, 0)))

# One of each, so the valid fixture exercises both values of the field and a
# rate that is neither none of the placements nor all of them.
_FIXTURE_CHOOSERS = (MODEL, FALLBACK)

# The order fixture. Both agent units are the same type, so battle priority
# cannot separate them and _pick_acting_unit falls through to placement_order:
# played in this order the agent takes the opponent's only unit on step 1 and
# wins 2-0, and stated the other way round the same two squares hold the same
# two units and the battle runs five steps to a 1-1 tie. The fixture above
# cannot do this, because its units differ in type and type is decided first.
_ORDER_PUZZLE = {
    "id": "order",
    "difficulty": 2,
    "llm_shop": ["A"],
    "llm_gold": 2,
    "opponent_shop": ["A"],
    "opponent_gold": 1,
    "opponent_placements": [{"type": "A", "row": 2, "col": 0}],
}

_ORDER_PLAY = (prep.Placement(engine.A, (1, 0)), prep.Placement(engine.A, (1, 1)))

_FIXTURE_SESSION = {
    "session_id": "fixture",
    "play_mode": "puzzle",
    "config": "FIXTURE",
    "attempt": 1,
    "play_all_attempts": False,
}


def _fixture_suite(directory):
    """The suite both fixture logs are played on, written where a loader can read it.

    Both puzzles live in one file because a run is scored against one suite, and
    a suite holding two puzzles is also what makes ``landscapes_for`` do its
    per-puzzle lookup more than once.
    """
    suite_path = Path(directory) / "fixture_suite.json"
    suite_path.write_text(json.dumps({"puzzles": [_FIXTURE_PUZZLE, _ORDER_PUZZLE]}))
    return suite_path, {
        puzzle.id: puzzle for puzzle in prep.load_suite(suite_path).puzzles()
    }


def _fixture_entries(puzzle, play, choosers=None):
    """A log of one attempt of ``play``, in the shape GameLogger writes.

    ``choosers`` states what made each of the agent's placements, defaulting to
    the model for all of them. The opponent's entries never carry the field.

    Built by running the play through the oracle, so what it proves is that each
    guard fires on the fault it names. That the reconstruction is right about the
    real game is a different claim, and only a real Godot log can carry it.

    The battle entries hold no events: nothing here reads them, only counts them
    against what the game_over states.
    """
    identity = dict(_FIXTURE_SESSION, puzzle_id=puzzle.id)
    result = prep.simulate_prep(puzzle, play)
    choosers = choosers if choosers is not None else (MODEL,) * len(play)
    made = [
        (order, AGENT, placement, chooser)
        for placement, order, chooser in zip(play, result.llm_orders, choosers)
    ]
    made.extend(
        (order, OPPONENT, prep.Placement(unit_type, pos), UNSTATED)
        for pos, unit_type, order in result.opponent_units
    )
    # By turn order alone: the chooser rides along and a str never has to be
    # compared with the UNSTATED an opponent entry carries.
    made.sort(key=lambda item: item[0])

    gold = {AGENT: puzzle.llm_gold, OPPONENT: puzzle.opponent_gold}
    entries = [dict(identity, turn_number=0, event="attempt_start")]
    for turn, (_, actor, placement, chooser) in enumerate(made, 1):
        gold[actor] -= engine.UNIT_COSTS[placement.unit_type]
        entry = dict(
            identity,
            turn_number=turn,
            phase="prep",
            actor=actor,
            unit_type=engine.TYPE_LABELS[placement.unit_type],
            position={"row": placement.pos[0], "col": placement.pos[1]},
            gold_remaining=gold[actor],
        )
        if chooser is not UNSTATED:
            entry["chooser"] = chooser
        entries.append(entry)

    final = engine.run_battle(prep.build_board(puzzle, play))["final"]
    for step in range(1, final["steps"] + 1):
        entries.append(
            dict(
                identity,
                turn_number=step,
                phase="battle",
                active_owner="LLM",
                events="",
                had_escape=False,
            )
        )
    over = dict(
        identity,
        turn_number=final["steps"],
        event="game_over",
        winner=_LABEL_FROM_WINNER[final["winner"]],
        total_prep_turns=len(made),
        total_battle_steps=final["steps"],
    )
    over.update({name: final[name] for name in SCORE_FIELDS})
    entries.append(over)
    return entries


def _stopped_part_way(entries, attempt_number):
    """The entries an ablation leaves when it stops part way through an attempt.

    Its boundary entry and the placements it had already made, with no game_over
    after them: ``AblationRunner.terminate_with_failure`` ends the run and
    ``game_controller._on_ablation_completed`` saves the log, so this much of the
    attempt reaches disk and its outcome never does.
    """
    partial = [
        copy.deepcopy(entry)
        for entry in entries
        if entry.get("event") == "attempt_start" or entry.get("phase") == "prep"
    ][:3]
    for entry in partial:
        entry["attempt"] = attempt_number
    return partial


def _without(entries, key):
    """A copy of the log with one key gone from every entry that carries it.

    A log written before the game recorded a field looks exactly like this, and
    it is the shape both fields added after the first logs were written have to
    be readable in.
    """
    stripped = copy.deepcopy(entries)
    for entry in stripped:
        entry.pop(key, None)
    return stripped


def _prep_indices(entries, actor):
    return [
        index
        for index, entry in enumerate(entries)
        if entry.get("phase") == "prep" and entry.get("actor") == actor
    ]


def _renumber(entries):
    """Restate the prep turn numbers and the prep-turn total as the game would.

    A mutation that removes a placement leaves the numbering and the recorded
    total describing the log before it, which fires the wrong guard. This is
    what isolates a case to the fault it means to represent.
    """
    turn = 0
    for entry in entries:
        if entry.get("phase") == "prep":
            turn += 1
            entry["turn_number"] = turn
        elif entry.get("event") == "game_over":
            entry["total_prep_turns"] = turn
    return entries


def _broken_logs(puzzles, directory):
    """A log per way a file can fail to describe the run it records.

    Most cases are the fixture puzzle's valid log with one thing changed, and
    each carries the fragment of the refusal it must produce. Matching the
    fragment is what makes the case a check: any of these raises something, and
    a case that fired a different guard from the one it names would otherwise
    pass unnoticed.

    Five cases are files rather than mutations of one, because a file that does
    not decode and a path that cannot be read are ways of naming the wrong file
    rather than ways of writing a bad one. A sixth is the order fixture's log,
    which is a different valid log rather than a broken one: it is the only case
    here whose fault is invisible on the fixture above.

    Yields ``(what is wrong, path, fragment of the refusal)``.
    """
    directory = Path(directory)
    puzzle = puzzles["fixture"]
    valid = _fixture_entries(puzzle, _FIXTURE_PLAY, _FIXTURE_CHOOSERS)
    agent = _prep_indices(valid, AGENT)
    opponent = _prep_indices(valid, OPPONENT)
    steps = valid[-1]["total_battle_steps"]

    def drop_key(index, key):
        def mutate(entries):
            del entries[index][key]
        return mutate

    def put(index, key, value):
        def mutate(entries):
            entries[index][key] = value
        return mutate

    def swap_turn_numbers(entries):
        entries[agent[0]]["turn_number"] = entries[opponent[0]]["turn_number"]
        entries[opponent[0]]["turn_number"] = 1

    def drop_last_agent_placement(entries):
        entries.pop(agent[1])
        _renumber(entries)

    def stretch_the_battle(entries):
        # Both sides of the battle-step count moved together, so the count check
        # has nothing to say and only the replay can tell that the battle the
        # file describes is a step longer than this play produces.
        entries.insert(-1, dict(entries[-2]))
        entries[-1]["total_battle_steps"] += 1

    cases = [
        (
            "an entry that is not a dictionary",
            lambda entries: entries.insert(1, "attempt_start"),
            "entry 1 is str, not a dictionary",
        ),
        (
            "a prep entry whose identity went missing",
            drop_key(agent[0], "puzzle_id"),
            "names no puzzle attempt and does not declare itself free play",
        ),
        (
            "a prep entry placed by neither side",
            put(agent[0], "actor", "spectator"),
            "which is neither the agent",
        ),
        (
            "a prep entry naming an unreadable unit type",
            put(agent[0], "unit_type", "Z"),
            "places the unreadable unit type 'Z'",
        ),
        (
            "a prep entry on a square that is not the agent's",
            put(agent[0], "position", {"row": 2, "col": 0}),
            "which is not a square the llm may place on",
        ),
        (
            "a prep entry on a square that is not the opponent's",
            put(opponent[0], "position", {"row": 0, "col": 0}),
            "which is not a square the human may place on",
        ),
        (
            "a prep entry whose position is not a row/col pair",
            put(agent[0], "position", [0, 1]),
            "rather than the {row, col} pair",
        ),
        (
            "a prep entry stating a chooser that is neither the model nor the fallback",
            put(agent[0], "chooser", "human"),
            "which is neither 'model' nor 'fallback'",
        ),
        (
            "a prep entry attributing the scripted opponent's placement to a chooser",
            put(opponent[0], "chooser", MODEL),
            "attributes a placement by the scripted opponent to the chooser",
        ),
        (
            "a prep entry whose gold is not a number",
            put(agent[0], "gold_remaining", "one"),
            "rather than a number",
        ),
        (
            "prep entries the game did not number in order",
            swap_turn_numbers,
            "rather than the 1..4 TurnManager counts them off in",
        ),
        (
            # Bumping the recorded count rather than removing a placement, which
            # would break the turn numbering as well and fire that guard first.
            # A placement the file never received is caught either way.
            "an attempt whose prep entries do not number what the game counted",
            lambda entries: entries[-1].update(
                total_prep_turns=entries[-1]["total_prep_turns"] + 1
            ),
            "prep placements and its own game_over counted",
        ),
        (
            "an attempt holding fewer battle entries than the game counted",
            lambda entries: entries.__setitem__(
                -1, dict(entries[-1], total_battle_steps=99)
            ),
            "battle steps and its own game_over counted 99",
        ),
        (
            "a game_over stating no prep-turn count",
            drop_key(-1, "total_prep_turns"),
            "stating no total_prep_turns",
        ),
        (
            "a game_over stating no battle-step count",
            drop_key(-1, "total_battle_steps"),
            "stating no total_battle_steps",
        ),
        (
            "a game_over missing a score field",
            drop_key(-1, "llm_escaped"),
            "stating no readable llm_escaped",
        ),
        (
            "a game_over whose winner is not a label the game writes",
            put(-1, "winner", "Nobody"),
            "which is none of the labels turn_manager._end_game writes",
        ),
        (
            # The fixture is one attempt, so the attempt whose outcome this
            # removes is also the last one in the file, which is the shape an
            # ablation that stops itself leaves. Nothing about it is a loss, and
            # what it leaves is a log stating no attempt that was played through.
            "a log whose only attempt never reached a game_over entry",
            lambda entries: entries.pop(),
            "states no puzzle attempt the run played to an outcome",
        ),
        (
            "an attempt that states a second game_over",
            lambda entries: entries.append(dict(entries[-1])),
            "states a second game_over at entry",
        ),
        (
            "an attempt stated in two separate blocks",
            lambda entries: entries.extend(copy.deepcopy(entries)),
            "in two separate blocks",
        ),
        (
            "a prep entry whose gold does not follow from what it bought",
            lambda entries: entries[agent[0]].update(
                gold_remaining=entries[agent[0]]["gold_remaining"] + 1
            ),
            "gold and Shop.purchase recorded",
        ),
        (
            "a play buying a unit the puzzle's shop does not sell",
            put(agent[1], "unit_type", "C"),
            "which is not a complete legal play of puzzle fixture",
        ),
        (
            "a play the agent could not have stopped where it did",
            drop_last_agent_placement,
            "which is not a complete legal play of puzzle fixture",
        ),
        (
            "a log naming a puzzle the suite does not list",
            lambda entries: [entry.update(puzzle_id="absent") for entry in entries],
            "names a puzzle",
        ),
        (
            "a log stating the puzzle's opponent differently",
            put(opponent[0], "position", {"row": 3, "col": 0}),
            "states a different puzzle from the one the suite does",
        ),
        (
            "positions read column-first rather than by their field names",
            lambda entries: [
                entries[index].update(
                    position={
                        "row": entries[index]["position"]["col"],
                        "col": entries[index]["position"]["row"],
                    }
                )
                for index in agent
            ],
            "does not reproduce the battle the game recorded",
        ),
        (
            "a game_over recording a battle this play does not produce",
            lambda entries: entries[-1].update(
                llm_score=entries[-1]["llm_score"] + 1
            ),
            "does not reproduce the battle the game recorded",
        ),
        (
            "a game_over recording a battle a step longer than this play runs",
            stretch_the_battle,
            "steps %d replayed against %d recorded" % (steps, steps + 1),
        ),
        (
            "a log stating no attempt at all",
            lambda entries: entries.clear(),
            "states no puzzle attempt",
        ),
        (
            # Nothing follows the attempt a run stopped part way through, so one
            # with a whole attempt after it lost its game_over rather than never
            # writing one, and is a loss like any other.
            "an attempt with no outcome that is not where the run stopped",
            lambda entries: entries.__setitem__(
                slice(0, 0), _stopped_part_way(entries, 2)
            ),
            "never reached a game_over entry",
        ),
    ]

    for index, (description, mutate, fragment) in enumerate(cases):
        entries = copy.deepcopy(valid)
        mutate(entries)
        path = directory / ("broken-%d.json" % index)
        path.write_text(json.dumps(entries))
        yield description, path, fragment

    not_json = directory / "not-json.json"
    not_json.write_text("GameLogger: Saved log to user://game_logs/game_x.json")
    yield "a file that is not JSON", not_json, "does not read as JSON text"

    not_array = directory / "not-array.json"
    not_array.write_text(json.dumps({"entries": valid}))
    yield "a root that is not an array of entries", not_array, "the root of"

    not_text = directory / "not-text.json"
    not_text.write_bytes(bytes(range(200, 256)) * 4)
    yield "a file that does not decode as text", not_text, "does not read as JSON text"

    yield (
        "a log path that is not there",
        directory / "no-such-log.json",
        "cannot be read (No such file or directory)",
    )
    yield "a directory named as a log", directory, "cannot be read (Is a directory)"

    # The order fixture. Its two agent placements swap positions and keep their
    # turn numbers, so the file states the same two units on the same two
    # squares in the order the game did not place them in. They cost the same,
    # so the gold still reconciles; the play is still legal, the opponent still
    # matches, and only the replay can tell.
    scrambled = _fixture_entries(puzzles["order"], _ORDER_PLAY)
    first, second = _prep_indices(scrambled, AGENT)
    scrambled[first]["position"], scrambled[second]["position"] = (
        scrambled[second]["position"],
        scrambled[first]["position"],
    )
    scrambled_path = directory / "scrambled-order.json"
    scrambled_path.write_text(json.dumps(scrambled))
    yield (
        "a log stating its placements in the order they were not made in",
        scrambled_path,
        "winner tie replayed against llm recorded",
    )


def _broken_landscapes(valid_path, suite_path, artifacts, directory):
    """A staged artifact directory per way scoring can be wrong about the puzzle.

    None of these is reachable by breaking a log: every one needs an artifact
    the run's puzzle names, since a puzzle with no artifact is enumerated
    instead and reaches none of this. So each is a real artifact directory with
    the ground moved under it afterwards, the way ``generate.py`` stages its
    staleness cases.

    Two of the four are the artifact that cannot be read at all rather than the
    artifact that says the wrong thing, which is the same distinction the log
    side draws between a bad file and the wrong file.

    Yields ``(what moved, log path, suite path, artifact directory, fragment)``.
    """
    directory = Path(directory)

    # A suite that has gained a shop entry the recorded play never bought. The
    # log still reads against it exactly as it did before, which is the whole
    # point: nothing in the file states shop membership, so the artifact's
    # fingerprint is the only thing left that can see the edit.
    wider = json.loads(suite_path.read_text())
    wider["puzzles"][0]["llm_shop"] = wider["puzzles"][0]["llm_shop"] + ["C"]
    wider_path = directory / "wider_shop_suite.json"
    wider_path.write_text(json.dumps(wider))
    yield (
        "a suite whose shop the artifact was not built from",
        valid_path,
        wider_path,
        artifacts,
        "llm_shop is ['A', 'B'] in the artifact and ['A', 'B', 'C'] in the file",
    )

    # An artifact that passes every check load_analysis makes and holds a value
    # for this play that the game's own margin contradicts. Nothing about the
    # suite moved, so only the cross-check in score_run is left to catch it.
    wrong_value = directory / "wrong-value-artifacts"
    shutil.copytree(artifacts, wrong_value)
    artifact_path = wrong_value / "puzzle_fixture.json"
    built = json.loads(artifact_path.read_text())
    key = analysis.encode_play(_FIXTURE_PLAY)
    built["play_values"][key] += 1
    artifact_path.write_text(json.dumps(built))
    yield (
        "an artifact holding a value the recorded battle contradicts",
        valid_path,
        suite_path,
        wrong_value,
        "the landscape values this play at",
    )

    # An artifact path that exists and cannot be opened. A directory is the
    # shape of that this test can build; an unreadable mode is not, since the
    # self-check has to pass as root as well.
    a_directory = directory / "directory-artifacts"
    shutil.copytree(artifacts, a_directory)
    (a_directory / "puzzle_fixture.json").unlink()
    (a_directory / "puzzle_fixture.json").mkdir()
    yield (
        "an artifact path that is a directory",
        valid_path,
        suite_path,
        a_directory,
        "cannot be read (Is a directory)",
    )

    # An artifact whose write was killed part way through. It exists, it is the
    # right name, and nothing but decoding it can tell.
    truncated = directory / "truncated-artifacts"
    shutil.copytree(artifacts, truncated)
    written = (artifacts / "puzzle_fixture.json").read_text()
    (truncated / "puzzle_fixture.json").write_text(written[: len(written) // 2])
    yield (
        "an artifact whose write was killed part way through",
        valid_path,
        suite_path,
        truncated,
        "does not read as JSON text",
    )


def _self_check(args):
    """Fire every refusal on fixtures, and score the valid logs they are built from.

    The negative cases are what say the guards work; the positive cases are what
    say they do not fire on a log that is right, which a file of guards alone
    cannot establish.

    Every refusal this module makes has a case here. Two of them are about a
    file the run needs and cannot read rather than about the run, and they are
    staged as artifact directories because that is the only place a log cannot
    reach them from.

    The valid logs are scored twice, once with no artifact directory and once
    against artifacts written from the fixture suite, because those are two
    different halves of ``landscapes_for`` and only one of them runs at a time.
    Holding the two to the same rows is also what says an artifact read back is
    the landscape enumerating would have produced.
    """
    failed = False
    fired = 0
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        suite_path, puzzles = _fixture_suite(directory)

        valid_path = directory / "valid.json"
        entries = _fixture_entries(puzzles["fixture"], _FIXTURE_PLAY, _FIXTURE_CHOOSERS)
        valid_path.write_text(json.dumps(entries))

        run = load_run(valid_path, suite_path)
        attempts = run.attempts()
        rows = score_run(run, directory / "no-artifacts")
        if len(attempts) == 1 and attempts[0].play == _FIXTURE_PLAY:
            print(
                "a log of a play the game could have made scores: %s, value %d, "
                "regrets %s"
                % (
                    analysis.encode_play(attempts[0].play),
                    rows[0].value,
                    [row.regret for row in rows],
                )
            )
        else:
            print("THE VALID FIXTURE DID NOT READ BACK: %s" % (attempts,))
            failed = True

        if (
            tuple(row.chooser for row in rows) == _FIXTURE_CHOOSERS
            and "made 1 of the agent's 2 placements (50.0%)" in _chooser_rate(rows)
        ):
            print(
                "what made each placement reaches the row its regret is on (%s), and "
                "the rate is reported: %s"
                % (
                    ", ".join(row.chooser_label for row in rows),
                    _chooser_rate(rows),
                )
            )
        else:
            print(
                "THE CHOOSER DID NOT REACH THE ROWS: %r"
                % (tuple(row.chooser for row in rows),)
            )
            failed = True

        silent_chooser_path = directory / "no-chooser.json"
        silent_chooser_path.write_text(json.dumps(_without(entries, "chooser")))
        silent_chooser = load_run(silent_chooser_path, suite_path)
        silent_rows = score_run(silent_chooser, directory / "no-artifacts")
        if (
            silent_chooser.attempts()[0].choosers == (UNSTATED, UNSTATED)
            and [row.chooser_label for row in silent_rows] == ["unstated"] * 2
            and "states what chose none of the 2 placements" in _chooser_rate(silent_rows)
            and [row.regret for row in silent_rows] == [row.regret for row in rows]
        ):
            print(
                "a log written before the game recorded the chooser still scores, and "
                "says so rather than crediting the model: %s"
                % _chooser_rate(silent_rows)
            )
        else:
            print("A LOG STATING NO CHOOSER WAS NOT READ AS UNSTATED")
            failed = True

        order_path = directory / "valid-order.json"
        order_path.write_text(json.dumps(_fixture_entries(puzzles["order"], _ORDER_PLAY)))
        order_attempts = load_run(order_path, suite_path).attempts()
        if len(order_attempts) == 1 and order_attempts[0].play == _ORDER_PLAY:
            print(
                "a log whose placement order decides the battle reads back in that "
                "order: %s" % analysis.encode_play(order_attempts[0].play)
            )
        else:
            print("THE ORDER FIXTURE DID NOT READ BACK: %s" % (order_attempts,))
            failed = True

        artifacts = directory / "artifacts"
        with contextlib.redirect_stdout(io.StringIO()):
            analysis.write_artifacts(
                artifacts,
                suite_path,
                [analysis.analyze_puzzle(puzzle) for puzzle in puzzles.values()],
            )
        if score_run(run, artifacts) == rows:
            print(
                "the same run scores the same from a written artifact as from "
                "enumerating: %d placements" % len(rows)
            )
        else:
            print("SCORING FROM AN ARTIFACT DISAGREED WITH ENUMERATING")
            failed = True

        stopped_path = directory / "stopped-part-way.json"
        stopped_path.write_text(
            json.dumps(entries + _stopped_part_way(entries, 2))
        )
        stopped = load_run(stopped_path, suite_path)
        if (
            len(stopped.unfinished) == 1
            and score_run(stopped, artifacts) == rows
        ):
            print(
                "an attempt the run stopped part way through is named and costs the "
                "attempts before it nothing: %s"
                % stopped.unfinished[0].name
            )
        else:
            print("A RUN THAT STOPPED PART WAY THROUGH AN ATTEMPT DID NOT SCORE")
            failed = True

        if attempts[0].play_all_attempts is False and "first solve" in _stopping_rule(
            attempts
        ):
            print(
                "the stopping rule the attempt was played under reads back: %s"
                % _stopping_rule(attempts)
            )
        else:
            print("THE STOPPING RULE DID NOT READ BACK: %r" % (attempts[0].play_all_attempts,))
            failed = True

        silent_path = directory / "no-stopping-rule.json"
        silent_path.write_text(json.dumps(_without(entries, "play_all_attempts")))
        silent_run = load_run(silent_path, suite_path)
        if (
            silent_run.attempts()[0].play_all_attempts is None
            and "does not state" in _stopping_rule(silent_run.attempts())
            and score_run(silent_run, artifacts) == rows
        ):
            print(
                "a log written before the game recorded the stopping rule still "
                "scores, and says the rule is unstated rather than assuming one"
            )
        else:
            print("A LOG STATING NO STOPPING RULE WAS NOT READ AS UNSTATED")
            failed = True

        free_play_path = directory / "with-free-play.json"
        free_play_path.write_text(
            json.dumps(
                [{"play_mode": "free_play", "turn_number": 0, "event": "attempt_start"}]
                + entries
            )
        )
        free_play = load_run(free_play_path, suite_path)
        if len(free_play.attempts()) == 1 and free_play.free_play_entries == 1:
            print(
                "an entry the file declares is not part of a puzzle attempt is counted "
                "and not lost: %d of them" % free_play.free_play_entries
            )
        else:
            print("A FREE-PLAY ENTRY WAS TREATED AS A LOSS")
            failed = True

        for description, path, fragment in _broken_logs(puzzles, directory):
            try:
                load_run(path, suite_path).attempts()
            except (RunNotMeasurable, prep.SuiteNotMeasurable) as error:
                fired += 1
                if fragment in str(error):
                    print("guard fires on %s: %s" % (description, error))
                else:
                    print(
                        "GUARD FIRED WITH THE WRONG REASON on %s, expected %r: %s"
                        % (description, fragment, error)
                    )
                    failed = True
            else:
                print("GUARD DID NOT FIRE on %s, %s" % (description, path))
                failed = True

        for description, log, suite, out_dir, fragment in _broken_landscapes(
            valid_path, suite_path, artifacts, directory
        ):
            try:
                score_run(load_run(log, suite), out_dir)
            except (RunNotMeasurable, analysis.ArtifactNotCurrent) as error:
                fired += 1
                if fragment in str(error):
                    print("guard fires on %s: %s" % (description, error))
                else:
                    print(
                        "GUARD FIRED WITH THE WRONG REASON on %s, expected %r: %s"
                        % (description, fragment, error)
                    )
                    failed = True
            else:
                print("GUARD DID NOT FIRE on %s, %s" % (description, out_dir))
                failed = True

        undecodable_suite = directory / "not-text-suite.json"
        undecodable_suite.write_bytes(bytes(range(200, 256)) * 4)
        for description, path in (
            ("a suite path that is not there", directory / "no-such-suite.json"),
            ("a suite path that does not decode as text", undecodable_suite),
        ):
            try:
                load_run(valid_path, path)
            except prep.SuiteNotMeasurable as error:
                fired += 1
                print("guard fires on %s: %s" % (description, error))
            else:
                print("GUARD DID NOT FIRE on %s, %s" % (description, path))
                failed = True

    print("%d refusals fired, each on the fault it names" % fired)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(
        description="Score the plays a Godot game log records against the oracle."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser(
        "score",
        help="one row per placement, with the puzzle's difficulty and the "
        "placement's regret",
    )
    score.add_argument(
        "--log", required=True, help="a game_<session>.json written by GameLogger"
    )
    score.add_argument(
        "--puzzles",
        default=prep.DEFAULT_PUZZLE_PATH,
        help="the puzzle suite the run was played on (default: the game's own suite)",
    )
    score.add_argument(
        "--artifacts",
        default=analysis.DEFAULT_OUT_DIR,
        help="where this suite's landscapes are, if they have been built "
        "(default: oracle/artifacts). A puzzle with no artifact is enumerated",
    )
    score.set_defaults(handler=_score)

    check = sub.add_parser(
        "self-check",
        help="fire every refusal on a fixture log, and score a valid one",
    )
    check.set_defaults(handler=_self_check)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
