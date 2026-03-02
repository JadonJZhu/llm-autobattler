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

const ROWS: int = 4
const COLS: int = 3

const OWNER_PREFIXES: Dictionary = {
	Unit.Owner.LLM: "L",
	Unit.Owner.HUMAN: "H",
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
				var type_label: String = Unit.TYPE_LABELS[data["unit_type"]].to_lower()
				cells.append(_pad_cell(prefix + type_label))
			else:
				cells.append(_pad_cell("."))
		var side_label: String = ROW_SIDE_LABELS[row]
		lines.append("row %d  |%s|  %s" % [row, "|".join(cells), side_label])

	lines.append("       +------+------+------+")
	return "\n".join(lines)


static func _pad_cell(text: String) -> String:
	# Each cell is 6 chars wide (including surrounding spaces)
	var total_width: int = 6
	var padding: int = total_width - text.length()
	var left: int = padding / 2
	var right: int = padding - left
	return " ".repeat(left) + text + " ".repeat(right)
