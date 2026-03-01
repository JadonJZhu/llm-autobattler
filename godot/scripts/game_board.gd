class_name GameBoard
extends Node2D
## Manages the 6x6 grid of tiles: creation, layout, state, and correctness scoring.

signal tile_clicked(grid_position: Vector2i)
signal board_ready

const GRID_SIZE: int = 6
const TILE_SPACING: int = 72
const TILE_SCENE_SIZE: int = 64

var tiles: Dictionary = {}  # Vector2i -> Tile
var _solution_directions: Dictionary = {}  # Vector2i -> Tile.Direction

@export var board_offset: Vector2 = Vector2(100, 60)


func _ready() -> void:
	pass


func initialize_board(board_data: Dictionary) -> void:
	_clear_board()
	_solution_directions = board_data.get("solution", {})

	var destination_x: Vector2i = board_data["destination_x"]
	var destination_y: Vector2i = board_data["destination_y"]
	var initial_directions: Dictionary = board_data.get("initial_directions", {})

	for row: int in range(GRID_SIZE):
		for col: int in range(GRID_SIZE):
			var grid_pos := Vector2i(col, row)
			var tile := _create_tile(grid_pos)

			if grid_pos == destination_x:
				tile.tile_type = Tile.TileType.DESTINATION_X
			elif grid_pos == destination_y:
				tile.tile_type = Tile.TileType.DESTINATION_Y
			elif initial_directions.has(grid_pos):
				tile.tile_type = Tile.TileType.ARROW
				tile.direction = initial_directions[grid_pos]
			else:
				tile.tile_type = Tile.TileType.EMPTY

			if _solution_directions.has(grid_pos):
				tile.correct_direction = _solution_directions[grid_pos]

			tiles[grid_pos] = tile

	board_ready.emit()


func _create_tile(grid_pos: Vector2i) -> Tile:
	var tile := Tile.new()
	tile.grid_position = grid_pos
	tile.position = Vector2(
		board_offset.x + grid_pos.x * TILE_SPACING,
		board_offset.y + grid_pos.y * TILE_SPACING
	)
	tile.tile_clicked.connect(_on_tile_clicked)
	add_child(tile)
	return tile


func _on_tile_clicked(grid_pos: Vector2i) -> void:
	tile_clicked.emit(grid_pos)


func flip_tile(grid_pos: Vector2i) -> bool:
	if not tiles.has(grid_pos):
		return false
	var tile: Tile = tiles[grid_pos]
	if tile.tile_type != Tile.TileType.ARROW:
		return false
	if tile.is_locked:
		return false
	tile.flip_direction()
	return true


func toggle_lock_tile(grid_pos: Vector2i) -> bool:
	if not tiles.has(grid_pos):
		return false
	var tile: Tile = tiles[grid_pos]
	if tile.tile_type != Tile.TileType.ARROW:
		return false
	tile.set_locked(not tile.is_locked)
	return true


func get_correctness_score() -> int:
	var score: int = 0
	for grid_pos: Vector2i in tiles:
		var tile: Tile = tiles[grid_pos]
		if tile.tile_type == Tile.TileType.ARROW and tile.is_correct():
			score += 1
	return score


func get_max_correctness_score() -> int:
	return get_arrow_tile_count()


func get_arrow_tile_count() -> int:
	var count: int = 0
	for grid_pos: Vector2i in tiles:
		if tiles[grid_pos].tile_type == Tile.TileType.ARROW:
			count += 1
	return count


func get_tile(grid_pos: Vector2i) -> Tile:
	return tiles.get(grid_pos)


func _clear_board() -> void:
	for grid_pos: Vector2i in tiles:
		tiles[grid_pos].queue_free()
	tiles.clear()
	_solution_directions.clear()


## Generates a board with a stochastic path from X to Y.
## X is placed in the top-left area, Y in the bottom-right area.
## The path randomly steps RIGHT or DOWN from X until reaching Y.
static func create_simple_board_data() -> Dictionary:
	var destination_x := Vector2i(randi() % 3, randi() % 3)
	var destination_y := Vector2i(3 + randi() % 3, 3 + randi() % 3)

	# Build path positions from X to Y by randomly stepping right or down.
	var path: Array[Vector2i] = [destination_x]
	var current: Vector2i = destination_x
	while current != destination_y:
		var can_go_right: bool = current.x < destination_y.x
		var can_go_down: bool = current.y < destination_y.y
		if can_go_right and can_go_down:
			if randi() % 2 == 0:
				current = Vector2i(current.x + 1, current.y)
			else:
				current = Vector2i(current.x, current.y + 1)
		elif can_go_right:
			current = Vector2i(current.x + 1, current.y)
		else:
			current = Vector2i(current.x, current.y + 1)
		path.append(current)

	# For each path tile (excluding X and Y), determine correct direction
	# based on the next tile in the path.
	var solution: Dictionary = {}
	var initial_directions: Dictionary = {}
	for i: int in range(1, path.size() - 1):
		var pos: Vector2i = path[i]
		var next_pos: Vector2i = path[i + 1]
		var correct_dir: Tile.Direction
		if next_pos.x > pos.x:
			correct_dir = Tile.Direction.RIGHT
		elif next_pos.y > pos.y:
			correct_dir = Tile.Direction.DOWN
		else:
			correct_dir = Tile.Direction.RIGHT
		solution[pos] = correct_dir
		# Randomize initial direction on the same axis as the correct direction.
		if correct_dir == Tile.Direction.RIGHT or correct_dir == Tile.Direction.LEFT:
			initial_directions[pos] = Tile.Direction.RIGHT if randi() % 2 == 0 else Tile.Direction.LEFT
		else:
			initial_directions[pos] = Tile.Direction.UP if randi() % 2 == 0 else Tile.Direction.DOWN

	return {
		"destination_x": destination_x,
		"destination_y": destination_y,
		"solution": solution,
		"initial_directions": initial_directions,
	}
