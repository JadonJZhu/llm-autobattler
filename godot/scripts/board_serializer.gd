class_name BoardSerializer
extends RefCounted
## Converts board state into a text representation for LLM consumption.

const GRID_SIZE: int = 6
const COLUMN_SEPARATOR: String = " | "


static func serialize(board: GameBoard) -> String:
	var lines: PackedStringArray = PackedStringArray()

	lines.append(_build_header())
	lines.append(_build_divider())

	for row: int in range(GRID_SIZE):
		var row_cells: PackedStringArray = PackedStringArray()
		for col: int in range(GRID_SIZE):
			var tile: Tile = board.get_tile(Vector2i(col, row))
			if tile:
				row_cells.append(_pad_cell(tile.get_serialized_label()))
			else:
				row_cells.append(_pad_cell("?"))
		lines.append(str(row) + " | " + COLUMN_SEPARATOR.join(row_cells) + " |")

	lines.append(_build_divider())
	return "\n".join(lines)


static func _build_header() -> String:
	var header_cells: PackedStringArray = PackedStringArray()
	for col: int in range(GRID_SIZE):
		header_cells.append(_pad_cell(str(col)))
	return "  | " + COLUMN_SEPARATOR.join(header_cells) + " |"


static func _build_divider() -> String:
	return "  +" + "-".repeat(GRID_SIZE * 6 + 1) + "+"


static func _pad_cell(text: String) -> String:
	if text.length() == 1:
		return " " + text + " "
	elif text.length() == 2:
		return " " + text
	return text
