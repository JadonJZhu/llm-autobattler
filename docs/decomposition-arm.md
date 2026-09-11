# The decomposition arm: what is run, what it measures, and what it costs

Written 2026-09-11 in the `decomp` worktree, at commit 2671872. This file is the one home for the
decomposition arm's measurement procedure and its price. Where another file says something different
about this arm, this file is newer.

**What the arm is for, in one sentence.** When a model plays a puzzle badly, this arm says how much of
the loss came from not knowing the rules, how much from knowing them and not being able to run them
forward, how much from being able to run them and not searching enough, and how much from being handed
the right answer and still not picking it.

**The honest limit, in the same breath.** What is exact is the regret of any single observed play:
integer margin points against the oracle, with the per-placement regrets summing to it as a checked
integer. The four numbers are built on top of that and are estimates, differences of arm means over
24 attempts per cell from a stochastic agent, reported signed with bootstrap intervals. What the
design controls is the conditions those means are taken under. The two-way split people actually ask
for, "was it a bad world model or bad search", is provably not recoverable from watching an agent
play, and this arm reports it as an interval rather than a number. The width of that interval is the
paper's headline.

**Status.** Nothing here has been run. This is a design plus a costing. The measurements it rests on
were taken on 2026-09-10 and 2026-09-11 and are labelled throughout. The suite it needs does not exist
yet and Stage 0 of the pilot is the attempt to build it.

---

## 1. What this arm measures and why it is not the prior art

Three pieces of published work sit close enough that a reviewer will name them. Here is what each one
owns and what it leaves.

**STOCKTAKE (arXiv 2607.13618, Deb and Krishnan, 15 July 2026)** owns the framing. It measures the gap
between perception and action in a 26-week supply-chain task against a fair oracle, and its opening
line is one restatement away from ours. It does not own the measurement. Checked by full-text search
rather than by reading the abstract: the words "regret" and "telescop" appear zero times in the whole
paper, so there is no per-decision regret and no summation identity; its oracle is Bayes-optimal in
expectation rather than exact, and the paper concedes agents legitimately beat it on 33 of 196
scoreable runs; and its perception axis is the agent's own stated belief read off natural-language
rationales by a gpt-5-mini grader, which the paper itself calls a lower bound on what the model knows.
"Search" appears once in a methods sense, as the forward scan that computes detection lag, and never as
a quality axis, so an agent with a correct model that searches badly and an agent with a wrong model
land in the same low-skill bucket. That collapse is the gap this arm
fills.

**CalBench (arXiv 2605.09823v3, Zou, Yao, She, Goodman, Hawkins)** owns the instrumentation pairing:
per-instance difficulty computed before any agent runs, `d = F / (T! / (T-M)!)` where F is the number
of feasible assignments returned by CP-SAT, sitting in the same benchmark as regret against that same
CP-SAT optimum. It does not own regret against an exact continuation value over prefixes. Its regret is
labelled in the paper as an upper-bound regret proxy and is aggregated to one scalar per agent per
game; the strings "prefix" and "per-action" are absent from the full text of v3; and v3 reports no
result broken out by difficulty bucket at all. Pin the version when citing: the difficulty definition
was rewritten between v1 (10 May 2026), v2 (28 May 2026) and v3 (5 June 2026). The suite size is not
settled and was not reconciled: the sweep recorded a growth from 72 tasks in v1 to 90 in v3, while the
verification read of v3's full text records a 72-task suite. The version-pinning advice rests on the
difficulty-definition rewrite, which was verified, and does not need the task count.

**Cross-Component Interference (arXiv 2605.05716, Ming Liu, 7 May 2026)** owns the other arm's shape: a
full factorial over all 32 subsets of planning, tool use, memory, self-reflection and retrieval, 118
configurations in the paper body (the arXiv abstract advertises 96, which is the Llama-only primary
setting), 32,000-plus evaluations, exact Shapley values. It touches nothing this arm measures. Checked
by full-text search: "oracle", "regret", "ground truth", "upper bound", "best possible", "dynamics" and
"search" all return zero hits. It is still load-bearing here for one reason: tool use is its
highest-value component (Shapley +0.177, z = 9.1, 70 percent of total scaffold value), which is exactly
why this design carries a null-tool control at L3N. Without that control, our L1-to-L3 result is
explicable in one sentence as a tool-use effect, and the paper that sentence comes from is this one.

**What is left, stated narrowly enough to defend.** Nobody separates model error from search error
against an exact per-prefix `V*` whose per-decision regret telescopes exactly to whole-play regret, in
a deterministic fully enumerable action space. Determinism plus exhaustive enumeration is the
load-bearing part, because it is what buys exactness and telescoping, and both are what STOCKTAKE
forfeits by being stochastic and partially observed.

**The scoop check's population finding.** Seventeen papers were downloaded and grepped in full text
rather than summarised. Twelve of them are LLM game and puzzle benchmarks; the rest are adjacent work
(Grams et al. is an exploration paper, not a game benchmark, and is discussed below). The phrases "search error" and "model
error" occur **zero times across all seventeen**. "Regret" occurs as a metric in three of them
(GTBench, Grams et al., Schmied et al.) and in none of those against an exact optimal continuation
value in a deterministic fully observable game. Across the twelve named benchmarks, not one has a
non-zero count for both "regret" and "oracle".

**Four near-neighbours that must be cited by name, with what each actually does.**

| Paper | What it really does | Why it is not this |
|---|---|---|
| Extracting Search Trees from LLM Reasoning Traces (2605.06840) | Fits search trees to four-in-a-row reasoning traces; max depth 1.00 to 3.48 plies against 4 to 6 for humans; myopic backups predict moves better than minimax backups | No solver, no optimality claim, and it never validates the heuristic it fits, so it cannot say what a shallow search cost. Write this as an observed absence: the paper does not state it lacks a solver, and an earlier draft of our survey put those words in its mouth |
| Game Reasoning Arena (2508.03368) | Declares "decision optimality, measured as the proportion of moves matching the equilibrium or optimal policy" among its metrics, on an OpenSpiel backend that could supply one | Never computes it. "Equilibrium" appears exactly once in the paper and the reported results are a taxonomy over rationale text. This is prior art that names the target and does not execute it, and the non-execution must be stated in our text or a reviewer states it for us |
| BALROG (2411.13543), Appendix F.5 and Table 16 | A five-question NetHack questionnaire with stated correct answers, graded on response correctness, conclusion correctness and in-game behaviour consistency against the NetHack wiki, tabulated for seven models | It is a structured knowledge probe, not an anecdote, and any sentence calling it anecdotal is wrong. It is still checkmarks rather than a loss: no oracle, no continuous optimality gap, no decomposition |
| Code World Models (2510.04542) | LLM writes executable game rules; transition fidelity measured (Gin Rummy 0.7816 train and 0.7455 test); and it does run an LLM as a direct move-selecting policy, with CWM-plus-planner beating Gemini 2.5 Pro in 9 of 10 games | Fidelity and play are measured on different objects and never summed into one agent's realised loss. Do not write "the LLM is a model-writer, not a player" about it, because it runs the player baseline |

**One more that the domain search will miss.** Grams et al. (2501.08925) already does exact-optimum-anchored
additive two-term regret decomposition through an intermediate privileged-oracle policy. It is not a
game benchmark, so a related-work search scoped to games will not surface it. Their exploration term is
defined as the loss in return due to missing information, which is identically zero in a fully
observable deterministic puzzle, so their exploitation gap is precisely the quantity this arm splits
further. Borrow the algebra openly and claim the axis.

**Two domain-adjacency citations that are missing and will be asked about.** AdvGameBench
(2506.12012, Yuan et al.) already benchmarks LLMs in tower defence, auto-battler and turn-based combat
with process metrics and no oracle. TowerMind (2601.05899) is a second tower-defence LLM environment,
also with no oracle. Neither scoops the method. An auto-battler paper that does not cite the existing
auto-battler benchmark will be asked why.

**A method warning worth carrying into the writing.** During the scoop check, a summarising fetch
produced an entire fabricated abstract for one paper plus three fabricated verbatim quotes that
mirrored the prompt's own phrasing and asserted exactly the scoop being probed for. Direct text
extraction of the same file showed zero occurrences of the relevant words. Every positive finding above
was re-verified by grep over downloaded text. Treat any summariser-sourced prior-art claim as unverified.

---

## 2. The procedure

One axis, run as a ladder: how much of the exactly computable true dynamics the agent is handed. The
whole thing runs offline in Python against the API and writes a Godot-schema game log plus a sidecar
file. No change to the Godot project, and no dependency on the parallel session's run.

### 2.0 Suite, zero API, and it gates everything

`oracle/generate.py`'s acceptance moves off the difficulty band and onto a congruence census computed
from the enumeration the generator already runs. Three criteria, all play-weighted over the decision
points a play actually visits, all fixed before anything is generated.

| Criterion | Threshold | What it stops | Shipped suite | Low-band suite |
|---|---|---|---|---|
| `pi_F`, flat-or-forced share | at most 0.15 | Decision points that carry no decision diluting the denominator | 3.7 percent pooled, 1.4 / 3.1 / 4.6 per puzzle | 32.4 percent pooled, 10.3 to 33.4 per puzzle |
| `pi_N`, strict-incongruent share | at least 0.20 | A suite where correct one-step evaluation always suffices, so lookahead is never required | 29.0 percent pooled, 5.6 / 0.0 / 41.0 per puzzle | 0.5 percent pooled |
| `pi_unique`, unique-argmax share of non-flat visits | at least 0.35 | The VALUES rung degenerating into "pick any of several tied maxima", which drives the selection term to zero by construction | not measured on the shipped suite | 16 percent on the ten-puzzle set it was measured on |

**Each threshold is applied per accepted puzzle, and the pooled figure is reported beside it but
decides nothing.** That is a choice and it matters, because pooled play-weighting lets one large
puzzle decide a suite: gen67 contributes 3,149,280 of the low-band suite's 3,323,880 visits, 94.7
percent, so the pooled 32.4 percent flat is essentially gen67's 33.4 percent and the other four
puzzles are nearly invisible in it, and on the shipped suite puzzle 3 contributes 68.1 percent. Under
a pooled rule a 12-puzzle suite could clear `pi_N >= 0.20` with three puzzles carrying all the
incongruence, and section 4's class-conditional dissociation would then rest on those three.

So the shipped suite passes criterion (i) both ways, meets criterion (ii) pooled at 29.0 percent but
fails it on two of its three puzzles, and has never been measured on criterion (iii) at all. It is an
anchor set rather than an accepted suite, and the three shipped puzzles, if they are carried as
anchors, are exempt from the thresholds with their own shares reported. Nothing else is exempt.

**The ten-puzzle set is not in this worktree and its three numbers could not be re-run here.** The
`pi_unique` figure of 16 percent, the 135,846-of-roughly-835,000 tied-optima count in section 4, and
the 50.7-percent-at-depth-1 flat concentration all come from a set this repository does not contain:
it holds `godot/puzzles/puzzle_suite.json` (3 puzzles), `lowtail_suite.json` (5) and
`pilot_suite.json` (5), and `oracle/artifacts/suite.json` lists no puzzles at all. Those three figures
are carried over from an earlier session on trust, not re-measured, and criterion (iii)'s 0.35
threshold is calibrated against the first of them. Everything else in this section was re-run here on
2026-09-11.

The flat and free shares above were re-run in this worktree on 2026-09-11 and reproduce exactly:
shipped 0.0 percent forced, 3.7 percent flat, 96.3 percent free, mean action gap 1.19; low-band 0.0 /
32.4 / 67.6, mean gap 1.38. Per-puzzle free share is 95.4 to 98.6 percent on the shipped suite and
66.6 to 89.7 percent on the low-band suite.

Target is 12 accepted puzzles, laid on a 2-by-2 that breaks the play-count against play-length
collinearity L10 flagged (short and few, short and many, long and few, long and many, three each).
Computed difficulty is recorded as a covariate and is never an axis, because the 2026-09-10 measurement
found it does not predict LLM performance and inverts at one adjacent pair. Play count and mean play
length are covariates for the same reason.

Two implementation facts that will otherwise cost a day each. `prep.build_board` refuses a partial
play, so `oracle/congruence.py` needs its own prep path rather than the shipped one. And while the
opponent's unit set is play-invariant, its order indices are not (two and three distinct assignments on
shipped puzzles 2 and 3), which matters because `engine._pick_acting_unit` sorts on type and order:
fix the convention as order indices taken from the lexicographically first completion, and re-run the
invariance check on every new suite. On the shipped suite 0 of 13,194 prefixes were affected; that is a
measurement of one suite, not a property of the generator.

The census is not free. It was measured at 2.4 seconds against 0.93 seconds on the shipped suite
(2.6x) and 86.4 seconds against 42.0 seconds on the low-band suite (2.1x), so acceptance costs two to
three times the enumeration pass per rejected candidate. Pre-filter candidates by play count, rejecting
anything over 60,000 plays before running the census, cap generator wall clock, and run acceptance in
parallel. If the generator cannot fill the cells inside that budget, fall back to eight accepted
puzzles plus the three shipped ones as anchors and re-derive the permutation floor that eight actually
buys before proceeding.

### 2.1 The ladder

Common to every arm: `E=0`, `R=0` (the scaffolding factorial is the other arm); no game history in any
user message; one API call per placement except at L3 and L3N; identical decoding parameters across
arms; `max_completion_tokens = 16384` everywhere, not 4096; candidate and shop serialization order
randomised per call from a logged seed.

| Rung | What the agent gets | Why it exists |
|---|---|---|
| **L0 INFER** (primary) | Trimmed role text plus response format. Mechanics withheld | The bottom of the ladder. Trimmed means the sentence telling the agent to infer mechanics from past tracethroughs is deleted, because with `E=0, R=0` it has no tracethroughs and that instruction sits directly on the headline contrast |
| **L0R ROLE-BRIDGE** (subsample) | The shipped untrimmed role text. 3 puzzles x 12 attempts x luna and terra | Measures how big the role-text artifact is and bridges to the factorial arm's I0 cells |
| **L1 RULES** | L0 plus `llm_rules.txt` verbatim | True dynamics stated in words |
| **L1P PLACEBO** | L1 with a dynamics-free block, token-matched and register-matched, restating only what the interface already shows | Separates "the rules helped" from "more text helped". It is deliberately not a false rule set: misinformation is not a placebo |
| **L1C CORRUPT, two variants** | `llm_rules.txt` replaced by a faithful rendering of a deliberately corrupted engine, chosen by enumeration from the seven named misconceptions to maximise argmax shift while staying a one-clause edit | The causal test that stated rules are operative at all. For each corruption the oracle precomputes, before any call, the mean regret a perfectly corruption-trusting agent would incur and the per-decision predicted placement shift |
| **L2 VALUES** | L1 plus an oracle block after the shops, one line per legal candidate, `<type> (row,col) -> final margin <V*>`, order randomised per call | Removes the dynamics work entirely. Whatever regret survives here is selection failure |
| **L2P VALUES-DERANGED** | Byte-length-matched to L2, same margin multiset under a seeded derangement, with the trusting-agent regret precomputed | Proves the agent is reading the printed numbers. If it lands near L1, the VALUES rung delivered nothing |
| **L3 SIMULATE** | Multi-turn. One tool, `resolve(ordered_play) -> exact final margin`, backed by `prep.build_board` plus `engine.run_battle`. Offered, never forced. Cap K = 10 calls per decision | The only construct in the field that removes simulation error while preserving search. It is a model oracle over complete plays and never a value oracle over prefixes, because handing `V*(prefix)` would leak the answer, which is what L2 does deliberately and L3 does not |
| **L3N NULL-TOOL** | The same interface, the same transcript growth, the same tool-use competence requirement, but the tool returns the count of units on the submitted play | Without it, L1 to L3 is explicable as a tool-use effect, which is the attack 2605.05716 hands a reviewer for free |

**Why the tool takes an ordered play and not a board.** A final board does not determine the final
margin here. `engine._pick_acting_unit` sorts on type and order index, and `prep.build_board(puzzle,
play)` takes its order indices from the play, so 23.4 percent of the shipped suite's distinct final
boards (294 of 1,255, re-measured 2026-09-11) carry more than one value depending on the order the
units were placed in. A board-only tool would therefore hand the agent, on about a quarter of queries,
the margin of some convention's completion rather than the margin it will actually realise, and that
error lands on `Rbar(L3,K)`, which is the upper endpoint of the headline interval. Taking the ordered
play removes it. The cost is that the agent must submit an order, which `prep.build_board` requires
anyway because it refuses a partial play.

**Grid.** 12 puzzles x 24 attempts per puzzle, arm and model, for L0, L1, L1P, L2, L2P and L3 on luna
and terra. Three arms run smaller because they answer narrower questions: L1C at 12 puzzles x 12
attempts per corruption, L3N at 6 puzzles x 12 attempts, and L0R at 3 puzzles x 12 attempts. Sol runs
L0, L1 and L2 at full size and L3 at 6 puzzles x 16 attempts, and sol is the first cut if its contested price
turns out to be the higher one. Section 7.3 prices each of these cells separately, so a cut to any one
of them reads straight off that table.

**Controls**, luna and terra, 3 puzzles x 12 attempts each: an eval-framing arm (an L1 variant stating
that placements are scored against an optimal solver, which is the observer-effect null), and a
serialization-order arm of 12 puzzles x 8 permutations x 5 repeats on all three models as single
calls, giving the agent-side positional-bias baseline against which any environment order effect has
to be judged.

### 2.2 Per-attempt mechanics

Build the board with a Python port of `BoardSerializer.serialize_snapshot` and the history-free branch
of `LlmPromptBuilder.build_user_message`. The Score Summary line adds escapes from `__meta` and the
existing prototype in `/tmp` omits them, which is a real byte-parity trap. Call the API. Parse with a
port of `LlmResponseParser.parse_place_command` (last `PLACE:` line, `rfind`). Validate against shop
membership, gold and occupancy. Apply. Advance the scripted opponent queue exactly as `prep._run_prep`
does, which is legitimate because the interleaving depends only on the agent's cost sequence. Stop when
nothing is affordable or no square is empty. Resolve with `engine.run_battle`.

**No fallback, ever.** On an unparseable or empty response, retry the identical call twice, then censor
the whole attempt and discard it, recording that it was censored. Censoring the attempt rather than the
decision is what keeps the per-attempt summation identity exactly true; dropping one decision while
keeping its attempt silently breaks `R = sum r_t`.

### 2.3 The secondary instrument: compiled belief

Fenced off from every primary statistic, costed at 25 to 33 dollars, run offline and after the fact
against boards rebuilt from a finished log, so it cannot contaminate anything. Elicit an executable
`resolve(units)` from each model across 3 models x 2 knowledge conditions x 3 contexts x 8 resamples =
144 engines, plus at most two syntax-only repair rounds that return tracebacks and never ground-truth
outcomes. Load each engine in a subprocess with no network and restricted builtins, with the timeout
applied per engine over a bounded validation set rather than per play, because per-play sandboxing is
unaffordable: 144 engines over 12 puzzles is 1.9 million battles if every accepted puzzle is the size
of the smallest shipped one, and 103.7 million if every accepted puzzle sits at the 60,000-play cap
criterion (i)'s pre-filter allows. At the measured enumeration rate and the assumed 20x slowdown for
elicited Python that is about 45 CPU-minutes at the floor and about 43 CPU-hours at the cap, which is
the number the budget has to survive. Substitute at the resolver seam to build believed value
landscapes on the 12-puzzle suite only.

It reports three things, all labelled secondary: margin-exact rate on 500 held-out enumerated plays
plus order-sensitivity agreement (an order-blind engine is detectably wrong on the 23.4 to 25.8 percent
of distinct boards whose value depends on placement order) plus the cost of the nearest named
misconception in margin points; a puzzle-level correlation between the elicited engine's value-relevant
error and the measured `D_infer` on the same puzzle; and the four certified cells computed on the L0
logs with the ambiguous share stated as assumption-dependent mass.

### 2.4 Recovery and confusion, zero API, and nothing is bought until it passes

Ground-truth agents are constructible here, so Wilson and Collins Rules 5 and 6 are treated as a
shipping requirement. Built through a resolver seam at `analysis._build_landscape`, whose enumeration
loop has exactly one `engine.run_battle` call site (line 416), rather than by monkeypatching, with the
resolver's own sha256 folded into `_code_fingerprint` so a believed landscape can never be loaded as a
true one. Two things this costs, said here rather than discovered later. The seam is an edit to
`analysis.py`: `_build_landscape` today takes only `puzzle`, and `CODE_FINGERPRINT` is a module
constant computed at import (line 214), so both have to change. And `analysis.py` has a second
`engine.run_battle` call site at line 459, inside `measure_simulation_cost`, which `analyze_puzzle`
also calls; it must either take the same seam or have its output suppressed on a believed landscape,
or a believed run reports a simulation time measured with the true engine.

The agents: corrupt-dynamics agents that plan exactly optimally under each of the seven named
misconceptions and are graded in the true engine (pure model error); truncated-search agents with
exact dynamics, resolve-now and best-of-k for k in 1, 2, 4, 8, 16, 64, 256, and depth-limited (pure
search error); epsilon-greedy under true dynamics at 0.05, 0.15 and 0.35 (pure lapse, the agent that
would masquerade as model error and the single most important row); mixtures at known ratios; and one
agent that deliberately violates the search-invariance assumption by searching worse when handed more
numbers, included so the coverage break is shown rather than assumed. Each is given a defined response
at every rung. Report interval coverage over the known truth and the 4-by-4 confusion matrix over pure
model, pure search, pure lapse and mixture.

### 2.5 What is deliberately not done

No statistic reads any self-report. No difficulty axis. No win-rate outcome anywhere, because that is
what saturated and made L10's terra and sol results untestable. No stop-on-first-solve. No scipy. No
Godot change. No claim on the parallel session's run.

---

## 3. What is logged

**(a) A Godot-schema game log** in `game_logger.gd`'s exact format, so `runlog.py`, `analysis.py` and
`outcomes.py` consume it unchanged and `runlog`'s replay verification certifies every offline attempt
on six score fields, the winner and the battle length, exactly as it certifies a Godot-produced one.
The `config` field carries the rung label; `runlog` accepts any non-empty string there.

**(b) A sidecar JSONL**, one row per API call, joined on puzzle id, config, attempt and turn number.
This needs no change to `runlog.py`, a 1,949-line module, for a simpler reason than tolerance: the
sidecar is a separate file that `runlog` never opens, and the four fields it is joined on are ones the
Godot-schema log already carries. Separately, extra keys may be added to the game log itself without
touching `runlog`, because `runlog._identity` reads only `play_mode`, `puzzle_id`, `config` and
`attempt`, each with `.get()`, and ignores everything else.

Sidecar fields: model id, rung, decision index, prefix key, the full system and user
prompt text plus a sha256 of each, the oracle block as printed, the candidate-order and shuffle seeds,
the raw response, the parsed placement, a parse-ok flag, retry index, finish reason, a truncated flag,
prompt tokens, completion tokens, reasoning tokens, cached tokens, latency, request id, and the
free-text rationale. The rationale is stored and is read by no statistic in this design.

**(c) Per tool call at L3 and L3N**: call index within the placement, the ordered play submitted, the
value returned, legality, and whether the cap was hit. Derived per placement: whether the tool was called at
all, how many times, and whether the placement finally chosen was one the agent had actually simulated.

**(d) Oracle side, recomputed offline with zero API.** Per decision: `V*(prefix)`, `V*(prefix+a)` for
every legal `a`, `r_t`, candidate count, remaining depth, action gap, the size of the argmax set and a
unique-optimum flag, the congruence class in F, C, P, N under both myopic rules, the depth of
separation, and the argmax set under each of the seven ladder engines with a value-relevance flag. Per
attempt: the ordered play, the final margin, whole-play regret, and a hard assertion that the
per-placement regrets sum to it.

**(e) Provenance.** `analysis._code_fingerprint()`, the suite path and its sha256, a sha256 of every
prompt file, the pricing table applied, the git commit, and per-arm censoring counts.

---

## 4. The statistic

### Notation

For arm `a` and attempt `y`, `analysis.score_play` gives per-placement regret
`r_t(y) = V*(p_{t-1}) - V*(p_t)` and whole-play regret `R(y) = sum_t r_t(y) = V*(empty) - value(y)`.
Write `Rbar(a)` for the puzzle-stratified mean whole-play regret in arm `a`: the mean of the
per-puzzle means, so puzzles weight equally. Computed per model. In the full-suite decomposition that
is the mean of 12; inside any arm-to-arm contrast it is the mean over the puzzles both arms ran, for
the reason given under the intervals below.

### The four primary terms

```
D_infer  = Rbar(L0)   - Rbar(L1)       rule-inference regret
D_exec   = Rbar(L1)   - Rbar(L3,K)     simulation-execution regret
D_search = Rbar(L3,K) - Rbar(L2)       search-under-exact-dynamics regret
S_sel    = Rbar(L2)                    selection regret

Rbar(L0) = D_infer + D_exec + D_search + S_sel      exactly, by cancellation
```

The three-term form `D_infer + D_sim + S_sel` with `D_sim = Rbar(L1) - Rbar(L2) = D_exec + D_search` is
reported alongside, so the result survives intact if L3 is cut for budget.

### The scale the four terms are read against

All four terms are reported both in margin points and as fractions of a span computed offline for zero
dollars: the puzzle-stratified `Rbar` of a uniform-random legal placer at one end and of the worst
legal play at the other. Without that span a small `D_infer` cannot be told apart from a ceiling
effect, and the dynamics probe in section 8 gives a concrete reason to expect one, since per-candidate
value error of 1.00 to 1.33 margin points is the same size as the modal action gap of exactly 1. If
`Rbar(L0)` and `Rbar(L1)` both sit near the uniform-random `Rbar`, the agent is close to choosing at
random among the top candidates at both rungs and the small gap between them is a ceiling, not a
finding. The span is also what gives gate G5's monotone chain a top as well as a bottom.

### The one term that needs no assumption

At the VALUES rung, per-placement regret is an algebraic identity rather than an attribution.
`V*(prefix) = max_a V*(prefix+a)` is a property of how `analysis.py` builds a prefix value rather than
its definition: `_build_landscape` takes the maximum over the complete plays passing through the
prefix, and the one-step form follows by a short induction. So it is verified rather than assumed, and
it was checked directly against the oracle at all 1,647 proper prefixes of the shipped suite with 0
violations (re-run in this worktree on 2026-09-11). At L2, then,
`r_t = (largest printed margin) - (printed margin of the chosen placement)`. `S_sel > 0` therefore
proves selection failure exists and measures it, in a condition where there is no model left to be
wrong.

### The intervals, and their width is the headline

Under two declared assumptions, (A1) the search-and-selection procedure is the same function across
rungs and only the dynamics channel moves, and (A2) supplying correct dynamics weakly improves the
subjective model and never degrades search:

```
R_search(L0) in [ S_sel , Rbar(L3,K) ]           = [ S_sel , S_sel + D_search ]
R_model(L0)  in [ Rbar(L0) - Rbar(L3,K) , Rbar(L0) - S_sel ]
                                                 = [ D_infer + D_exec , D_infer + D_exec + D_search ]
width of both = Rbar(L3,K) - S_sel = D_search
```

**What `R_model` and `R_search` are, since the names do work the algebra does not.** They are sums of
the four primary terms, and `R_model + R_search = Rbar(L0)`, so the single term the two intervals
share, `D_search`, is split between them in an unknown proportion and that is the whole of the width.
The two assignments outside the width are imposed rather than derived, and both are contestable.
`D_exec`, knowing the rules and not being able to run them forward, is charged to the model side, on
the argument that an agent that cannot execute its stated dynamics does not have them as a usable
model; a reader who calls that a procedural failure will want it on the other side. `S_sel`, being
handed the right answer and still not picking it, is charged to the search side, on the argument that
there is no model left to be wrong at L2; a reader who calls it neither model nor search is also
right, which is why `S_sel` is reported on its own as well. Where the assignment is what a reader
would dispute, the four terms are the result and the two-way names are the summary.

**The lower endpoint's real dependency, in the same breath as the endpoint.** `R_search(L0) >= S_sel`
is not established by "L2 removes all dynamics work, so residual regret there is pure selection". That
sentence says what `S_sel` measures; it does not say that the agent's non-model regret at L0 is at
least that large. The step needs A1, and A1 is least credible at exactly this pair: L2's task is to
pick the largest of about 18 printed integers, L0's is to choose among imagined outcomes, and those
are the two rungs whose cognitive demand differs most. If the agent selects more sloppily when there
is nothing to compute, `S_sel` exceeds the L0 selection channel and the interval does not contain the
truth at all. The A1 check is the per-arm reasoning-token distribution, and this is the pair it is
most likely to flag. Fixed in advance, with the threshold chosen rather than derived: if the L0-to-L2
shift in median reasoning tokens exceeds a factor of two, the lower endpoint is reported as an
A1-conditional figure and the interval is quoted as one-sided from `Rbar(L3,K)` down.

The upper endpoint holds because at L3 exact dynamics are available on demand, so residual regret
there bounds search from above; it is an upper bound and not a point precisely because it also
contains tool non-use and tool-use incompetence. Without L3 the width is `D_sim = D_exec + D_search`;
L3 narrows it to exactly `D_search`, a reduction of `D_exec`, and that reduction is itself reported.

**Every contrast is computed on the puzzles both arms ran.** The arms are not all the same size: sol
runs L3 on 6 puzzles against 12 for its single-turn arms, and L3N runs on 6 puzzles against 12 for L3
itself. A difference of means taken over different puzzle sets can take either sign for reasons of
suite composition alone. So each contrast is computed on the intersection of the two arms' puzzles,
the intersection is stated per contrast, and `Rbar` in a contrast means the mean of the per-puzzle
means over that intersection rather than over all 12. G5's chain and G7's comparison are restated on
the same intersections. The four-term sum still telescopes to `Rbar(L0)` on the full 12 because
`Rbar(L3)` cancels, and that full-suite version is what is reported as the headline decomposition.

### Non-negativity and summation, stated exactly

- `r_t >= 0` always, and the terms telescope exactly to whole-play regret, because a longer prefix
  maximises over a subset of a shorter prefix's completions. `analysis._check_decomposition` already
  verifies both over every play of every puzzle, and the driver re-asserts the sum per attempt as a
  computed integer rather than as a claim.
- `S_sel >= 0` always: it is a mean of non-negative regrets.
- `D_infer`, `D_exec` and `D_search` are differences of arm means and are **not** guaranteed
  non-negative. No clamping, fixed in advance: each is reported signed, and a sign violation is a
  finding rather than a nuisance. A2 predicts `Rbar(L0) >= Rbar(L1) >= Rbar(L3) >= Rbar(L2) >= 0`,
  falsifiable at every link. Hamrick et al. (2011.04021) measured median reward falling 4.7 points
  with more search under a learned model, and 2605.05716 finds scaffold components subadditive, so a
  violation is a live possibility that would refute A2 rather than break the arithmetic.
- Because censoring drops whole attempts, `R = sum_t r_t` holds exactly on every retained attempt.

### Edge case: flat decision points

Every legal candidate has the same value, so `r_t = 0` by construction and no mistake is possible.
Measured 1.4 to 4.6 percent by puzzle on the shipped suite and 10.3 to 33.4 percent on the low-band
suite, which criterion (i) rejects (re-measured 2026-09-11). An accepted puzzle is capped at 15
percent, so the 33.4 percent end is what the criterion exists to exclude and not a rate the design
expects to live with. Whole-play regret is the primary outcome and needs no denominator convention,
so the ladder contrasts are untouched by flatness. Every per-decision rate is regret-mass-weighted with flat points excluded, and is censused
separately by remaining depth, because flatness concentrates at depth 1 (50.7 percent at depth 1 on
the ten-puzzle set where it was measured) and an unconditioned flat rate would confound the depth
regression. Suite criterion (i) caps the flat share at 0.15 so this exclusion cannot eat the sample.

### Edge case: tied optima at the VALUES rung

On the ten-puzzle set where it was measured, only about 16 percent of non-flat decisions had a unique
argmax (135,846 of roughly 835,000). At that rate "maximise the printed list" collapses into "pick any
of several tied maxima" and `r_t = 0` for any of them, driving `S_sel` to zero for reasons that have
nothing to do with the agent. Two responses, both fixed in advance: suite criterion (iii) requires the
unique-argmax share to be at least 0.35, and `S_sel` is reported both pooled and restricted to
unique-optimum decisions, the restricted version being the one that can actually detect selection
failure.

### Edge case: fallback placements

There are none. No random placement is ever substituted into any log. Two retries, then the attempt is
censored. Censoring is gated in advance on both the absolute rate (above 2 percent in any arm) and the
differential rate (more than 2 points between arms), because the VALUES arms give the agent less to
think about and so plausibly truncate at a different rate. One of 29 measured calls already returned
4,096 reasoning tokens and no content. The cap is 16384 rather than 4096 precisely so this gate is not
tripped by a decoding parameter chosen for a parity nobody is testing.

### Secondary statistic: the class-conditional dissociation

Stratify every per-placement regret by the oracle-certified congruence class in F, C, P, N and report
each ladder contrast within class. Prediction fixed in advance: `D_infer` concentrates in class C,
where a correct one-step evaluation already suffices so a wrong rule is what hurts, while
`D_exec + D_search` concentrate in class N, where lookahead is strictly required. This is an
interaction between a randomised manipulation and an enumerated certificate, so it needs no normative
assumption: no level is ever charged to a named cause, only a contrast conditioned on a certificate
computed from the oracle. Robustness across both myopic rules is mandatory and reported, because the
strict-incongruent share varied 5.6 / 0.0 / 41.0 across just the three shipped puzzles and the
stratifier's own stability has to be shown rather than assumed.

### Secondary statistic: differential scaling in remaining depth

On free decisions, fit `r_t = alpha_q + beta*n_t + gamma*d_t` per arm by hand-rolled OLS with puzzle
fixed effects, inference by attempt-clustered bootstrap. Prediction: `gamma` near zero at L2, because
maximising a printed list does not get harder with remaining depth, only with list length, while
`gamma > 0` at L1 from rollout compounding. `gamma_L1` close to `gamma_L2` would say the simulation gap
is a list-length artifact. At remaining depth 1 the L1-minus-L2 gap isolates single-battle simulation
error with zero lookahead, which is the floor of the compounding curve.

### Manipulation checks, each with a precomputed predicted value

- `Rbar(L1P) - Rbar(L1)`: true rules against a token-matched dynamics-free block. A large positive
  value while `D_infer` is large means the L0-to-L1 gain was content: the placebo text did not buy
  what the rules bought. Near zero means the placebo bought the same thing, so the gain was length or
  compute, which is gate G4 failing.
- L2P: the oracle precomputes the regret a perfectly number-trusting agent would incur under the
  derangement. Landing near that value means the agent reads and trusts the printed numbers; landing
  near `Rbar(L1)` voids the rung.
- L1C: for each corruption, the predicted regret and the per-decision predicted placement shift are
  computed before the run, so the arm has a predicted value and not merely a predicted direction.
  Report the noise-normalised switch rate toward the corrupted argmax (normalisation is essential
  because candidate sets fall to 3 at the last placement) against the realised regret increase.
- A1 check: per-arm distributions of reasoning tokens. A large shift from L0 to L1 is direct evidence
  that supplying rules changed how much search happened, and it is reported as such rather than
  absorbed.

### Normalizer discipline

L10 measured the same arm's rank correlation moving from -0.410 to -1.000 to -0.821 purely by changing
the regret normalizer. Because every headline quantity here is a within-puzzle paired contrast, its
sign is normalizer-invariant and only the pooled magnitude moves. All three normalizers are fixed in
advance and all three are reported: raw margin points, regret divided by the puzzle's attainable value
span, and regret divided by `V*(empty)`. No conclusion may rest on one of them.

### Inference, standard library only

`outcomes.py` as it stands. Exact permutation over all pairings for per-puzzle paired arm contrasts.
At n = 12 there are 2^12 = 4,096 sign assignments, so the floor is a one-sided p of 1/4,096 and a
two-sided p of 1/2,048; at n = 15, which is what option 1 in section 9 recommends, the one-sided floor
is 1/32,768. The 2,000-resample attempt-level bootstrap for confidence
intervals on all four terms and on both interval endpoints. Wilson intervals for parse rate, censoring
rate, tool usage rate and simulated-then-chosen rate. Per-puzzle contrasts reported alongside every
pooled mean.

### Reporting form

Following Skalse and Abate (2411.15951), publish the ambiguity set plus a tolerance argument: name the
downstream decision the split is meant to inform, which is "give this agent a simulator, or give it
more deliberation", and show whether every member of the interval implies the same answer. Where it
does not, say so in those words.

---

## 5. What is identified and what is not

### Identified with no normative assumption at all

1. **The four ladder contrasts.** They are average treatment effects on exact oracle regret between
   randomly assigned, within-puzzle-crossed conditions with a token-matched placebo beside each
   informative rung. They are identified by the design rather than by a model of the agent.
   Armstrong and Mindermann's Theorem 1 does not touch them, because they are differences in an
   observable outcome across conditions and not a factorization of a policy.
2. **`S_sel`, additionally as an algebraic identity**, for the reason given in section 4.
3. **The class-conditional pattern.** An interaction between a randomised manipulation and an
   enumerated certificate. No level is ever charged to a named cause.
4. **The companion quantities**: the causal effect of dynamics access on regret; the tool usage rate
   at L3 and the rate at which the chosen placement was one the agent had actually simulated (an agent
   handed an exact simulator that declines to call it is itself a finding); and the residual floors
   `Rbar(L3)` and `Rbar(L2)`, which upper-bound the regret that neither supplying dynamics nor
   supplying exact simulation can remove.

### Not identified, and this belongs in the abstract rather than the threats section

The latent pair of subjective dynamics and search procedure is not recoverable from placements.
Armstrong and Mindermann's Theorem 1 constructs, for any hypothesised dynamics model including the true
one and its worst distortion, a search procedure that reproduces the observed play exactly.
Propositions 7, 8 and 10 close the simplicity escape under Kolmogorov, Kt and KT complexity. Their
abstract closes the escape a reader reaches for first: the ambiguity cannot be resolved by observing
the agent's policy in enough environments, so more puzzles is necessary and not sufficient. Shah et al.
(1906.09624) prove constructively that assuming the planner is constant across environments still falls
prey to the impossibility result.

Shah et al. also supply the remedy, and a reviewer who knows the paper will ask why it was declined, so
here is the answer rather than a silence. They add one of two tie-breakers: Assumption 2a, that the
demonstrator is close to optimal, or Assumption 2b, that the reward is known on a set of calibration
tasks from which the planner is pinned first and then frozen. Assumption 2b is the one that fits this
environment's shape, and it is not constructible here. Its calibration tasks would be decisions with no
search demand, which in this game means forced or flat decision points, and at exactly those points
`r_t = 0` by construction for every candidate. A zero-search-demand decision carries no regret signal,
so there is nothing on it to pin a dynamics parameter with. Criterion (i) then caps such points at 0.15
for an unrelated reason, which shrinks the channel further. What the design carries instead are two
weakened substitutes, both named as substitutes: the class-conditional dissociation in section 4, which
conditions on an enumerated certificate rather than pinning a parameter, and the fenced elicitation in
section 2.3, which is a calibration channel with no claim that what it elicits is what the agent
planned with. Assumption 2a transfers no better: regularizing a fitted search procedure toward the
exact optimizer assumes the answer to the question being asked. The exact oracle rescues none of this: `V*` pins the true dynamics
and hence exact per-placement regret, but regret is one scalar per placement and both degenerate
explanations reproduce it.

Also not identified: which rule the agent believes, beyond its value-equivalence class on the visited
decision points (Grimm et al. 2011.03506, where the class shrinks monotonically as the policy set
grows, which is an independent argument for the cross-puzzle design and a hard limit on what one puzzle
can say). And not identified: the agent's search procedure. We report what its failure cost, never a
mechanism.

### So the answer is a set, and its width is measured rather than argued

If the width `Rbar(L3,K) - S_sel` is small, the set nearly collapses and a near-point may be quoted
with no elicitation and no faithfulness assumption. If it is large, the honest statement is the
interval, and the honest headline is that the split is not resolvable to better than that many margin
points on this suite. Either outcome is a result, which is the property the elicitation-first
alternative does not have.

### The two declared normative assumptions, imposed rather than deduced

- **(A1) Search invariance across rungs.** Partly testable: per-arm reasoning-token distributions are
  logged, a large shift is direct evidence of violation, and a synthetic A1-violating agent is included
  in the recovery study specifically to exhibit the coverage break.
- **(A2) Monotone information.** Falsifiable at every link of `Rbar(L0) >= Rbar(L1) >= Rbar(L3) >= Rbar(L2) >= 0`.

### Why the L3 rung is the identification step rather than an extra

The width exists because the VALUES rung removes the model and the search together. In this game all
value is terminal, the battle resolves only from a complete board, so supplying any prefix value is
supplying its optimal completion, and "give the model, keep the search" is not constructible at the
prefix level. It is constructible at the leaf level, and that is L3: the agent has zero simulation
error but must still choose which completions to query under a cap of K. The game's branching allows
524,880 completions at the ceiling (18 x 15 x 12 x 9 x 6 x 3), but no accepted puzzle can reach that,
because section 2.0's pre-filter rejects anything over 60,000 plays; the three shipped puzzles run
3,240, 1,080 and 7,230. The argument does not need the inflated figure, and 60,000 under a cap of 10
is already the whole of it. Sweeping K
traces search error against search budget with the model held exact.

### We measure how hard non-identifiability bites, rather than only citing it

Interval coverage over known truth and a 4-by-4 confusion matrix, including the epsilon-greedy row,
which matters most because lapse noise is what would masquerade as model error. Off-diagonal mass is
the measured bite of the No Free Lunch result for this estimator on this suite, and it is the strongest
claim the theorem leaves available. If the matrix is not near-diagonal, the paper reports that the
result bit, for zero dollars, before a token is spent.

### What the secondary elicitation adds, and what it cannot

It supplies, up to a value-equivalence class, the content of the error in named rule terms with costs
in margin points, plus a puzzle-level convergent-validity correlation against the interventionally
measured `D_infer`. It is fenced off from every primary statistic, so its failure costs a secondary
claim and nothing else. It cannot license any claim that the elicited engine is what the agent planned
with: grading a report against an oracle proves the report accurate, not operative. The published form
of that objection is Chen, Zhong et al.'s +0.012 Pearson correlation between explanation plausibility
and counterfactual simulatability precision.

---

## 6. The pilot and its gates

Five stages. Stages 0 and 1 cost nothing and must both pass before a single token is bought. Summing
the three live stages below gives 1,823 calls and $13.39 at the lower sol price, $16.44 at the
higher one, one afternoon. The cost table in section 7.3 carries the pilot at a padded $25 to cover
retries and a partial re-run, and the padding is the difference.

| Stage | What it is | Cost | Blocking condition |
|---|---|---|---|
| 0 | Suite feasibility. Re-aim `generate.py` acceptance onto the census, try to produce 12 puzzles meeting all three criteria across the 2-by-2, and run the opponent-order-index invariance check on every accepted puzzle | zero API | If the generator cannot fill the cells inside its wall-clock budget, fall back to 8 plus the 3 shipped anchors and re-derive the permutation floor before proceeding. This is a real gate, and neither existing suite clears it. Per puzzle, the shipped suite passes criterion (i) at 1.4, 3.1 and 4.6 percent flat, fails criterion (ii) on two of its three puzzles (strict-incongruent shares 5.6, 0.0 and 41.0 percent against a required 0.20), and has never been measured on criterion (iii) at all. The one existing generated suite misses criterion (ii) by a factor of 40, at 0.5 percent pooled against 0.20, and misses criterion (i) at 32.4 percent against a cap of 0.15. Criterion (iii) is the one with no path in sight: it was 16 percent on the ten-puzzle set where it was last measured, against a required 35 percent, and it is the criterion the interval's lower endpoint depends on, because a suite that fails it drives `S_sel` to zero for reasons that have nothing to do with the agent. If the generator cannot reach 0.35 on any candidate, the fallback is fixed in advance: report `S_sel` only on the restricted unique-optimum subset, state the size of that subset, and if the subset is too small to estimate, report the interval with a lower endpoint of zero and say so in the abstract rather than in a threats paragraph |
| 1a | Arithmetic. On synthetic plays, `Rbar(L0) - (D_infer + D_exec + D_search + S_sel) = 0` as an integer on every cell, and `r_t` sums to whole-play regret on every play | zero API | A failure here is a bug, not a finding |
| 1b | Recovery and confusion. Run the full estimator on the synthetic ladder and ship the coverage rate and the 4-by-4 matrix | zero API | Proceed only if pure-model and pure-search generators land on the diagonal at least 70 percent of the time at mid-ladder settings **and** the epsilon-greedy agent is not classified as pure-model more often than chance. If lapse is confused with a misconception, the design is measuring choice noise and should be stopped here |
| 1c | Driver fidelity. Byte equality against `LlmPromptBuilder.build_user_message` on 3 puzzles x 3 prefixes including the Score Summary line; parser agreement with `LlmResponseParser` on the Godot fixtures; `runlog.load_run` plus `score_run` accepting 20 driver-emitted attempts with the replay check green on all six score fields, the winner and the battle length | zero API | Any mismatch blocks the run. Results that do not reproduce the Godot prompt are not comparable with the scaffolding arm |
| 2 | Choice entropy. 3 models x 1 fixed prefix x 20 identical repeats, measuring the empirical distribution over the roughly 18 candidates | 60 calls, $0.81 at the lower sol price and $1.01 at the higher | If the modal placement takes more than about 90 percent of draws on all three models, attempt-to-attempt variation is near zero, the attempt-level bootstrap is measuring almost nothing, and the grid must be re-sized toward more puzzles and fewer attempts before it is bought |
| 3 | Smallest live ladder. 3 accepted puzzles x 7 arms x 4 attempts on luna, both tool arms included so G7 has something to read | 979 calls (5 single-turn arms at 326, plus L3 and L3N at 653), $1.02 | Feeds gates G1 to G7 |
| 4 | Truncation and tool check on the expensive models. 3 puzzles x 4 arms x 3 attempts on terra and on sol, three arms single-turn and one the tool arm the stage is named for | 783 calls, $11.56 at the lower sol price and $14.41 at the higher | Feeds G1 and G6 |

### The seven live gates

| Gate | Threshold | What happens if it fails |
|---|---|---|
| **G1 Censoring** | Parse rate at least 95 percent, censoring under 2 percent in every arm, and under 2 points differential between arms, at `max_completion_tokens = 16384` with finish reason logged | Raise the cap further and re-run. A differential failure invalidates the affected contrast. This gate is why the cap is 16384: the only measurement in hand is 1 of 29 calls (3.4 percent) hitting exactly 4,096 reasoning tokens with no content, which is already above a 2 percent gate |
| **G2 Manipulation check** (the real abort condition) | `Rbar(L2P)` materially worse than `Rbar(L2)` and near the precomputed trusting-agent value | Stop and redesign the oracle block before committing the grid. If L2P lands near `Rbar(L1)`, the agent is not reading the printed margins, `S_sel` is meaningless and the VALUES rung delivers nothing |
| **G3 Selection floor** | `S_sel` measurably greater than zero on at least one puzzle, computed on unique-optimum decisions | Not fatal, but it changes the paper: the agent maximises a printed list perfectly, the lower search endpoint is trivially zero, and L3 becomes the only rung that can say anything about search |
| **G4 Placebo separation** | `Rbar(L1P)` no better than `Rbar(L0)` | The L0-to-L1 gain was length or compute, and that has to be known before the grid is costed rather than after |
| **G5 Monotonicity** | Point estimates satisfy `Rbar(L0) >= Rbar(L1) >= Rbar(L3) >= Rbar(L2) >= 0` | A violation refutes A2 and is publishable, but it must be seen at pilot scale because it changes what the paper claims and whether the intervals are reported at all |
| **G6 Tool reality** | At L3, usage rate above 0, mean round-trips per placement at most 6, cap-hit rate recorded | If usage is 0 the offered rung carries no information and only a forced variant survives. The cost model is priced at 5 calls per placement, not 6, so it is already short anywhere above 5: a measured mean of 6 re-prices the five tool lines from $141.64 to $172.00 at the lower sol price and from $156.47 to $189.96 at the higher, about $31 to $33 on an arm of $496 to $570. That is survivable against the $1,200 reassess point, which is why the gate sits at 6 rather than at 5, but a measured multiplier between 5 and 6 means the L3 lines in section 7.3 must be re-priced at the measured value before the grid is bought, and above 6 K must be tightened |
| **G7 Tool-use separation** | `Rbar(L3)` materially better than `Rbar(L3N)` | The L1-to-L3 effect is tool-use competence rather than dynamics access. L3 is then reported as a tool-use effect and the interval-narrowing claim is withdrawn |

### The decision rule

Stages 0 to 2 all pass and G1 to G5 pass: buy the full grid, luna first, then terra, then sol,
checking spend against the $1,200 gate after each model. G2 fails: do not buy, redesign the oracle
block. G6 or G7 fails: buy the single-turn grid only, report the three-term ladder with width `D_sim`,
and state plainly that the interval could not be narrowed. Stage 1b fails: stop, and report the
confusion matrix as the result. That is a measured negative about the identifiability of this
factorization, which is the outcome to discover in week one for zero dollars rather than in week three
for five hundred.

---

## 7. Cost

### 7.1 The inputs, and which are measured and which are assumed

**Measured, 2026-09-11, from 29 successful direct API calls outside the game that rebuilt the exact
`I1_E0_R0` prompt from the repo's own prompt files (one further call returned HTTP 500):**

| Quantity | luna | terra | sol |
|---|---|---|---|
| Input tokens per call | 969, range 967 to 973 | same | same |
| Output tokens, mean | 1,011 | 1,243 | 889 |
| Output tokens, median | 567 | 798 | 726 |
| Reasoning share of output | about 94 percent | about 94 percent | about 94 percent |
| Cached input tokens | 0 on every call | 0 | 0 |

**Prices per million tokens, input / output.** Luna $0.20 / $1.20 and terra $2.00 / $12.00, both
corroborated by a third-party tracker that is current on the 30 July 2026 price cut.

**Sol's price is contested and was not resolved.** The project brief records $4.00 / $20.00 read from
OpenAI's own pricing page on 2026-09-09 and says trackers quoting $5 / $30 are stale. The vendor page
could not be re-read from this machine: openai.com returns HTTP 403 both to the fetch tool and to curl.
The trackers that are current on luna and terra still say sol is $5.00 / $30.00 and that sol was
unchanged in the July cut. Every figure below is given at both prices. Nothing resolves this except
opening the vendor page from a machine it will answer.

**Assumptions, each flagged where it is used.**

- Average input per call across the ladder is taken as **1,070 tokens**, and here is what the 969 it
  is built from actually is. The measured prompt is `I1_E0_R0`, and its system message is
  `llm_role.txt` plus `llm_rules.txt` plus `llm_response_format.txt`, so the rules block is already
  inside the 969. That makes 969 the L1 prompt, not the L0 one. Rebuilding the ladder from it: L0 sits
  about 301 tokens below at roughly 668, that being `llm_rules.txt` at 1,206 bytes and four characters
  per token; L1, L1P and L1C sit at the measured 969; L2 and L2P sit 150 to 250 above it. The five-arm
  luna and terra average is then about 989 and the three-arm sol average about 935. **1,070 is used
  throughout as one conservative figure, roughly 8 percent above the rebuilt average**, rather than
  per-arm inputs, and the ladder lines are overstated by about that much. The 150-to-250 oracle block
  is the one estimate here that is an assumption about an arm that does not exist yet.
- **No prompt caching relief is assumed anywhere.** Cached tokens were 0 on all 29 calls, and the
  prompt is 969 tokens against a documented 1,024-token minimum for automatic caching on GPT-5.6 and
  later, so caching cannot fire as the prompt stands. The VALUES and tool arms may cross that
  threshold, which would create a per-arm cost asymmetry and not a behaviour difference, so per-arm
  cost is reported separately and never extrapolated from one arm. Padding the prompt to chase caching
  is forbidden, because it changes the stimulus.
- **5.44 placements per attempt**, the brief's measured suite mean. Used deliberately rather than the
  4.16 of the ten-puzzle set or the 3.49 the shipped suite measures in this worktree (40,260 visits
  over 11,550 plays), because the census-accepted suite does not exist yet and 5.44 is the conservative
  direction. The size of that conservatism is 31 percent against the ten-puzzle set and 56 percent
  against the shipped one, so every call count below is a ceiling rather than a forecast. The pilot
  measures the accepted suite's own mean and the budget is re-derived from it.
- L3 round-trips: 5 calls per placement (one initial plus four round-trips), input growing by about
  180 tokens for the first round-trip and 100 for each one after, to
  969 + 1,150 + 1,250 + 1,350 + 1,450 = 6,169 input tokens per placement, and output about 2.5 times a
  single call. Gate G6 measures this, the budget is priced at 5 and not at the gate's 6, and G6's row
  in section 6 carries what a measured 6 would cost.
- **87 elicitation calls per model.** Section 2.3 specifies 48 engines per model (2 knowledge
  conditions x 3 contexts x 8 resamples) and at most two syntax-only repair rounds, so the true count
  is between 48 and 144. 87 is 48 engines plus an assumed 39 repair calls, a repair rate of 0.81 per
  engine, which is a guess and not a measurement. At the ceiling of 144 the three elicitation lines
  come to $1.50 luna, $14.98 terra and $25.34 or $37.44 sol, which is $16.55 to $21.34 more than the
  table carries.

### 7.2 Per-call rates

```
luna      1,070 x 0.20/1e6  +  1,011 x 1.20/1e6  =  0.000214 + 0.001213  =  $0.001427
terra     1,070 x 2.00/1e6  +  1,243 x 12.00/1e6 =  0.002140 + 0.014916  =  $0.017056
sol low   1,070 x 4.00/1e6  +    889 x 20.00/1e6 =  0.004280 + 0.017780  =  $0.022060
sol high  1,070 x 5.00/1e6  +    889 x 30.00/1e6 =  0.005350 + 0.026670  =  $0.032020
```

The L3 and L3N rows of the table below are priced per placement and not per call, because a tool
placement is 5 calls that re-send a growing transcript. They cannot be reproduced by applying the
rates above to their call counts, so the rate they do use is printed here, at 6,169 input tokens and
2.5 times a single call's output per placement:

```
luna      6,169 x 0.20/1e6  +  2,527.5 x 1.20/1e6 =  0.001234 + 0.003033  =  $0.004267 per placement
terra     6,169 x 2.00/1e6  +  3,107.5 x 12.00/1e6 = 0.012338 + 0.037290  =  $0.049628 per placement
sol low   6,169 x 4.00/1e6  +  2,222.5 x 20.00/1e6 = 0.024676 + 0.044450  =  $0.069126 per placement
sol high  6,169 x 5.00/1e6  +  2,222.5 x 30.00/1e6 = 0.030845 + 0.066675  =  $0.097520 per placement
```

### 7.3 The decomposition arm, item by item

Every line below was recomputed from its own multiplication rather than copied. Placement and call
counts are rounded for display while the arithmetic is carried unrounded, so a few parentheticals do
not multiply out to the integer beside them: 1,566.72 placements x 5 is 7,833.6 shown as 7,834,
522.24 x 5 is 2,611.2 shown as 2,611, and 391.68 x 5 is 1,958.4 shown as 1,958. The same applies to
one dollar figure: the sol single-turn line is 4,700.16 calls at $0.022060, which is $103.686 and
displays as $103.69, where the rounded 4,700 would give $103.68. The column of displayed integers sums
to 50,005; the unrounded figures sum to the 50,003 in the total row.

| Item | Calls | Low (sol $4/$20) | High (sol $5/$30) |
|---|---:|---:|---:|
| Single-turn L0, L1, L1P, L2, L2P, luna (5 x 12 x 24 x 5.44) | 7,834 | $11.18 | $11.18 |
| Single-turn L0, L1, L1P, L2, L2P, terra | 7,834 | $133.61 | $133.61 |
| Single-turn L0, L1, L2, sol (3 x 12 x 24 x 5.44) | 4,700 | $103.69 | $150.50 |
| L3 tool, luna (1,567 placements x 5) | 7,834 | $6.68 | $6.68 |
| L3 tool, terra | 7,834 | $77.75 | $77.75 |
| L3 tool, sol reduced (522 placements x 5) | 2,611 | $36.10 | $50.93 |
| L3N null-tool, luna (392 placements x 5) | 1,958 | $1.67 | $1.67 |
| L3N null-tool, terra | 1,958 | $19.44 | $19.44 |
| L1C corrupt x2, luna (2 x 12 x 12 x 5.44) | 1,567 | $2.24 | $2.24 |
| L1C corrupt x2, terra | 1,567 | $26.72 | $26.72 |
| Controls, luna (role-bridge 196 + eval-framing 196 + serialization 480) | 872 | $1.24 | $1.24 |
| Controls, terra | 872 | $14.87 | $14.87 |
| Controls, sol (serialization only, 12 x 8 x 5) | 480 | $10.59 | $15.37 |
| Compiled-belief elicitation, luna (48 engines plus 39 assumed repair calls, at 4,000 in / 8,000 out) | 87 | $0.90 | $0.90 |
| Compiled-belief elicitation, terra | 87 | $9.05 | $9.05 |
| Compiled-belief elicitation, sol | 87 | $15.31 | $22.62 |
| Pilot, all stages (stages 2, 3 and 4 sum to $13.39 low and $16.44 high; carried padded for retries) | 1,823 | $25.00 | $25.00 |
| **Total** | **50,003** | **$496.05** | **$569.78** |
| **With 35 percent contingency on the output right tail** | | **$669.67** | **$769.20** |

The contingency is 35 percent and it exists for one specific reason: the measured output range already
reaches 4,096, and raising the cap to 16,384 removes the ceiling that was truncating it, so the right
tail of the output distribution has not been observed.

**Three corrections against the design's own summary, recorded because the numbers must reproduce.**
The design summary gives $485.2 low and $559.7 high. Its itemised entries actually sum to $558.8 on the
high side, so $559.7 was a rounding slip. Separately, its controls line reads $16 low and $19 high,
which is the cost of the luna and terra controls only and omits sol's 480 serialization calls, even
though the same summary counts those 1,440 serialization calls in its call total; recomputed, controls
are $26.70 low and $31.48 high. And its sol elicitation high figure reads $24.4 where
`87 x (4,000 x 5/1e6 + 8,000 x 30/1e6)` gives $22.62. The table above is the recomputation.

**Against the gates.** At $670 to $769 the decomposition arm clears the $1,200 abort-and-reassess point
on a single pass and leaves $2,231 to $2,330 of the $3,000 ceiling for the other arm. It does not clear
it twice: a full re-run puts cumulative spend at $1,339 to $1,538, which is past the reassess point at
either price. A second full pass is therefore a reassess-then-decide, not a free retry. Worse, the
$1,200 gate is checked after each model, and on a re-run the cumulative spend is still under it after
the second terra ($1,082 low, $1,181 high) and over it only after the second sol ($1,306 and $1,505),
so the gate would not stop a re-run until the re-run was finished. If a re-run is wanted, decide it
before starting it rather than expecting the gate to catch it.

**What drives the bill.** Reasoning tokens are 94 percent of output, so output dominates input: at the
1,070-token input used in every line above, 5.7 to 1 on luna and 7.0 to 1 on terra. (At the measured
969 the same ratios read 6.3 and 7.7, which is where an earlier "6 to 1 and 8 to 1" came from; both
figures below use 1,070, the one the priced lines use.) Input is 15.0 percent of a luna call, 12.5
percent of a terra call and 16.7 to 19.4 percent of a sol call, so even a 90 percent discount on
cached input would cap the saving at 11 to 17 percent by model, and only on the repeated part of the
prompt. That is more than the 10 percent an earlier draft claimed and still small, and it is moot
while caching cannot fire at all.

A tool placement costs about 3 times a single-turn placement (2.91x on terra to 3.13x on sol at the
lower price), because every round-trip re-sends the transcript and re-pays the reasoning, so about two
thirds of the spend inside a tool cell is the four round-trips after the first call. Across the whole
arm the two tool rungs are 21 to 35 percent of each model's bill: $8.35 of luna's $23.91, $97.19 of
terra's $281.44, and $36.10 of sol's $165.69 at the lower price.

Sol is 33 percent of the arm at $4/$20 and 42 percent at $5/$30, so cutting it saves $166 or $239
depending on which price is real. It is scheduled as the first cut for that reason, with the design
degrading to two models, and the size of the saving turns on the price question that could not be
resolved from this machine.

**Offline compute, because it is not free either.** Enumeration measured at 74 to 81 microseconds per
play: 11,550 plays in 0.93 seconds is 80.5 microseconds, 569,580 in 42.0 seconds is 73.7, and the two
measurements differ by 9 percent. The congruence census costs 2.1 to 2.6 times that. The one large
item is 144 elicited engines across 12 puzzles at an assumed 20x slowdown for unoptimised elicited
Python. It is embarrassingly parallel, and its bound is the 60,000-play pre-filter: at that cap it is
103.7 million battles, about 43 CPU-hours, against about 45 CPU-minutes if every accepted puzzle comes
in at the size of the smallest shipped one. The 43 hours is the number to plan against.

### 7.4 The ablation arm at the measured rates

The brief sizes the ablation arm at 1,400 to 4,800 multi-turn runs with up to 30 attempts each, which
reproduces as 8 configs x 15 to 30 puzzles x 3 to 4 models x 3 to 5 seeds (8 x 15 x 4 x 3 = 1,440 at
the low end, 8 x 30 x 4 x 5 = 4,800 at the high end). A run is one config-puzzle-model-seed cell,
played for some number of attempts, and each attempt costs 5.44 placement calls.

**Four assumptions, all flagged.** (1) Placements per attempt is 5.44, the same measured suite mean.
(2) Every attempt is played. The L10 pilot used `--all-attempts`, and with stop-on-first-solve the
realised mean is lower and has not been measured. (3) Input per call is taken as 1,070, the same as the
ladder, which is slightly generous across the factorial: the E1 half adds about 455 tokens and the I0
half removes about 301 (both estimated from the prompt files at four characters per token, not measured
against the tokenizer), and since each applies to 4 of the 8 configs the average lands near 1,046. (4) Output per call is the
measured per-model mean for the `I1_E0_R0` prompt. The R1 half of the factorial adds a separate
reflection call per attempt, which averages to about 0.5 extra calls per attempt across the eight
configs, about 9 percent; the "with reflection" column carries that and the plain column is a floor.

| Runs | Attempts | Placement calls | Model mix | Placement calls only | With reflection turns |
|---:|---:|---:|---|---:|---:|
| 1,400 | 10 | 76,160 | luna + terra + sol at $4/$20 | $1,029 | $1,124 |
| 1,400 | 10 | 76,160 | luna + terra + sol at $5/$30 | $1,282 | $1,400 |
| 1,400 | 10 | 76,160 | luna + terra only | $704 | $769 |
| 1,400 | 10 | 76,160 | luna only (absolute floor) | $109 | $119 |
| 1,400 | 30 | 228,480 | luna + terra + sol at $4/$20 | $3,088 | $3,372 |
| 1,400 | 30 | 228,480 | luna + terra + sol at $5/$30 | $3,846 | $4,200 |
| 1,400 | 30 | 228,480 | luna + terra only | $2,111 | $2,306 |
| 1,400 | 30 | 228,480 | luna only | $326 | $356 |
| 4,800 | 10 | 261,120 | luna + terra + sol at $4/$20 | $3,529 | $3,854 |
| 4,800 | 10 | 261,120 | luna + terra + sol at $5/$30 | $4,396 | $4,800 |
| 4,800 | 10 | 261,120 | luna + terra only | $2,413 | $2,635 |
| 4,800 | 10 | 261,120 | luna only | $373 | $407 |
| 4,800 | 30 | 783,360 | luna + terra + sol at $4/$20 | $10,587 | $11,561 |
| 4,800 | 30 | 783,360 | luna + terra + sol at $5/$30 | $13,187 | $14,401 |
| 4,800 | 30 | 783,360 | luna + terra only | $7,239 | $7,905 |
| 4,800 | 30 | 783,360 | luna only | $1,118 | $1,221 |

The three-model mix is an even split across luna, terra and sol. The brief commits to three to four
models; a fourth model's rate is unknown, so no four-model figure is given.

**The model-mix rows hold the run count fixed, which is a design choice and not the only one.** The
brief's run count already contains the model factor, since 1,400 reproduces as 8 configs x 15 puzzles
x 4 models x 3 seeds. So a row reading "1,400 runs, luna + terra" means the same run budget respread
over two models, which buys more puzzles or more seeds per model rather than the same coverage more
cheaply. The other reading, shrinking the grid, is cheaper and gives less: cutting sol from a
three-model 1,400-run grid at constant per-model coverage leaves 933 runs and 50,772 placement calls,
which is $469 plain and $512 with reflection at 10 attempts, against the table's $704 and $769. Under
the table's reading a model cut buys 56 percent; under the shrink reading it buys 35 percent and a
third of the coverage goes with it.

The one structural fact behind the whole table is that terra costs 12 times luna per call and sol 15
to 22 times, so the model list, not the run count, is the biggest single lever on this arm.

### 7.5 Do both arms fit

**The decomposition arm fits, at about a quarter of the ceiling.** $670 to $769 with contingency,
against a $3,000 ceiling and a $1,200 abort point. A full second pass does not fit under the abort
point: arm plus one re-run is $1,339 to $1,538, past $1,200 at either price, so a re-run is a
reassess-then-decide rather than a free retry.

**The ablation arm as the brief declares it does not fit, except in its smallest corner.** Taking the
decomposition arm at its high figure of $769 and requiring the pair to stay under $3,000.

**Every row below assumes the parallel session's per-attempt independence fix has landed, and it has
not.** `main` is still at 2671872. Without that fix an attempt replays the previous attempts, input
per call grows through a run instead of holding at 1,070, and the ablation arm's input cost becomes
quadratic in attempts, which is the regime the brief's own $3,000 model was built for. Rows are decided
here by margins as small as $75, so every row at 30 attempts has to be re-derived if the fix does not
land.

| Ablation configuration | Ablation cost (with reflection) | Plus decomposition at $769 | Fits under $3,000 |
|---|---:|---:|---|
| 1,400 runs, 10 attempts, three models, sol $4/$20 | $1,124 | $1,893 | **Yes** |
| 1,400 runs, 10 attempts, three models, sol $5/$30 | $1,400 | $2,169 | **Yes** |
| 1,400 runs, 10 attempts, luna + terra | $769 | $1,538 | **Yes** |
| 1,400 runs, 30 attempts, luna + terra | $2,306 | $3,075 | **No**, and it is only $75 over, so it turns on the decomposition arm landing at its low figure |
| 1,400 runs, 30 attempts, three models | $3,372 to $4,200 | $4,141 to $4,969 | **No**, over the ceiling on its own |
| 4,800 runs, 10 attempts, luna + terra | $2,635 | $3,404 | **No** |
| 4,800 runs, 10 attempts, three models | $3,854 to $4,800 | $4,623 to $5,569 | **No**, over the ceiling on its own |
| 4,800 runs, 30 attempts, any mix above luna alone | $7,905 to $14,401 | $8,674 to $15,170 | **No** |
| Any configuration, luna only | $119 to $1,221 | $888 to $1,990 | **Yes**, at every size, but a one-model ablation cannot support a claim about model families or scales |

**The plain answer.** Both arms fit together only at the bottom of the ablation arm's declared range:
1,400 runs at 10 attempts. At that size the pair costs $1,538 to $2,169 depending on the model list and
on which sol price is real, and the pair crosses the $1,200 abort-and-reassess point during the
ablation arm rather than during the decomposition arm. At 30 attempts or at 4,800 runs the ablation
arm exceeds the $3,000 ceiling on its own in every configuration except five: luna and terra at 1,400
runs and 30 attempts ($2,306), luna and terra at 4,800 runs and 10 attempts ($2,635), and the three
luna-only cells at those sizes ($356, $407 and $1,221). The first two are the configurations where the
decomposition arm is what breaks the budget; the luna-only cells stay under $3,000 paired as well.

**Which arm to cut, or whether to cut attempts instead of an arm, is Jadon's decision and is not made
here.** What the numbers say is that the binding constraint is the ablation arm's attempt count and
model list. The decomposition arm at $769 is about a quarter of the $3,000 ceiling, and it is the sole
reason a configuration fails to fit in two rows of the table above, not one. 1,400 runs at 30 attempts
on luna and terra costs $2,306 alone, which fits, and $3,075 paired, which does not; it is $75 over, so
that row turns on the decomposition arm landing at its low figure. 4,800 runs at 10 attempts on luna
and terra costs $2,635 alone, which fits, and $3,404 paired, which does not; that row is $404 over and
no plausible decomposition figure rescues it. Every other failing row exceeds the ceiling on its own.

**The two ways these figures could be wrong, in the direction that matters.** Output tokens are a
right-tailed distribution whose tail was truncated at 4,096 by the cap in force during measurement, and
raising the cap to 16,384 lets it out; the 35 percent contingency is a guess at that, not a
measurement. And the ablation figures assume every attempt is played and no attempt replays history;
if the parallel session's per-attempt independence fix does not land, replay growth returns and the
ablation arm's input cost grows quadratically in attempts, which is the regime the brief's own cost
model was built for.

---

## 8. Ruled out, do not re-derive

Each of these cost real time to establish. The point of this section is that nobody spends that time
again.

### From the design work

**The per-candidate-margin elicitation channel.** Asking the model for a predicted margin for each
candidate placement, then reading its choice against its own numbers. Ruled out on a measurement taken
this session. A stratified probe over 21 complete boards, 3 at each true margin from -4 to +2, asked
each model to predict the margin of a finished board with nothing left to search, and scored it against
the exact oracle:

| | exact | within +-1 | MAE | bias | \|error\| >= 2 |
|---|---:|---:|---:|---:|---:|
| best constant predictor | 14% | 43% | 1.71 | | |
| luna | 38% | 62% | 1.33 | -0.95 | 38% |
| terra | 43% | 67% | 1.14 | -0.76 | 33% |
| sol | 48% | 71% | 1.00 | -0.14 | 29% |

All three beat the constant by about 3x on exact match and the ordering luna, terra, sol holds on every
statistic, so the models genuinely know something. But MAE of 1.00 to 1.33 is the same size as the
modal action gap, which is exactly 1 (32,382 of 38,770 free visits on the shipped suite, 83.5 percent).
A channel whose error equals the gap it has to resolve cannot reliably separate the best candidate from
the second best in this environment. Two further facts about that probe, both of which belong in any
write-up of it: models are systematically pessimistic about their own margin and the bias shrinks with
tier, and part of that pessimism is an artifact of the flat prior imposed by stratifying, which
oversamples rare positive margins, so accuracy must be reported under both priors.

**"Within +-1" as a headline on an unstratified sample.** The first probe used 16 boards whose true
margins only ran -3 to -1: luna 56 percent exact and MAE 0.56, terra 75 percent and 0.25, sol 81
percent and 0.19. On that sample the best constant predictor scores 56 percent exact and 100 percent
within +-1, so "within +-1" is uninformative and luna is indistinguishable from a constant. This is the
same shape of confound as the material-differential collinearity that killed L10's eight-point curve.

**EVPI and wait-and-see.** Both are identically zero on every puzzle in the suite, because there is no
exogenous randomness and no hidden state, so the wait-and-see solution and the here-and-now solution
coincide. Any metric built on them returns a constant zero and measures nothing about the agent.

**The two-step task's model-based / model-free weight** (Daw et al.), with its reward-by-transition-type
stay-probability signature. It needs stochastic transitions (common and rare) and cross-trial learning
to identify the weight. This environment is deterministic and the agent does not learn, so the
diagnostic interaction is undefined. It also splits on the wrong axis: both of our error sources are
model-based in its sense.

**Difficulty as an axis.** Tested on 2026-09-10 and it did not earn the claim: computed difficulty does
not predict observed LLM performance, not on a suite spanning 0 to 1 and not on a generated suite built
inside the low band, and it inverts at one adjacent pair. Difficulty is recorded as a covariate
everywhere in this design and appears on no axis. Play count and mean play length are covariates for
the same reason: they are the rank-collinear bundle L10 named, so stratifying on either one makes the
stratifier the confound.

**The certainty-equivalence model-over-regret headline.** Elicit an executable dynamics model, define
`m_t` as the loss from planning perfectly inside it and `d_t` as the residual, and report `M/R`. The
identity `r_t = m_t + d_t` is real and was verified at 40,260 decision points with 0 failures and 0
negative `m_t`. The headline built on it is degenerate. With a plausible corrupted elicited engine, the
positive and negative parts of the residual measured `E[d+] = 18,415` against `E[d-] = -18,268`, which
cancel to `D = 147` and give `M/R = 100%` and `D/R = 0%` for reasons that have nothing to do with
dynamics. The mechanism: `m_t` prices planning perfectly over an exhaustive enumeration of up to
524,880 plays (the game's branching ceiling; an accepted puzzle is capped at 60,000), against an
agent that spends a median 567 to 798 reasoning tokens per placement and
enumerates nothing, so the counterfactual is unreachable and `d_t` becomes a signed residual that
closes by cancellation against any agent whose deviations from its own model's argmax are roughly
symmetric. The elicitation itself survives as a fenced secondary at $25 to $33 (section 2.3); the
headline does not. If it is ever run, the cancellation ratio `|E[d-]| / E[d+]` is a gate above which
the signed term is declared uninformative and no `M/R` is printed at all.

**Charging a level to dynamics.** The congruence census is the best artifact in the design work and two
reviewers reproduced it independently to the decimal, but defining the dynamics estimate as the regret
at decision points where an analyst-chosen myopic rule already suffices makes it a residual bucket with
a name on it: it cannot separate dynamics error from lapse noise, positional bias or board misreading.
The census is used here as a suite criterion and a per-decision stratifier, never as an estimator.

**A lookahead-depth and value-noise reference-agent fit.** Corrupting the true terminal value with
i.i.d. zero-mean noise and fitting a depth and a noise level. No false battle rule produces zero-mean
noise on `V*`; a wrong rule produces a systematically different, board-correlated value function. The
noise axis is also quantized by the measured action gap: at remaining depth 1, noise levels of 0 and
0.25 are literally indistinguishable, because a uniform draw on [-0.25, 0.25] can never flip an integer
gap of at least 1, so seven declared noise levels have roughly three effective ones.

### From the literature survey, 19 entries ruled out; the ones most likely to be re-proposed

| What it was | Why it does not work here |
|---|---|
| MBPO-style branched-rollout returns bound with measured model error | Its split is model error against policy shift relative to a data-collecting policy. There is no data-collecting policy here, no training distribution, and deterministic dynamics collapse its total-variation model-error measure. Keep only the k-step branched-rollout construct as a measurement device |
| Selective Dyna-style planning via decomposed predictive uncertainty | Its instrument is heteroscedastic variance minus ensemble variance, which needs a trainable model and a data distribution. Neither exists for a prompted model against a known deterministic simulator. Its negative result is worth stating when positioning: aleatoric and parameter uncertainty both vanish here, which makes our model-error side unambiguous |
| Regan-Haworth two-parameter fallible-agent fit (sensitivity, consistency) | A one-layer choice model with no search axis and no belief axis, so it yields a scalar skill profile that cannot attribute a bad placement to not knowing against not searching. Keep it only as the per-decision likelihood inside a depth-and-consistency grid |
| Estimate-then-optimize regret bound via the prediction-decision cross-derivative | Every assumption it rests on (smoothness, unconstrained continuous decisions, strong concavity, differentiable parameterization) is violated by a discrete placement puzzle with an integer-valued piecewise-constant value function |
| LLM-as-world-model inside MCTS with a state-confidence reward (RAP) | The canonical example of the confound to avoid: failures are jointly attributable to the world model and the policy with no way to apportion them, and the paper never scores the world model |
| Activation probes plus generative action-ranking for world-model recovery | Needs white-box activations or at minimum token log-probs, which this benchmark does not have through the API, and the property it measures (action legality) is trivially readable off our prompt. Its warning still carries: a competent internal model and a competent chosen action can come apart, so reading beliefs only from behaviour may under-attribute to search |
| STOCKTAKE's fair oracle, detection lag, knowing-doing rate and skill score | Ruled out as framing (it is prior art, see section 1) and as a mechanism, because it infers belief from self-report under partial observability. In a deterministic fully observable puzzle with an exact `V*`, reading belief from rationale text throws away the one thing this environment has that STOCKTAKE lacks. Keep only the two-endpoint skill normalization |
| Multi-environment or two-discount-factor reward recovery under entropy regularization | Its guarantee is conditional on a known correct behavioural model, which is the unknown here, and its disambiguating variation is over discount factors or over the true transition dynamics. This environment has no discount factor, and its true dynamics are the fixed object the agent's model is compared against, so varying them changes the estimand instead of identifying it |
| The Occam Sufficiency Hypothesis as an escape from No Free Lunch | No theorem, no estimator, and it relies on an uncomputable complexity measure, so it cannot produce a split for any concrete agent. It also does not engage the reward-negation symmetry, which is the half of the result that maps most directly onto "perfect model with terrible search" against "terrible model with perfect search" |
| Test-awareness probing and activation steering | Needs white-box activations and weight edits, targets safety compliance rather than decision quality, and the reactivity it measures is common to both arms so it cannot explain a difference between them. The eval-framing control covers the observable version of the same worry |
| Adaptive submodularity and the adaptive greedy policy | The realization distribution is a point mass here, so by the paper's own reduction it collapses to ordinary submodularity and the adaptive greedy collapses to the non-adaptive greedy. It would measure an adaptivity gap that is provably zero |
| NLCO benchmark metrics (feasibility rate, accuracy, average log optimality gap) | Feasibility rate is degenerate here and the log optimality gap is mis-scaled for a small-integer margin. Retained as a citation: the closest-adjacent literature measures an optimality gap against an exact reference and still never asks whether its own solution space is permutation-inflated or how many of its decisions are forced |
| Metamorphic "tool order invariance" for agent regression testing | Wrong object: it permutes the presentation of options rather than the sequence of executed placements, and tests output stability rather than value-function structure. Its residual use overlaps entirely with the serialization-order control |
| Online submodular maximization over sequences | Online adversarial job arrival is not this setting, where every instance is fully known offline. Recorded as covered and rejected rather than silently dropped, and flagged as not opened beyond an abstract listing |

**One entry in that list is wrong and must not be carried forward.** The survey recorded CalBench as an
identifier mismatch and advised not conceding its framing. The verification pass refuted that in terms:
CalBench v3 does define per-instance difficulty as the CP-SAT feasible fraction and does define oracle
regret, so the brief's original reading was right and the survey's mismatch finding was the error. What
CalBench does not do is pair them in any reported result, and its regret is a per-agent scalar rather
than per-prefix. Section 1 and section 10 carry the corrected version.

---

## 9. Open choices for Jadon

Seven. Each is stated as the thing he would see change, with a recommendation, so answering takes
seconds. None blocks Stage 0 or Stage 1, which cost nothing and can start immediately.

**1. Suite size, and whether to include the three shipped puzzles as anchors.** Twelve accepted
puzzles gives a smallest possible one-sided p-value of 1 in 4,096 on the headline contrasts; sixteen
gives 1 in 65,536 and costs about a third more in both API spend and generator wall clock. Adding the
three shipped puzzles as anchors is what would let any sentence tie this arm's numbers to the
scaffolding arm's existing logs; the cost is that their strict-incongruent shares are 5.6, 0.0 and
41.0 percent, so one of them contributes nothing to half the dissociation. The recommendation below
is 15 puzzles, not the 12 that section 7.3 prices, and the difference is not free: 15 is 25 percent
more on every per-puzzle arm, which is $62 to $74 if the anchors run only the single-turn arms and $90
to $102 if they run L3 and L1C as well, and it moves the one-sided permutation floor to 1 in 32,768.
*Recommendation: 12 accepted plus the 3 anchors, with the anchors excluded from the class-N analysis
and that exclusion stated, and section 7.3's total read as the 12-puzzle figure.*

**2. Attempts per cell, 24 or 40.** Decide after the choice-entropy gate rather than before. If 20
repeats of one prompt return the same placement 20 times, attempts buy almost nothing and the upgrade
should go to more puzzles instead. The upgrade's size depends on which cells scale, which is worth
deciding in the same breath: scaling the single-turn arms alone costs $166 at the lower sol price and
$197 at the higher, and scaling the L3 arms with them costs $222 and $253. If the modal placement takes under about 60 percent of
draws, 40 attempts roughly halves the confidence-interval width on every contrast and is the cheapest
power available. *Recommendation: hold at 24 and let Stage 2 decide, since Stage 2 costs under a dollar.*

**3. Whether sol runs the placebo rungs L1P and L2P.** Section 2.1 has sol running L0, L1 and L2 only,
and the $670 to $769 headline is the total without these two arms. Adding them is 3,133 calls, $69 at
the vendor sol price and $100 at the tracker price, which with the same 35 percent contingency puts
the arm at $763 to $905. Without them, the claim that the rules effect is informational rather than
length-driven, and the claim that the VALUES rung actually delivers its numbers, hold for luna and
terra only, and every sol number carries an asterisk saying its manipulation checks were not run.
*Recommendation: run them, and read the arm at $763 to $905 if that is the answer. The cost is 10 to
13 percent of the arm, and an asterisk on the most expensive model is the worst place to put one.*

**4. The tool cap K at L3, 10 or 6.** K sets the cost multiplier on the single most expensive arm and
it sets what the L3 number means. A cap that binds turns the upper search endpoint from "search regret
under an exact model" into "search regret under a K-query budget", which is a weaker and
differently-worded claim. The cap-hit rate is logged either way and tells you after the fact which
claim you bought. *Recommendation: K = 10 through the pilot, then set the grid's K from the measured
cap-hit rate at G6.*

**5. Whether the compiled-belief secondary ships at all.** Costs $25 to $33 plus one new module and the
resolver seam. With it, the paper can say which rule is wrong in named units, for example "behaves like
an agent that thinks escapes score nothing: 2.1 margin points per puzzle", and can report a
puzzle-level correlation against the measured rule-inference effect. Without it, the paper can say how
much regret supplying the dynamics removes and nothing at all about the content of the error.
*Recommendation: ship it, fenced as secondary. It is 4 percent of the arm's cost for the only sentence
in the paper that names a rule.*

**6. Which role text is primary at L0, trimmed or shipped.** The trimmed role removes the artifact of
instructing an agent to infer mechanics from tracethroughs it does not have, which sits directly on the
headline contrast. The shipped role preserves byte-comparability with the factorial arm's I0 cells. The
bridge subsample measures the gap between them either way, so this decides which number is the headline
and which is the footnote, not whether the artifact is known. *Recommendation: trimmed as primary,
shipped as the bridge, and report both in the same table.*

**7. L1C at two corruptions or three.** Two corruptions give two points against their precomputed
predicted regrets, which tests direction. Three give a dose-response, which tests whether the realised
regret increase tracks the size of the predicted one, which is calibration rather than direction. The
third costs $14.48, on luna and terra only, which is where L1C runs; sol's contested price does not
enter it. *Recommendation: two, and add the third only if the first two land on their predicted
values, since a dose-response through two points that both missed is worth nothing.*

---

## 10. Notes back to the paper brief

These are findings from this session that change what the paper can claim. `PAPER_BRIEF.md` is not this
session's to edit, so they are written here for Jadon to carry across.

**1. The CalBench positioning is better than the brief records.** The brief says "difficulty computed
per instance from environment structure" and "regret against a computable oracle" are "not novel as a
pair", and concedes the pair to CalBench. Full-text verification of v3 says less than that. CalBench's
regret is labelled in its own text as an upper-bound regret proxy and is aggregated to one scalar per
agent per game; the strings "prefix" and "per-action" do not appear anywhere in the paper; there is no
`V*` over prefixes; and v3 reports no result broken out by difficulty bucket at all, so the pair is
present in the instrumentation and absent from the results. The defensible concession is narrower:
CalBench owns pre-run structural difficulty and oracle regret coexisting in one benchmark, and it does
not own regret against an exact continuation value resolved per decision. Two smaller corrections for
the same paragraph: the brief lists v1 and v2 (10 May, 5 June) and there are three versions (10 May,
28 May, 5 June) with the difficulty definition rewritten between them, so the citation must pin a
version. The suite size is a separate question and is unresolved: one pass of this session recorded
72 tasks in v1 growing to 90 in v3, the verification read of v3's own full text recorded a 72-task
suite, and the two were never reconciled. Do not put a task count in a paper without re-reading v3. and the "coordination-adjusted regret" name in the brief
is the paper's "upper-bound regret proxy", same object, different name.

**2. The "Ming Liu, Amazon" affiliation is settled, and the brief has it right.** 2605.05716 has one
author. Its PDF title block, read directly with `pdftotext -f 1 -l 1` in this session, reads "More Is
Not Always Better: Cross-Component Interference in LLM Agent Scaffolding / Ming Liu / Amazon / Data
Scientist / mlliuz@amazon.com". An earlier pass reported the arXiv abstract page showing no
institution, which is true and means nothing: an arXiv abs page never prints affiliations. The two
passes were looking at different surfaces rather than contradicting each other. So the brief's
"Amazon, industry, not faculty" stands, and with it the decision to treat him as an outreach target
rather than a potential advisor. Nothing here needs re-checking.

**3. Prompt caching cannot fire at the prompt's current size, so the "$500 to $900 with aggressive
caching" figure is unreachable as things stand.** Cached tokens were 0 on all 29 calls measured this
session, and the reason is structural rather than a configuration mistake: the prompt is 969 tokens
against a documented 1,024-token minimum for automatic caching on GPT-5.6 and later. The brief calls
caching "a requirement, not a hope". It is currently neither, it is unavailable. Two consequences.
Padding the prompt to cross 1,024 is not a fix, because it changes the stimulus and therefore the
measurement. And caching would be worth at most 11 to 17 percent by model even if it fired, and only
on the repeated part of the prompt, because reasoning tokens are 94 percent of output and output
dominates input 5.7 to 1 on luna and 7.0 to 1 on terra at the input figure section 7 prices with. So
the brief's input-only cost model is measuring the smaller half.

**4. The brief's cost model omits output tokens entirely while overstating input, and the error does
not cancel.** The model is 20 attempts x roughly 800 tokens added per turn, giving about 208,000 input
tokens per run at a 2,000-token base, times 4,800 runs, giving about 1.0 billion input tokens at an
assumed $3.00 per million, which is about $3,000. Two things are wrong with it in opposite directions.
The input side is built on replay growth, where each attempt carries the previous attempts, which is
what makes it quadratic in attempts; the parallel session's per-attempt independence fix removes that
growth, and the measured input is 969 tokens per call and essentially constant, not 2,000 growing by
800 per turn. And the output side is absent, while the measurement says output is where the money is.
Recomputed at the measured rates in section 7.4, 4,800 runs at 30 attempts is $7,239 to $13,187
depending on the model list, so the brief's $3,000 was an underestimate of the largest configuration
rather than an overestimate, even though its input model was too big. The brief's own warning that
"every dollar figure below is a model, not a measurement" is the right frame; section 7 replaces the
model with a measurement for the token counts and leaves sol's price unresolved.

**5. One operational note that is not about claims.** A fresh worktree has no `godot/.godot` directory,
because it is gitignored, and without it `oracle/equivalence.py` fails with a GDScript parse error
("Identifier UnitData not declared") that reads exactly like a regression and is not one. One
`godot --headless --path godot --import` fixes it. Worth a line wherever the repo's setup is written
down, because the next person to open a worktree will lose an hour to it.

---

## Appendix: the baseline this design was written against

All green in this worktree on 2026-09-11, at commit 2671872.

| Check | Result |
|---|---|
| `python3 -B oracle/analysis.py` | 3,240 / 1,080 / 7,230 plays at difficulty 0.0318 / 0.0037 / 0.0430 |
| `python3 -B oracle/generate.py self-check` | passes |
| `python3 -B oracle/runlog.py self-check` | passes, ending "42 refusals fired" |
| `python3 -B oracle/equivalence.py` | 17,190 cases, 84,910 steps, 0 divergences, PASSED, 10.2 seconds |
| GUT suite | 9 scripts, 108 passing tests, 310 asserts |

A green check is evidence the check passed and not that the thing works. In particular, nothing above
exercises the offline driver, the census, or any rung of the ladder, because none of them exists yet.

`main` is still at commit 2671872 and identical to `decomp`. The parallel session's per-attempt
independence fix, model-identity logging and token logging have not landed. There is nothing to merge.
