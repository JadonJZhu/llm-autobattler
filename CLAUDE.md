# CLAUDE.md — Interactive Puzzle-Solving Project

## Project Overview

A 6x6 grid-based puzzle game built in Godot where an LLM (Claude Opus 4.6) attempts to solve a hidden pathfinding objective while a human acts as an adversary. The LLM receives only a correctness score — not the underlying rule — and must infer the goal through experimentation.

See `technical-plan.md` for full architecture and implementation phases.

## Code Principles

### SOLID
- **Single Responsibility**: Each script handles one concern. Do not combine unrelated logic.
- **Open/Closed**: Design systems to be extensible without modifying existing code. Use signals and composition over deep inheritance. New tile types or board layouts should not require rewriting core game logic.
- **Liskov Substitution**: If using inheritance (e.g., tile subtypes), subtypes must be fully substitutable for their base type without breaking behavior.
- **Interface Segregation**: Keep node interfaces small and focused. A tile node should not expose logging methods. A UI controller should not know about API payloads.
- **Dependency Inversion**: High-level modules (turn manager, game board) should depend on abstractions, not concrete implementations. Pass dependencies via signals, exported variables, or node references — not hardcoded paths.

### General Code Quality
- Prefer composition over inheritance. Use Godot's node tree and signals as the primary coupling mechanism.
- Keep functions short and focused. If a function does more than one thing, split it.
- Name variables and functions clearly. Avoid abbreviations. `current_tile_position` over `cur_pos`.
- No magic numbers. Use constants or exported variables for configurable values (grid size, API timeout, etc.).
- Handle errors explicitly. API calls, file I/O, and JSON parsing must have error handling. Do not silently swallow failures.
- Write GDScript that follows Godot's official style guide (snake_case, typed variables where possible).

## Key File Structure

```
godot/                     — Godot project root (kept separate from docs)
  project.godot
  scenes/game_board.tscn
  scripts/
    game_board.gd          — Grid rendering, board state management
    tile.gd                — Individual tile behavior (arrow direction, locked state)
    llm_client.gd          — Claude API HTTP requests and response parsing
    turn_manager.gd        — Turn alternation, win condition checking
    board_serializer.gd    — Board state → text representation for LLM
    logger.gd              — JSON turn/reasoning logging
    ui_controller.gd       — Thinking panel, chat interface, HUD
```

## When to Stop and Defer to the Human Engineer

**If a task requires any of the following, stop and describe what the human should do instead of attempting it yourself:**

- Manually positioning, scaling, or configuring nodes in the Godot editor Inspector panel
- Creating or editing `.tscn` scene files by hand (the serialization format is fragile and editor-managed)
- Importing, configuring, or assigning assets (textures, sprites, fonts, audio) through the Godot import system
- Setting up AnimationPlayer keyframes, Tween configurations, or visual shader graphs
- Adjusting physics layers, collision shapes, or navigation meshes in the editor
- Configuring project settings that require the Godot GUI (input map, display settings, autoloads) — unless the exact `project.godot` text format is known and straightforward
- Any task where the Godot editor's visual tools are the correct and less error-prone workflow

**Format for deferring:** Clearly state what needs to be done, which nodes/scenes are involved, and what properties to set. Provide step-by-step instructions the human can follow in the editor.

## LLM Integration Notes

- API target: Claude Opus 4.6 (`claude-opus-4-6`) only
- Use Godot's `HTTPRequest` node for API calls
- The LLM prompt must include: text grid state, correctness score, turn history, and game mechanics — but **never** the hidden path objective
- Parse the end LLM response for exactly two coordinate pairs (flip target + lock target)
- Capture and surface extended thinking / chain-of-thought content for the UI panel

## Conventions

- Godot version: 4.x
- Language: GDScript
- Signals over direct method calls for cross-node communication
- Use `@export` for inspector-configurable values
- Use typed variables (`var score: int = 0`) wherever possible
- Group related constants at the top of each script
- One script per file, one primary responsibility per script
