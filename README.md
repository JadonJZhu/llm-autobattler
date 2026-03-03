# LLM Autobattler

A 4x3 autochess game built in Godot 4 where an LLM competes against a human player. Both players spend gold to buy and place units during a Prep phase, then watch units fight automatically in a Battle phase. The LLM receives a full game replay of the previous match to inform its next decisions.

The project also supports a **puzzle-based ablation mode** for evaluating LLM performance across different prompt configurations.

## Prerequisites

- [Godot 4.x](https://godotengine.org/download) (tested with 4.3+)
- Python 3.10+ (for experiment scripts)
- A `.env` file with your LLM configuration (see below)

### If you do not have Godot installed

1. Download Godot 4 from the [official download page](https://godotengine.org/download) and install it.
2. Find the full path to your Godot executable.
3. Set `GODOT_PATH` to that executable path (either in your shell or in `.env`).

Example (`.env`):

```bash
GODOT_PATH="/absolute/path/to/godot"
```

## Quick Start

```bash
git clone <repo-url>
cd interactive-puzzle-solving
```

### 1. Configure your LLM provider in `.env`

Create a `.env` file in the repo root:

```bash
LLM_API_KEY="your-api-key"
LLM_API_ENDPOINT="https://api.anthropic.com/v1/messages"
LLM_API_MODEL="claude-sonnet-4-6"
LLM_API_FORMAT="anthropic"
```

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | *(empty by default)* | Your API key |
| `LLM_API_ENDPOINT` | `https://api.anthropic.com/v1/messages` | Chat completions endpoint URL |
| `LLM_API_MODEL` | `claude-sonnet-4-6` | Model identifier |
| `LLM_API_FORMAT` | `anthropic` | `anthropic` or `openai` |

Two API formats are supported:

- **`anthropic`** — Native Anthropic Messages API (used by `api.anthropic.com`)
- **`openai`** — OpenAI-compatible chat completions (used by OpenRouter, Together, Groq, Ollama, vLLM, and most other providers)

Gameplay has been tested with both `claude-sonnet-4-6` and `gpt-5.3`.

### 2. Run the game

Use the launcher script (recommended):

```bash
./play.sh
```

`play.sh` loads `.env`, then prints whether it is launching in:

- real API mode (`LLM_API_KEY` is set), or
- simulated fallback mode (`LLM_API_KEY` is unset; random valid placements are used).

You can still run Godot directly if your environment is already configured:

```bash
/path/to/godot --path godot
```

## Running Experiments

These scripts launch Godot in headless mode and write outputs under `ablation_results/` by default.

### Official full experiment

`scripts/run_official_experiment.py` runs the full 8-config ablation and automatically resumes the latest incomplete full checkpoint if one exists.

```bash
python3 scripts/run_official_experiment.py
```

Common options:

```bash
python3 scripts/run_official_experiment.py \
  --godot-path "$GODOT_PATH" \
  --max-attempts 30 \
  --max-parallel 8 \
  --output-dir ./ablation_results
```

Notes:

- A real `LLM_API_KEY` is required (from environment or `.env`).
- If `--godot-path` is omitted, the script falls back to `GODOT_PATH` from environment or `.env`.

### Custom / direct ablation runs

Use `scripts/run_ablation.py` for direct control over mode, configs, and checkpoint behavior.

Full run:

```bash
python3 scripts/run_ablation.py --mode full
```

Mini run (2 configs):

```bash
python3 scripts/run_ablation.py --mode mini
```

Run specific configs only:

```bash
python3 scripts/run_ablation.py \
  --mode full \
  --configs I0_E0_R0 I1_E1_R1 \
  --max-attempts 10
```

Resume from checkpoint:

```bash
python3 scripts/run_ablation.py \
  --mode full \
  --resume \
  --checkpoint-path ./ablation_results/full_ablation_checkpoint.json
```

If needed, pass `--godot-path` explicitly; otherwise `run_ablation.py` uses `GODOT_PATH` from environment or `.env`.

## Provider Examples

### Anthropic (default)

```bash
LLM_API_KEY="sk-ant-..."
# Endpoint, model, and format all default to Anthropic.
```

### OpenRouter

```bash
LLM_API_KEY="sk-or-..."
LLM_API_ENDPOINT="https://openrouter.ai/api/v1/chat/completions"
LLM_API_MODEL="anthropic/claude-sonnet-4-6"
LLM_API_FORMAT="openai"
```

### Local Ollama

```bash
# No real key needed for local Ollama, but the field must be non-empty.
LLM_API_KEY="ollama"
LLM_API_ENDPOINT="http://localhost:11434/v1/chat/completions"
LLM_API_MODEL="llama3"
LLM_API_FORMAT="openai"
```

### Together AI

```bash
LLM_API_KEY="your-together-key"
LLM_API_ENDPOINT="https://api.together.xyz/v1/chat/completions"
LLM_API_MODEL="meta-llama/Llama-3-70b-chat-hf"
LLM_API_FORMAT="openai"
```

## Game Rules

- **Grid**: 4 rows x 3 columns. LLM occupies rows 0-1 (top); human occupies rows 2-3 (bottom).
- **Prep**: Players alternate placing units from a randomized shop (3 gold to start). LLM goes first.
- **Battle**: Deterministic. Units activate by priority (A > B > C > D), then by placement order.
- **Scoring**: Units remaining on board + units that escaped past the opponent's edge. Higher score wins.

### Unit Types

| Type | Cost | Behavior |
|------|------|----------|
| A | 1g | Attacks enemy directly ahead; advances if clear |
| B | 1g | Attacks enemy diagonally left-ahead; advances if clear |
| C | 1g | Attacks enemy diagonally right-ahead; advances if clear |
| D | 2g | Ranged: removes closest enemy by Manhattan distance |

## Project Structure

```
godot/
  project.godot          — Godot project file
  scenes/                — Scene files (.tscn)
  scripts/               — All GDScript source
  prompts/               — LLM prompt templates (model-agnostic)
  puzzles/               — Scripted puzzle scenarios for ablation
```

See `CLAUDE.md` for detailed architecture documentation.
