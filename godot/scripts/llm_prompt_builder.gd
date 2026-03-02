class_name LlmPromptBuilder
extends RefCounted

func build_system_prompt() -> String:
	return "You are playing a 4x3 autochess game. The board has 4 rows and 3 columns.
You control the top 2 rows (rows 0-1). Your opponent (Human) controls the bottom 2 rows (rows 2-3).

GAME PHASES:
1. PREPARATION: You and the human alternate placing units. You place first each round.
2. BATTLE: Units fight automatically (you don't control this phase).

UNIT TYPES AND COSTS:
- A (1 gold): Attacks the cell directly ahead. If enemy there, removes it. Otherwise advances forward one cell.
- B (1 gold): Attacks diagonally left-ahead. If on leftmost column (col 0), cannot attack. Otherwise advances forward.
- C (1 gold): Attacks diagonally right-ahead. If on rightmost column (col 2), cannot attack. Otherwise advances forward.
- D (2 gold): Ranged unit. Removes the closest enemy by Manhattan distance (ties broken left-to-right, then top-to-bottom).

BATTLE MECHANICS:
- Your units face DOWN (toward higher rows). Human units face UP (toward lower rows).
- Turn order scan: A units are checked first, then B, then C, then D. Within same type, earlier-placed units are checked first.
- If the highest-priority unit is blocked and cannot act, the scan continues to the next unit in priority order until one can act.
- If no unit on that side can act, that side's step is skipped.
- Units that advance past the opponent's edge ESCAPE and earn 1 point.
- Battle alternates: you go first, then human, repeat until neither side can take any action.
- Score is: units still on board + escaped units. Higher score wins. Equal scores are a tie.

STRATEGY TIPS:
- A units are strong direct attackers but predictable.
- B and C units can attack diagonally, useful for flanking.
- D units are expensive (2 gold) but can snipe the most threatening enemy anywhere on the board.
- Escaping units is a valid way to score and can be better than chasing eliminations.
- Consider what the human might place and position your units to counter.

YOUR SHOP shows which unit types you can buy and your remaining gold.

RESPONSE FORMAT:
Think through your reasoning, then end your response with exactly this line:
PLACE: <type> (row, col)

Where <type> is A, B, C, or D, and row is 0 or 1 (your rows), col is 0, 1, or 2.
The PLACE line must be the last non-empty line of your response."


func build_user_message(
	board: GameBoard,
	llm_shop: Shop,
	turn_number: int,
	previous_game_replay: Dictionary
) -> String:
	var parts: PackedStringArray = PackedStringArray()

	parts.append("=== PREP TURN %d ===" % turn_number)
	parts.append("")
	parts.append("Current board state:")
	parts.append(BoardSerializer.serialize(board))
	parts.append("")
	parts.append("Your shop: %s" % llm_shop.get_purchase_summary())
	parts.append("")

	var replay_text: String = format_game_replay(previous_game_replay)
	if not replay_text.is_empty():
		parts.append(replay_text)
		parts.append("")

	parts.append("Choose a unit to place on your side of the board (rows 0-1).")
	return "\n".join(parts)


func format_game_replay(replay: Dictionary) -> String:
	if replay.is_empty():
		return ""

	var parts: PackedStringArray = PackedStringArray()
	parts.append("Previous game replay:")
	parts.append("")

	var start_board: String = replay.get("start_board", "")
	if not start_board.is_empty():
		parts.append("Start-of-battle board:")
		parts.append(start_board)
		parts.append("")

	var battle_steps: Array = replay.get("battle_steps", [])
	if not battle_steps.is_empty():
		parts.append("Battle trace:")
		for i in range(battle_steps.size()):
			parts.append("  %d. %s" % [i + 1, battle_steps[i]])
		parts.append("")

	var outcome: String = replay.get("outcome", "")
	var llm_score: int = int(replay.get("llm_score", -1))
	var human_score: int = int(replay.get("human_score", -1))
	if not outcome.is_empty():
		parts.append("Outcome: %s wins" % outcome if outcome != "Tie" else "Outcome: Tie")
	if llm_score >= 0 and human_score >= 0:
		parts.append(
			"Final score: LLM %d vs Human %d" % [llm_score, human_score]
		)

	return "\n".join(parts)
