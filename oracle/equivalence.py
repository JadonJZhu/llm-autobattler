"""Differential test of the Python battle oracle against the real Godot engine.

The oracle exists because Godot cannot be paid per game, and the cost of that
choice is two implementations of one rule set. Two implementations can disagree
while both keep producing healthy-looking numbers, so this harness is the reason
to believe the oracle at all: it sweeps positions through ``oracle/engine.py``
and through ``godot/tools/battle_trace.gd``, which drives the shipped
``BattleEngine``, and requires them to agree on the winner, on every score
field, and on every per-step event.

Every case is then resolved a third time, untraced. ``analysis.py`` resolves
boards with the default ``trace=False``, so that is the path the study's
difficulty and regret figures come from, and requiring it to reach the same
final record as the traced path puts it inside this sweep rather than leaving
it covered by the argument that the two paths share their rule logic. Only the
final record is compared there, because an untraced battle keeps no steps.

Run it:

    python3 oracle/equivalence.py            # 17,190 cases, about 10 seconds
    python3 oracle/equivalence.py --full     # 743,900 cases, about 4 minutes

Any disagreement prints the offending case as a JSON file that can be replayed
through either side on its own, and exits non-zero. So does a battle that fails
to terminate on either side, and so does a sweep that produced no cases at all:
a harness that compares nothing would otherwise report success having
established nothing.

``--engine PATH`` runs the whole thing against a different copy of the engine,
which is how the harness itself is tested: point it at a deliberately broken
copy and it must fail. The chosen module is installed as ``engine`` before
``prep`` is imported, so the preparation phase builds its boards on the same
copy the battles are resolved with, and that is exactly why a broken constant
needs a check of its own. A wrong unit cost or a wrong home row only changes
which boards prep builds; the same board then goes to both sides, they agree,
and the sweep silently gets smaller. So before any sweep runs, the constants
that decide which boards get built are checked against the GDScript the shipped
game loads them from. That covers the engine's own, and the two the preparation
phase holds outside the engine module for the same reason: ``prep``'s default
starting gold and the agent shop size ``generate`` deals.

What that leaves untested is prep's own logic. Turn order, the affordability
rule and the enumeration of plays have no Godot counterpart on this path, so a
fault in ``prep.py`` itself is not caught here.
"""

import argparse
import importlib.util
import itertools
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENGINE = REPO_ROOT / "oracle" / "engine.py"
GODOT_PROJECT = REPO_ROOT / "godot"
TRACE_SCRIPT = "tools/battle_trace.gd"

# The shipped game's own declarations of the board shape, the unit table and
# the shop, read as text because the constants check has to see them without
# Godot.
GRID_CONSTANTS_GD = GODOT_PROJECT / "scripts" / "grid_constants.gd"
UNIT_DATA_GD = GODOT_PROJECT / "scripts" / "unit_data.gd"
SHOP_GD = GODOT_PROJECT / "scripts" / "shop.gd"

# Godot costs about 0.29s to start and about 0.75ms per case (measured
# 2026-09-09 by driving battle_trace.gd over the boards prep builds from the
# shipped puzzle suite, every play of its three puzzles, cycled to fill the
# batch, best of three: 1 case in 0.28s, 2,000 in 1.78s, 10,000 in 9.50s,
# 25,000 in 20.12s, 100,000 in 74.89s). The machine is shared and under load,
# so read these as good to roughly 1.23x and no better. At 25,000 cases a
# batch, startup is about 1.5% of the run and one batch of prep boards holds
# roughly 15MB of input and 72MB of trace, which is small enough to parse whole.
DEFAULT_BATCH = 25000

DEFAULT_SEED = 20260907

# The owner names battle_trace.gd accepts, keyed by engine.LLM and
# engine.OPPONENT. The opponent is "human" there because the shipped game calls
# it that. Spelled with literals because the engine module is chosen at runtime.
OWNER_LABELS = {0: "llm", 1: "human"}
OWNER_FROM_LABEL = {label: owner for owner, label in OWNER_LABELS.items()}

engine = None
prep = None
generate = None
engine_path = None


def load_modules(path):
    """Import the engine under test, then prep and generate on top of it.

    ``prep`` does ``import engine``, so installing the chosen module under that
    name first is what makes ``--engine`` cover board construction as well as
    battle resolution. ``generate`` imports both and must come after them for
    the same reason: imported first, it would cache a ``prep`` built on the
    default engine and ``--engine`` would quietly stop covering anything.
    """
    global engine, prep, generate, engine_path
    engine_path = path
    spec = importlib.util.spec_from_file_location("engine", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["engine"] = module
    spec.loader.exec_module(module)
    engine = module
    prep = importlib.import_module("prep")
    generate = importlib.import_module("generate")


# --- The constants the shipped game declares ---


def gd_match(source, path, pattern, name):
    match = re.search(pattern, source, re.M | re.S)
    if match is None:
        raise RuntimeError("cannot read %s out of %s" % (name, path))
    return match


def gd_int(source, path, name):
    return int(gd_match(source, path, r"^const %s\b[^=]*=\s*(-?\d+)" % name, name).group(1))


def gd_int_array(source, path, name):
    body = gd_match(source, path, r"^const %s\b[^=]*=\s*\[([^\]]*)\]" % name, name).group(1)
    return tuple(int(entry) for entry in body.replace(",", " ").split())


def gd_enum(source, path, name):
    """A GDScript enum with no explicit values, as {member name: its index}."""
    body = gd_match(source, path, r"^enum %s\s*\{([^}]*)\}" % name, name).group(1)
    members = [member.strip() for member in body.split(",") if member.strip()]
    return {member: index for index, member in enumerate(members)}


def gd_unit_dict(source, path, name, unit_types):
    """A ``UnitType``-keyed const dictionary, rekeyed to the type's index.

    Values are read as the ints and quoted strings those tables actually hold;
    anything else is a table this cannot check and says so.
    """
    body = gd_match(source, path, r"^const %s\b[^=]*=\s*\{(.*?)^\}" % name, name).group(1)
    table = {}
    for member, raw in re.findall(r"UnitType\.(\w+)\s*:\s*([^,\n]+)", body):
        raw = raw.strip()
        if re.fullmatch(r'"[^"]*"', raw):
            value = raw[1:-1]
        elif re.fullmatch(r"-?\d+", raw):
            value = int(raw)
        else:
            raise RuntimeError("%s in %s holds %s, which this cannot read" % (name, path, raw))
        table[unit_types[member]] = value
    if len(table) != len(unit_types):
        raise RuntimeError(
            "%s in %s covers %d of the %d unit types"
            % (name, path, len(table), len(unit_types))
        )
    return table


def check_constants():
    """Require the oracle to hold the shipped game's constants.

    Battle resolution is compared case by case, but the board a case starts
    from is built by prep and handed to both sides, so a constant only the
    preparation phase reads (the unit costs, the home rows) cannot disagree
    with anything: it changes which boards get swept, silently. That is what
    this check is for, and it applies past the engine module to the two such
    constants prep and generate hold themselves, so those are checked here
    beside the engine's. The GDScript is the ground truth the port was written
    from, so the comparison is against the game's own declarations rather than
    against a second copy of the numbers kept here.
    """
    grid = GRID_CONSTANTS_GD.read_text()
    units = UNIT_DATA_GD.read_text()
    shop = SHOP_GD.read_text()
    unit_types = gd_enum(units, UNIT_DATA_GD, "UnitType")
    owners = gd_enum(units, UNIT_DATA_GD, "Owner")
    expected = {
        (engine, "ROWS"): gd_int(grid, GRID_CONSTANTS_GD, "ROWS"),
        (engine, "COLS"): gd_int(grid, GRID_CONSTANTS_GD, "COLS"),
        (engine, "LLM_ROWS"): gd_int_array(grid, GRID_CONSTANTS_GD, "LLM_ROWS"),
        (engine, "OPPONENT_ROWS"): gd_int_array(grid, GRID_CONSTANTS_GD, "HUMAN_ROWS"),
        (engine, "A"): unit_types["A"],
        (engine, "B"): unit_types["B"],
        (engine, "C"): unit_types["C"],
        (engine, "D"): unit_types["D"],
        (engine, "LLM"): owners["LLM"],
        (engine, "OPPONENT"): owners["HUMAN"],
        (engine, "TYPE_LABELS"): gd_unit_dict(units, UNIT_DATA_GD, "TYPE_LABELS", unit_types),
        (engine, "UNIT_COSTS"): gd_unit_dict(units, UNIT_DATA_GD, "UNIT_COSTS", unit_types),
        # The gold puzzle_loader.gd defaults a missing gold field to, and the
        # shop size Shop.create_randomized deals, which is the size generate
        # gives the agent.
        (prep, "STARTING_GOLD"): gd_int(shop, SHOP_GD, "STARTING_GOLD"),
        (generate, "AGENT_SHOP_SIZE"): gd_int(shop, SHOP_GD, "SHOP_SIZE"),
    }
    mismatches = [
        "  %s.%s: holds %r, shipped %r" % (module.__name__, name, getattr(module, name), value)
        for (module, name), value in expected.items()
        if getattr(module, name) != value
    ]
    if mismatches:
        raise RuntimeError(
            "the oracle (engine %s) does not hold the constants the shipped "
            "game declares:\n%s" % (engine_path, "\n".join(mismatches))
        )
    return len(expected)


# --- Cases ---


def case_of(case_id, board):
    """The JSON case battle_trace.gd and engine.py's CLI both read.

    Units are emitted in square order so the same board always produces the same
    case text, whatever order the generator happened to build it in.
    """
    return {
        "id": case_id,
        "units": [
            {
                "row": pos[0],
                "col": pos[1],
                "type": engine.TYPE_LABELS[unit[0]],
                "owner": OWNER_LABELS[unit[1]],
                "placement_order": unit[2],
            }
            for pos, unit in sorted(board.items())
        ],
    }


def all_cells():
    return [(row, col) for row in range(engine.ROWS) for col in range(engine.COLS)]


def board_of(cells, types, owners, orders):
    return {
        cell: (unit_type, owner, order)
        for cell, unit_type, owner, order in zip(cells, types, owners, orders)
    }


# --- Sweep: the starting positions the study will actually enumerate ---

# Scripted opponents, in the shape puzzle_loader.gd reads. Between them they
# cover a full opponent half, a two-D back line, a single advancing row, a queue
# that runs out of gold part-way, and a queue with a repeated square, so the
# refusal path in prep is exercised as well as the placements that succeed.
OPPONENT_SCRIPTS = [
    {
        "gold": 6,
        "shop": ["A", "B", "D"],
        "placements": [("A", 2, 0), ("A", 2, 1), ("B", 2, 2), ("B", 3, 2), ("D", 3, 1)],
    },
    {
        "gold": 6,
        "shop": ["A", "C", "D"],
        "placements": [("C", 2, 0), ("A", 2, 1), ("A", 2, 2), ("D", 3, 1), ("D", 3, 0)],
    },
    {
        "gold": 5,
        "shop": ["D", "A", "B", "C"],
        "placements": [("D", 3, 2), ("B", 2, 2), ("B", 2, 1), ("C", 2, 0)],
    },
    {
        "gold": 3,
        "shop": ["A"],
        "placements": [("A", 3, 0), ("A", 3, 1), ("A", 3, 2)],
    },
    {
        "gold": 4,
        "shop": ["D", "B"],
        "placements": [("D", 2, 1), ("D", 3, 1)],
    },
    {
        "gold": 6,
        "shop": ["C", "B"],
        "placements": [
            ("C", 2, 0),
            ("C", 2, 1),
            ("C", 2, 2),
            ("B", 3, 0),
            ("B", 3, 1),
            ("B", 3, 2),
        ],
    },
    {
        "gold": 1,
        "shop": ["A", "B", "C"],
        "placements": [("A", 2, 1), ("B", 2, 0)],
    },
    {
        "gold": 3,
        "shop": ["A", "D"],
        "placements": [("A", 2, 0), ("A", 2, 0), ("D", 3, 2)],
    },
]

# Every shop the design admits, since can_afford asks only whether a type is in
# the shop: duplicate slots collapse, so the distinct shops are the non-empty
# subsets of the four types.
SHOP_SUBSETS = [
    list(labels)
    for size in range(1, 5)
    for labels in itertools.combinations("ABCD", size)
]

def synthetic_suite():
    """Puzzle suite JSON spanning the gold band and every shop composition.

    The band is generate's, not a copy of it: generate decides what gold the
    generated puzzles actually hold, and this sweep exists to cover that space,
    so a band that widened there has to widen here or the cover goes stale
    without saying so.
    """
    puzzles = []
    for index, (gold, shop) in enumerate(
        itertools.product(generate.GOLD_BAND, SHOP_SUBSETS)
    ):
        script = OPPONENT_SCRIPTS[index % len(OPPONENT_SCRIPTS)]
        puzzles.append(
            {
                "id": "synthetic-%s-g%d" % ("".join(shop), gold),
                "llm_shop": list(shop),
                "llm_gold": gold,
                "opponent_shop": list(script["shop"]),
                "opponent_gold": script["gold"],
                "opponent_placements": [
                    {"type": label, "row": row, "col": col}
                    for label, row, col in script["placements"]
                ],
            }
        )
    return {"puzzles": puzzles}


def load_synthetic_puzzles(work_dir):
    """Write the synthetic suite out and read it back through prep's own loader.

    Going through the loader rather than building Puzzle objects directly means
    these are puzzles the shipped loader accepts, and ``Suite.puzzles`` is what
    the sweep needs from it rather than ``prep.check_queue_lands``: the scripts
    deliberately queue placements prep refuses at run time, an unaffordable one
    and one onto a taken square, so the property here is that every placement
    the file lists reached prep, not that every one reached the board. That is
    exactly what ``Suite.puzzles`` holds, at every level the loader can discard
    at. Without it a mistyped square or shop label would shrink the boards swept
    and the sweep would still report a clean run over fewer of them.
    """
    suite = synthetic_suite()
    path = work_dir / "synthetic_puzzles.json"
    path.write_text(json.dumps(suite, indent=2))
    return prep.load_suite(path).puzzles()


def random_play(puzzle, rng):
    """One complete legal play, drawn uniformly at each choice.

    The stopping rule is enumerate_plays': the agent places until it can afford
    nothing or has no free square. simulate_prep rejects anything else, so a
    play that drifted from that rule fails the sweep rather than sneaking in.
    """
    types = tuple(dict.fromkeys(puzzle.llm_shop))
    gold = puzzle.llm_gold
    used = set()
    play = []
    while True:
        affordable = [t for t in types if gold >= engine.UNIT_COSTS[t]]
        free = [square for square in prep.LLM_SQUARES if square not in used]
        if not affordable or not free:
            return tuple(play)
        unit_type = rng.choice(affordable)
        square = rng.choice(free)
        gold -= engine.UNIT_COSTS[unit_type]
        used.add(square)
        play.append(prep.Placement(unit_type, square))


def plays_for(puzzle, limit, rng):
    """Every play when there are at most ``limit`` of them, else a sample."""
    plays = list(itertools.islice(prep.enumerate_plays(puzzle), limit + 1))
    if len(plays) <= limit:
        return plays
    sampled = {}
    while len(sampled) < limit:
        sampled[random_play(puzzle, rng)] = None
    return list(sampled)


def sweep_prep(rng, real_limit, synthetic_limit, work_dir):
    """Starting boards from the preparation phase, real puzzles and synthetic."""
    for puzzle in prep.load_suite().puzzles():
        for play in plays_for(puzzle, real_limit, rng):
            yield prep.build_board(puzzle, play)
    for puzzle in load_synthetic_puzzles(work_dir):
        for play in plays_for(puzzle, synthetic_limit, rng):
            yield prep.build_board(puzzle, play)


# --- Sweep: every small board there is ---


def sweep_exhaustive(max_units):
    """Every board of up to ``max_units`` units.

    Every cell subset, every type and owner assignment, and every placement
    order: 96 boards at one unit, 8,448 at two, 675,840 at three.
    """
    cells = all_cells()
    kinds = [
        (unit_type, owner)
        for unit_type in (engine.A, engine.B, engine.C, engine.D)
        for owner in (engine.LLM, engine.OPPONENT)
    ]
    for count in range(1, max_units + 1):
        for subset in itertools.combinations(cells, count):
            for assignment in itertools.product(kinds, repeat=count):
                types = [kind[0] for kind in assignment]
                owners = [kind[1] for kind in assignment]
                for orders in itertools.permutations(range(count)):
                    yield board_of(subset, types, owners, orders)


# --- Sweeps: positions chosen to stress the rules most likely to diverge ---


def random_orders(rng, count):
    orders = list(range(count))
    rng.shuffle(orders)
    return orders


def has_closest_enemy_tie(board):
    """True when some D's nearest enemy is decided by the column-then-row rule."""
    for pos, (unit_type, owner, _) in board.items():
        if unit_type != engine.D:
            continue
        distances = [
            abs(cell[0] - pos[0]) + abs(cell[1] - pos[1])
            for cell, unit in board.items()
            if unit[1] != owner
        ]
        if distances and distances.count(min(distances)) > 1:
            return True
    return False


def generate_filtered(rng, count, make, keep, description):
    """``count`` boards from ``make`` that satisfy ``keep``.

    The attempt cap turns a generator that stopped producing the thing it is
    named for into a loud failure instead of a hang.
    """
    produced = 0
    attempts = 0
    while produced < count:
        attempts += 1
        if attempts > 200 * count:
            raise RuntimeError(
                "%s: only %d of %d boards in %d attempts"
                % (description, produced, count, attempts)
            )
        board = make(rng)
        if board is None or not keep(board):
            continue
        produced += 1
        yield board


def sweep_d_tiebreak(rng, count):
    """D-heavy boards where the closest-enemy tie-break decides the target."""

    def make(local_rng):
        shooter = local_rng.randrange(2)
        shooters = local_rng.randint(1, 3)
        enemies = local_rng.randint(2, 5)
        friends = local_rng.randint(0, 2)
        total = shooters + enemies + friends
        if total > engine.ROWS * engine.COLS:
            return None
        cells = local_rng.sample(all_cells(), total)
        types = [engine.D] * shooters
        owners = [shooter] * shooters
        for _ in range(enemies):
            types.append(local_rng.randrange(4))
            owners.append(1 - shooter)
        for _ in range(friends):
            types.append(local_rng.randrange(4))
            owners.append(shooter)
        return board_of(cells, types, owners, random_orders(local_rng, total))

    return generate_filtered(
        rng, count, make, has_closest_enemy_tie, "D closest-enemy tie-break"
    )


def sweep_edge_diagonals(rng, count):
    """B and C on the edge columns, where their diagonal attack is off the board."""
    edge_columns = (0, engine.COLS - 1)

    def make(local_rng):
        edge_cells = [
            (row, col) for row in range(engine.ROWS) for col in edge_columns
        ]
        diagonal_count = local_rng.randint(2, 4)
        cells = local_rng.sample(edge_cells, diagonal_count)
        types = [local_rng.choice((engine.B, engine.C)) for _ in cells]
        owners = [local_rng.randrange(2) for _ in cells]
        remaining = [cell for cell in all_cells() if cell not in cells]
        others = local_rng.randint(1, 4)
        extra = local_rng.sample(remaining, others)
        cells = list(cells) + extra
        types += [local_rng.randrange(4) for _ in extra]
        owners += [local_rng.randrange(2) for _ in extra]
        return board_of(cells, types, owners, random_orders(local_rng, len(cells)))

    def both_owners(board):
        return len({unit[1] for unit in board.values()}) == 2

    return generate_filtered(rng, count, make, both_owners, "edge-column B and C")


def sweep_escapes(rng, count):
    """Boards with units on the far edge, one advance from walking off it.

    A unit only ever escapes off its own owner's forward edge, so the runners go
    on the last row for the LLM and the first for the opponent.
    """
    escape_row = {0: engine.ROWS - 1, 1: 0}
    for _ in range(count):
        owner = rng.randrange(2)
        row = escape_row[owner]
        cells = rng.sample(
            [(row, col) for col in range(engine.COLS)], rng.randint(1, engine.COLS)
        )
        types = [rng.randrange(4) for _ in cells]
        owners = [owner] * len(cells)
        remaining = [cell for cell in all_cells() if cell not in cells]
        extra = rng.sample(remaining, rng.randint(0, 4))
        cells = list(cells) + extra
        types += [rng.randrange(4) for _ in extra]
        owners += [rng.randrange(2) for _ in extra]
        yield board_of(cells, types, owners, random_orders(rng, len(cells)))


def sweep_single_owner(rng, count):
    """Boards with only one side on them, larger than the exhaustive sweep reaches."""
    for _ in range(count):
        total = rng.randint(4, engine.ROWS * engine.COLS)
        cells = rng.sample(all_cells(), total)
        owner = rng.randrange(2)
        types = [rng.randrange(4) for _ in cells]
        yield board_of(cells, types, [owner] * total, random_orders(rng, total))


def sweep_crowded(rng, count):
    """Full and nearly full boards, where almost nothing has room to advance."""
    for _ in range(count):
        total = rng.randint(10, engine.ROWS * engine.COLS)
        cells = rng.sample(all_cells(), total)
        types = [rng.randrange(4) for _ in cells]
        owners = [rng.randrange(2) for _ in cells]
        yield board_of(cells, types, owners, random_orders(rng, total))


# --- Comparing the two sides ---


GODOT_LABELS = ("oracle", "godot")
UNTRACED_LABELS = ("untraced", "traced")


def rendered(value, key):
    return json.dumps(value[key]) if key in value else "<missing>"


def first_difference(path, left, right, labels):
    """The first place two parsed records disagree, as a readable line, or None.

    ``labels`` names the two sides in the message. Structural on purpose:
    Godot's JSON.stringify sorts keys and Python's does not, so comparing the
    text would report a difference on every case.
    """
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return "%s.%s: %s %s, %s %s" % (
                    path,
                    key,
                    labels[0],
                    rendered(left, key),
                    labels[1],
                    rendered(right, key),
                )
            difference = first_difference(
                "%s.%s" % (path, key), left[key], right[key], labels
            )
            if difference:
                return difference
        return None
    if isinstance(left, list) and isinstance(right, list):
        # The shared prefix is checked before the lengths, so a battle that ran
        # longer on one side is reported at the step where it went wrong rather
        # than as a step count.
        for index, (mine, theirs) in enumerate(zip(left, right)):
            difference = first_difference("%s[%d]" % (path, index), mine, theirs, labels)
            if difference:
                return difference
        if len(left) != len(right):
            return "%s: %s has %d entries, %s has %d" % (
                path,
                labels[0],
                len(left),
                labels[1],
                len(right),
            )
        return None
    if left != right:
        return "%s: %s %s, %s %s" % (
            path,
            labels[0],
            json.dumps(left),
            labels[1],
            json.dumps(right),
        )
    return None


class Divergence(Exception):
    """A case the two engines did not agree on, or did not finish."""

    def __init__(self, case, reason):
        super().__init__(reason)
        self.case = case
        self.reason = reason
        self.sweep = None


def run_godot(godot_binary, cases_path, out_path):
    result = subprocess.run(
        [
            godot_binary,
            "--headless",
            "--path",
            str(GODOT_PROJECT),
            "-s",
            TRACE_SCRIPT,
            "--cases",
            str(cases_path),
            "--out",
            str(out_path),
        ],
        capture_output=True,
        text=True,
    )
    # The autoloads print on every run, so stdout says nothing about success and
    # the exit code and the output file are what get read.
    if result.returncode != 0:
        raise RuntimeError(
            "battle_trace exited %d\n%s" % (result.returncode, result.stderr.strip())
        )
    with open(out_path) as handle:
        return json.load(handle)["traces"]


def compare_batch(cases, godot_binary, work_dir):
    """Resolve a batch both ways and check every field of every step.

    Returns (steps compared, event type counts). Raises Divergence on the first
    case the two sides do not agree on.
    """
    cases_path = work_dir / "cases.json"
    out_path = work_dir / "godot_traces.json"
    with open(cases_path, "w") as handle:
        json.dump({"cases": cases}, handle)

    godot_started = time.perf_counter()
    godot_traces = run_godot(godot_binary, cases_path, out_path)
    godot_seconds = time.perf_counter() - godot_started

    # Traces are matched by id rather than by position, so a batch that came
    # back short or reordered is caught here instead of quietly comparing the
    # wrong pairs.
    by_id = {trace["id"]: trace for trace in godot_traces}
    if by_id.keys() != {case["id"] for case in cases}:
        raise RuntimeError(
            "battle_trace returned %d distinct traces for %d cases"
            % (len(by_id), len(cases))
        )

    oracle_started = time.perf_counter()
    steps_compared = 0
    event_types = {}
    for case in cases:
        board = {
            (unit["row"], unit["col"]): (
                engine.label_to_type(unit["type"]),
                OWNER_FROM_LABEL[unit["owner"]],
                unit["placement_order"],
            )
            for unit in case["units"]
        }
        oracle = engine.run_battle(board, trace=True)
        untraced = engine.run_battle(board)
        godot = by_id[case["id"]]

        if oracle["aborted"] or godot["aborted"]:
            raise Divergence(
                case,
                "the battle did not terminate within the step cap (oracle aborted "
                "%s, godot aborted %s)" % (oracle["aborted"], godot["aborted"]),
            )
        # Steps first: the earliest step they disagree on names the rule that
        # broke, where the final score only says that something did.
        difference = first_difference(
            "steps", oracle["steps"], godot["steps"], GODOT_LABELS
        )
        if difference is None:
            difference = first_difference(
                "final", oracle["final"], godot["final"], GODOT_LABELS
            )
        if difference is None:
            # The path analysis.py takes. It keeps no steps, so the final record
            # and the abort flag are the whole of what it produces.
            difference = first_difference(
                "untraced",
                {"final": untraced["final"], "aborted": untraced["aborted"]},
                {"final": oracle["final"], "aborted": oracle["aborted"]},
                UNTRACED_LABELS,
            )
        if difference is not None:
            raise Divergence(case, difference)

        steps_compared += len(oracle["steps"])
        for step in oracle["steps"]:
            event_types[step["event_type"]] = event_types.get(step["event_type"], 0) + 1
    oracle_seconds = time.perf_counter() - oracle_started
    return steps_compared, event_types, godot_seconds, oracle_seconds


# --- Running a whole sweep ---


class SweepResult:
    def __init__(self, name):
        self.name = name
        self.cases = 0
        self.steps = 0
        self.event_types = {}
        self.godot_seconds = 0.0
        self.oracle_seconds = 0.0


def run_sweep(name, boards, godot_binary, batch_size, work_dir):
    result = SweepResult(name)
    batch = []

    def flush():
        if not batch:
            return
        steps, event_types, godot_seconds, oracle_seconds = compare_batch(
            batch, godot_binary, work_dir
        )
        result.steps += steps
        result.godot_seconds += godot_seconds
        result.oracle_seconds += oracle_seconds
        for event_type, count in event_types.items():
            result.event_types[event_type] = (
                result.event_types.get(event_type, 0) + count
            )
        print(
            "  %s: %d cases, %d steps (godot %.1fs, oracle %.1fs)"
            % (name, result.cases, result.steps, result.godot_seconds, result.oracle_seconds),
            flush=True,
        )
        batch.clear()

    try:
        for board in boards:
            result.cases += 1
            batch.append(case_of("%s#%d" % (name, result.cases), board))
            if len(batch) >= batch_size:
                flush()
        flush()
    except Divergence as divergence:
        divergence.sweep = name
        raise

    if result.cases == 0:
        raise RuntimeError(
            "sweep %s produced no cases, so it established nothing" % name
        )
    return result


def report_divergence(divergence):
    case_path = Path(
        tempfile.mkstemp(prefix="equivalence-divergence-", suffix=".json")[1]
    )
    case_path.write_text(json.dumps({"cases": [divergence.case]}, indent=2))
    print("")
    print("DIVERGENCE in sweep %s, case %s" % (divergence.sweep, divergence.case["id"]))
    print("  %s" % divergence.reason)
    print("  units: %s" % json.dumps(divergence.case["units"]))
    print("  the case on its own: %s" % case_path)
    print("  replay the traced comparison:")
    print(
        "    python3 %s --cases %s --out /tmp/oracle-trace.json"
        % (engine_path, case_path)
    )
    print(
        "    godot --headless --path %s -s %s --cases %s --out /tmp/godot-trace.json"
        % (GODOT_PROJECT, TRACE_SCRIPT, case_path)
    )


def build_sweeps(full, rng, work_dir):
    """The sweeps to run, as (name, board iterator) pairs.

    Fast mode is sized for routine use: it holds the exhaustive one- and
    two-unit boards whole, and samples the rest. Full mode adds every three-unit
    board, every play of the three real puzzles, and five times the sampling
    everywhere else.
    """
    if full:
        return [
            ("prep-starts", sweep_prep(rng, 100000, 400, work_dir)),
            ("exhaustive-3", sweep_exhaustive(3)),
            ("d-tiebreak", sweep_d_tiebreak(rng, 6000)),
            ("edge-diagonals", sweep_edge_diagonals(rng, 6000)),
            ("far-edge-escapes", sweep_escapes(rng, 6000)),
            ("single-owner", sweep_single_owner(rng, 3000)),
            ("crowded", sweep_crowded(rng, 6000)),
        ]
    return [
        ("prep-starts", sweep_prep(rng, 300, 40, work_dir)),
        ("exhaustive-2", sweep_exhaustive(2)),
        ("d-tiebreak", sweep_d_tiebreak(rng, 1200)),
        ("edge-diagonals", sweep_edge_diagonals(rng, 1200)),
        ("far-edge-escapes", sweep_escapes(rng, 1200)),
        ("single-owner", sweep_single_owner(rng, 600)),
        ("crowded", sweep_crowded(rng, 1200)),
    ]


def print_summary(results, seed, wall_clock):
    print("")
    print("%-18s %10s %10s  %s" % ("sweep", "cases", "steps", "events"))
    for result in results:
        events = " ".join(
            "%s=%d" % (event_type, count)
            for event_type, count in sorted(result.event_types.items())
        )
        print(
            "%-18s %10d %10d  %s"
            % (result.name, result.cases, result.steps, events)
        )
    print(
        "%-18s %10d %10d"
        % (
            "total",
            sum(result.cases for result in results),
            sum(result.steps for result in results),
        )
    )
    print("")
    # The run stops at the first divergence, so reaching this line means none.
    print("seed %d, 0 divergences, %.1fs wall clock" % (seed, wall_clock))


def main():
    parser = argparse.ArgumentParser(
        description="Check the Python battle oracle against the real Godot engine."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="exhaustive three-unit boards and every play of the real puzzles",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="seed for the sampled sweeps"
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        help="cases per Godot invocation (default %d)" % DEFAULT_BATCH,
    )
    parser.add_argument(
        "--engine",
        default=str(DEFAULT_ENGINE),
        help="engine module to test (default %s)" % DEFAULT_ENGINE,
    )
    parser.add_argument("--godot", default=None, help="path to the Godot binary")
    args = parser.parse_args()

    godot_binary = args.godot or shutil.which("godot")
    if not godot_binary or not Path(godot_binary).exists():
        parser.error("no Godot binary found; pass --godot with its path")

    load_modules(args.engine)

    print(
        "engine %s, godot %s, seed %d, batch %d, mode %s"
        % (args.engine, godot_binary, args.seed, args.batch, "full" if args.full else "fast")
    )
    print("%d constants match the shipped GDScript" % check_constants())

    work_dir = Path(tempfile.mkdtemp(prefix="oracle-equivalence-"))
    started = time.perf_counter()
    results = []
    try:
        for name, boards in build_sweeps(args.full, random.Random(args.seed), work_dir):
            results.append(run_sweep(name, boards, godot_binary, args.batch, work_dir))
    except Divergence as divergence:
        report_divergence(divergence)
        print("")
        print(
            "FAILED after %d cases in %.1fs"
            % (
                sum(result.cases for result in results),
                time.perf_counter() - started,
            )
        )
        return 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    print_summary(results, args.seed, time.perf_counter() - started)
    print(
        "PASSED: the oracle and the Godot engine agreed on every step of every "
        "case, and the untraced path analysis.py uses reached the same final "
        "record on all of them."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
