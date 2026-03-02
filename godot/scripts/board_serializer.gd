class_name BoardSerializer
extends RefCounted
## Converts 4x3 autochess board state into ASCII text for LLM consumption.
##
## Output format:
##        col 0  col 1  col 2
##        +------+------+------+
## row 0  |  La  |  .   |  La  |  (LLM)
## row 1  |  .   |  Lb  |  .   |  (LLM)
## row 2  |  Ha  |  .   |  Hb  |  (Human)
## row 3  |  .   |  Hd  |  .   |  (Human)
##        +------+------+------+
##
## La = LLM unit type A, Hd = Human unit type D, . = empty

const ROWS: int = GridConstants.ROWS
const COLS: int = GridConstants.COLS

const OWNER_PREFIXES: Dictionary = {
	UnitData.Owner.LLM: "L",
	UnitData.Owner.HUMAN: "H",
}

const ROW_SIDE_LABELS: Dictionary = {
	0: "(LLM)",
	1: "(LLM)",
	2: "(Human)",
	3: "(Human)",
}


static func serialize(board: GameBoard) -> String:
	return serialize_snapshot(board.get_snapshot())


static func serialize_snapshot(snapshot: Dictionary) -> String:
	var lines: PackedStringArray = []

	# Header
	lines.append("       col 0  col 1  col 2")
	lines.append("       +------+------+------+")

	for row in range(ROWS):
		var cells: PackedStringArray = []
		for col in range(COLS):
			var pos := Vector2i(row, col)
			if snapshot.has(pos):
				var data: Dictionary = snapshot[pos]
				var prefix: String = OWNER_PREFIXES[data["owner"]]
				var type_label: String = UnitData.TYPE_LABELS[data["unit_type"]].to_lower()
				cells.append(_pad_cell(prefix + type_label))
			else:
				cells.append(_pad_cell("."))
		var side_label: String = ROW_SIDE_LABELS[row]
		lines.append("row %d  |%s|  %s" % [row, "|".join(cells), side_label])

	lines.append("       +------+------+------+")
	var score_summary: Dictionary = _compute_score_summary(snapshot)
	lines.append("")
	lines.append(
		"Score Summary: LLM %d (%d remaining + %d escaped) | Human %d (%d remaining + %d escaped)" % [
			score_summary["llm_score"], score_summary["llm_remaining"], score_summary["llm_escaped"],
			score_summary["human_score"], score_summary["human_remaining"], score_summary["human_escaped"],
		]
	)
	return "\n".join(lines)


static func _pad_cell(text: String) -> String:
	# Each cell is 6 chars wide (including surrounding spaces)
	var total_width: int = 6
	var padding: int = total_width - text.length()
	var left: int = int(padding / 2.0)
	var right: int = padding - left
	return " ".repeat(left) + text + " ".repeat(right)


static func _compute_score_summary(snapshot: Dictionary) -> Dictionary:
	var llm_remaining: int = 0
	var human_remaining: int = 0
	for key in snapshot.keys():
		if key is Vector2i:
			var pos: Vector2i = key
			var data: Dictionary = snapshot[pos]
			if data.get("owner", UnitData.Owner.LLM) == UnitData.Owner.LLM:
				llm_remaining += 1
			else:
				human_remaining += 1
	var meta: Dictionary = snapshot.get("__meta", {})
	var llm_escaped: int = int(meta.get("llm_escaped", 0))
	var human_escaped: int = int(meta.get("human_escaped", 0))
	return {
		"llm_remaining": llm_remaining,
		"human_remaining": human_remaining,
		"llm_escaped": llm_escaped,
		"human_escaped": human_escaped,
		"llm_score": llm_remaining + llm_escaped,
		"human_score": human_remaining + human_escaped,
	}
