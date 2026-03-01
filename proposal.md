# Interactive LLM Inductive Reasoning Game — Project Plan

## Context
Build a Godot + LLM project to demonstrate research proficiency and Godot skills to a Riot Games researcher. The project connects to themes from a prior meeting: Stanford's Smallville paper, Riot's WILT benchmark (multi-turn inductive logic), and Godot proficiency. Primary goal is a polished interactive demo that proves competence; secondary goal is demonstrating research rigor through experimental design (described, not necessarily all executed).

## Core Research Question
**Can LLMs inductively discover hidden game rules and adapt to adversarial interference through multi-turn grid-based interaction?**

## Game Design

### Mechanics
- **Board**: 6x6 grid with two destination tiles (X, Y) and directional arrow tiles (4 cardinal directions)
- **Hidden rule**: Arrows should form a path from X to Y. The LLM is NOT told this — it only receives an opaque "correctness" score (count of arrows matching their correct orientation)
- **LLM turn**: Returns two coordinate pairs — one to flip an arrow, one to lock a tile (preventing human interaction)
- **Human turn**: Click one unlocked tile to flip its arrow (adversarial role)
- **Win condition**: LLM achieves maximum correctness score (complete path)
- **Input to LLM**: Text-based grid representation (not screenshots) + correctness score + turn history
- **Board states**: Pre-made initially, randomly generated later

### Two-Layer Inductive Reasoning
1. **Primary**: Discover what the correctness score rewards (path from X to Y)
2. **Secondary**: Discover adversarial interference exists and use locking strategically

## Architecture

### Godot (Frontend + Game Logic)
- Grid rendering with tile sprites/visuals for arrows, X, Y, locked indicators
- Click handling for human turns
- Turn management (alternating LLM and human)
- Dynamic UI panel showing LLM's raw reasoning/thinking
- Chat interface for optional human-LLM communication between turns
- Board state serialization to text format for LLM consumption

### LLM Integration (API Layer)
- HTTP requests from Godot to Claude API (Claude Opus 4.6 only)
- Structured prompt with: text grid state, correctness score, turn history, game rules (mechanics only, not the hidden path objective)
- Parse LLM response for two coordinate pairs
- Capture and display chain-of-thought / reasoning tokens

### Logging
- Log all turns: LLM reasoning, moves made, correctness score, lock usage
- JSON export for later analysis
- Lightweight — not a full experimental harness, but enough to support a writeup

## Scope: Demo-First Approach

### What to Build (Priority)
1. **Core game** — grid, tiles, turn logic, correctness scoring
2. **LLM integration** — Claude Opus 4.6 API, prompt design, response parsing
3. **Interactive UI** — reasoning display panel, chat interface, lock/turn indicators
4. **Basic logging** — turn-by-turn JSON logs for analysis

### What to Run
- ~5-10 games as the human adversary with different strategies (passive, random, targeted)
- A few baseline games with no adversary to establish if the LLM can discover the path rule alone
- Qualitative analysis of reasoning traces: when does the LLM hypothesize about the hidden rule? When does it notice interference?

### What to Describe (Future Work in Writeup)
- Full experimental design with controlled conditions (see below)
- Multi-model comparison
- Scripted adversary strategies for reproducible batch runs
- Statistical analysis across many games

## Experimental Design (For Writeup)

### Independent Variables
- **Board complexity**: Grid size (4x4, 6x6, 8x8), path length
- **Adversary strategy**: None (baseline), random flipping, targeted (undo LLM's last correct move)
- **Locking ability**: Enabled vs. disabled
- **Human guidance**: With/without optional chat hints between turns

### Dependent Variables
- Turns to solve (or failure after N turns)
- Correctness trajectory over time (learning curve)
- Turn of first strategic lock usage (evidence of adversary model formation)
- Hypothesis formation visible in reasoning traces (qualitative)

### Key Conditions
1. **Baseline**: LLM alone, no adversary → measures pure inductive discovery
2. **Adversary, no lock**: LLM vs. adversary, locking disabled → measures resilience
3. **Adversary + lock**: Full game → measures strategic adaptation
4. **Adversary + lock + chat**: Full game with human hints → measures guidance impact

## Implementation Phases

### Phase 1: Core Game (Godot)
- Grid rendering, arrow tiles, X/Y tiles
- Click-to-flip mechanic
- Turn alternation logic
- Board state serialization to text
- Correctness scoring

### Phase 2: LLM Integration
- Claude Opus 4.6 API integration via HTTPRequest
- Prompt engineering for the game context
- Response parsing for coordinate pairs
- Turn loop: serialize state → query LLM → apply moves → human turn

### Phase 3: UI & Polish
- LLM thinking/reasoning display panel
- Chat interface for human-LLM communication
- Lock indicators, turn indicators, correctness display
- Visual path highlighting when solved

### Phase 4: Logging & Preliminary Runs
- JSON turn logging
- Play 5-10 games, collect observations
- Write up findings + full experimental design as future work

## Verification
- Manually play through a game to verify turn logic and correctness scoring
- Verify LLM receives accurate text grid representations
- Run baseline (no adversary) to confirm LLM can solve simple boards
- Check that locking mechanics work correctly
- Validate logging captures turn data correctly

## Key Files to Create
- `project.godot` — Godot project config
- `scenes/game_board.tscn` + `scripts/game_board.gd` — Main game scene and logic
- `scripts/tile.gd` — Tile behavior (arrow, destination, locked state)
- `scripts/llm_client.gd` — Claude API integration
- `scripts/turn_manager.gd` — Turn alternation and win condition
- `scripts/board_serializer.gd` — Board state → text representation
- `scripts/logger.gd` — Turn/reasoning JSON logging
- `scripts/ui_controller.gd` — Thinking panel, chat, HUD
- `CLAUDE.md` — Project conventions and context
