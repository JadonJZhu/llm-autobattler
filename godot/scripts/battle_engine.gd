class_name BattleEngine
extends RefCounted
## Pure battle logic. Operates on snapshot dictionaries, never holds Node refs.
##
## Snapshot format: Dictionary[Vector2i] → { "unit_type": UnitType, "owner": Owner, "placement_order": int }
## Snapshot metadata: snapshot["__meta"] → { "llm_escaped": int, "human_escaped": int }

const ROWS: int = 4
const COLS: int = 3

# --- Public ---

## Execute one step for the given owner. Returns a result dictionary:
## {
##   "acting_unit_pos": Vector2i or null,
##   "acting_unit_type": UnitType or null,
##   "move": { "from": Vector2i, "to": Vector2i } or null,
##   "removal": Vector2i or null,          # enemy removed
##   "self_removal": Vector2i or null,      # unit removed itself (off-edge)
##   "event": String,
##   "is_finished": bool,
##   "winner": Owner or null,               # null = tie or not finished
##   "active_owner": Owner,
##   "llm_score": int,
##   "human_score": int,
##   "llm_remaining": int,
##   "human_remaining": int,
##   "llm_escaped": int,
##   "human_escaped": int,
## }
func execute_step(snapshot: Dictionary, active_owner: Unit.Owner) -> Dictionary:
	_ensure_snapshot_meta(snapshot)
	var result: Dictionary = {
		"acting_unit_pos": null,
		"acting_unit_type": null,
		"move": null,
		"removal": null,
		"self_removal": null,
		"event": "",
		"event_type": "",
		"is_finished": false,
		"winner": null,
		"active_owner": active_owner,
		"llm_score": 0,
		"human_score": 0,
		"llm_remaining": 0,
		"human_remaining": 0,
		"llm_escaped": 0,
		"human_escaped": 0,
	}

	var acting_unit := _pick_acting_unit(snapshot, active_owner)
	if acting_unit == Vector2i(-1, -1):
		# No units can act — check terminal
		result["event"] = "No units can act for %s (turn skipped)" % _owner_label(active_owner)
		result["event_type"] = "pass"
		_check_terminal(snapshot, result)
		return result

	var unit_data: Dictionary = snapshot[acting_unit]
	result["acting_unit_pos"] = acting_unit
	result["acting_unit_type"] = unit_data["unit_type"]

	match unit_data["unit_type"]:
		Unit.UnitType.A:
			_act_a(snapshot, acting_unit, unit_data["owner"], result)
		Unit.UnitType.B:
			_act_b(snapshot, acting_unit, unit_data["owner"], result)
		Unit.UnitType.C:
			_act_c(snapshot, acting_unit, unit_data["owner"], result)
		Unit.UnitType.D:
			_act_d(snapshot, acting_unit, unit_data["owner"], result)

	_check_terminal(snapshot, result)
	return result


## Check if neither side can make any more valid moves.
func is_stalemate(snapshot: Dictionary) -> bool:
	var llm_can_act := _pick_acting_unit(snapshot, Unit.Owner.LLM) != Vector2i(-1, -1)
	var human_can_act := _pick_acting_unit(snapshot, Unit.Owner.HUMAN) != Vector2i(-1, -1)
	return not llm_can_act and not human_can_act


# --- Unit Actions ---

func _act_a(snapshot: Dictionary, pos: Vector2i, unit_owner: Unit.Owner, result: Dictionary) -> void:
	var ahead := _cell_ahead(pos, unit_owner)
	if _has_enemy_at(snapshot, ahead, unit_owner):
		snapshot.erase(ahead)
		result["removal"] = ahead
		result["event"] = "A at %s removes enemy at %s" % [pos, ahead]
		result["event_type"] = "attack"
	else:
		_try_advance(snapshot, pos, unit_owner, result)


func _act_b(snapshot: Dictionary, pos: Vector2i, unit_owner: Unit.Owner, result: Dictionary) -> void:
	# Diagonal left ahead
	var ahead := _cell_ahead(pos, unit_owner)
	var diag_left := Vector2i(ahead.x, ahead.y - 1)

	if pos.y == 0:
		# On leftmost column — cannot attack, try advance
		_try_advance(snapshot, pos, unit_owner, result)
		return

	if _has_enemy_at(snapshot, diag_left, unit_owner):
		snapshot.erase(diag_left)
		result["removal"] = diag_left
		result["event"] = "B at %s removes enemy at %s" % [pos, diag_left]
		result["event_type"] = "attack"
	else:
		_try_advance(snapshot, pos, unit_owner, result)


func _act_c(snapshot: Dictionary, pos: Vector2i, unit_owner: Unit.Owner, result: Dictionary) -> void:
	# Diagonal right ahead
	var ahead := _cell_ahead(pos, unit_owner)
	var diag_right := Vector2i(ahead.x, ahead.y + 1)

	if pos.y == COLS - 1:
		# On rightmost column — cannot attack, try advance
		_try_advance(snapshot, pos, unit_owner, result)
		return

	if _has_enemy_at(snapshot, diag_right, unit_owner):
		snapshot.erase(diag_right)
		result["removal"] = diag_right
		result["event"] = "C at %s removes enemy at %s" % [pos, diag_right]
		result["event_type"] = "attack"
	else:
		_try_advance(snapshot, pos, unit_owner, result)


func _act_d(snapshot: Dictionary, pos: Vector2i, unit_owner: Unit.Owner, result: Dictionary) -> void:
	var closest := _find_closest_enemy(snapshot, pos, unit_owner)
	if closest != Vector2i(-1, -1):
		snapshot.erase(closest)
		result["removal"] = closest
		result["event"] = "D at %s removes enemy at %s" % [pos, closest]
		result["event_type"] = "attack"
	else:
		result["event"] = "D at %s has no enemies to target" % [pos]
		result["event_type"] = "pass"


# --- Helpers ---

func _cell_ahead(pos: Vector2i, unit_owner: Unit.Owner) -> Vector2i:
	# LLM faces down (increasing row), Human faces up (decreasing row)
	if unit_owner == Unit.Owner.LLM:
		return Vector2i(pos.x + 1, pos.y)
	else:
		return Vector2i(pos.x - 1, pos.y)


func _has_enemy_at(snapshot: Dictionary, cell: Vector2i, unit_owner: Unit.Owner) -> bool:
	if not snapshot.has(cell):
		return false
	return snapshot[cell]["owner"] != unit_owner


func _try_advance(snapshot: Dictionary, pos: Vector2i, unit_owner: Unit.Owner, result: Dictionary) -> void:
	var ahead := _cell_ahead(pos, unit_owner)
	var type_label: String = Unit.TYPE_LABELS[result["acting_unit_type"]]
	# Check if advancing goes off the board edge
	if ahead.x < 0 or ahead.x >= ROWS:
		_increment_escaped(snapshot, unit_owner)
		snapshot.erase(pos)
		result["self_removal"] = pos
		result["event"] = "%s at %s escaped off the board" % [type_label, pos]
		result["event_type"] = "escaped"
		return

	# Check if the cell ahead is occupied (friendly or enemy — can't move into occupied)
	if snapshot.has(ahead):
		result["event"] = "%s at %s cannot advance (cell %s occupied)" % [type_label, pos, ahead]
		result["event_type"] = "blocked"
		return

	# Advance
	var unit_data: Dictionary = snapshot[pos]
	snapshot.erase(pos)
	snapshot[ahead] = unit_data
	result["move"] = { "from": pos, "to": ahead }
	type_label = Unit.TYPE_LABELS[unit_data["unit_type"]]
	result["event"] = "%s advances from %s to %s" % [type_label, pos, ahead]
	result["event_type"] = "advance"


func _find_closest_enemy(snapshot: Dictionary, pos: Vector2i, unit_owner: Unit.Owner) -> Vector2i:
	var closest := Vector2i(-1, -1)
	var best_distance: int = 999

	# Collect enemies and sort by Manhattan distance, then col (left-to-right), then row (top-to-bottom)
	var enemies: Array[Vector2i] = []
	for key in snapshot.keys():
		if key is Vector2i:
			var cell_pos: Vector2i = key
			if snapshot[cell_pos]["owner"] != unit_owner:
				enemies.append(cell_pos)

	if enemies.is_empty():
		return Vector2i(-1, -1)

	for enemy_pos in enemies:
		var distance: int = abs(enemy_pos.x - pos.x) + abs(enemy_pos.y - pos.y)
		if distance < best_distance:
			best_distance = distance
			closest = enemy_pos
		elif distance == best_distance:
			# Tie-break: left-to-right (smaller col), then top-to-bottom (smaller row)
			if enemy_pos.y < closest.y or (enemy_pos.y == closest.y and enemy_pos.x < closest.x):
				closest = enemy_pos

	return closest


func _pick_acting_unit(snapshot: Dictionary, active_owner: Unit.Owner) -> Vector2i:
	## Find the highest-priority unit for the given owner that can act.
	## Priority: A > B > C > D, within same type: lower placement_order first.
	var candidates: Array[Vector2i] = _get_sorted_candidates(snapshot, active_owner)
	for candidate in candidates:
		if _can_unit_act(snapshot, candidate, active_owner):
			return candidate
	return Vector2i(-1, -1)


func _get_sorted_candidates(snapshot: Dictionary, active_owner: Unit.Owner) -> Array[Vector2i]:
	var candidates: Array[Vector2i] = []
	for key in snapshot.keys():
		if key is Vector2i:
			var cell_pos: Vector2i = key
			if snapshot[cell_pos]["owner"] == active_owner:
				candidates.append(cell_pos)

	if candidates.is_empty():
		return []

	# Sort by type priority (A=0, B=1, C=2, D=3), then placement_order
	candidates.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		var data_a: Dictionary = snapshot[a]
		var data_b: Dictionary = snapshot[b]
		if data_a["unit_type"] != data_b["unit_type"]:
			return data_a["unit_type"] < data_b["unit_type"]
		return data_a["placement_order"] < data_b["placement_order"]
	)

	return candidates


func _can_unit_act(snapshot: Dictionary, unit_pos: Vector2i, unit_owner: Unit.Owner) -> bool:
	if not snapshot.has(unit_pos):
		return false
	var unit_data: Dictionary = snapshot[unit_pos]
	var unit_type: Unit.UnitType = unit_data["unit_type"]
	var ahead: Vector2i = _cell_ahead(unit_pos, unit_owner)
	var can_advance: bool = ahead.x < 0 or ahead.x >= ROWS or not snapshot.has(ahead)

	match unit_type:
		Unit.UnitType.A:
			return _has_enemy_at(snapshot, ahead, unit_owner) or can_advance
		Unit.UnitType.B:
			if unit_pos.y > 0:
				var diag_left := Vector2i(ahead.x, ahead.y - 1)
				if _has_enemy_at(snapshot, diag_left, unit_owner):
					return true
			return can_advance
		Unit.UnitType.C:
			if unit_pos.y < COLS - 1:
				var diag_right := Vector2i(ahead.x, ahead.y + 1)
				if _has_enemy_at(snapshot, diag_right, unit_owner):
					return true
			return can_advance
		Unit.UnitType.D:
			return _has_any_enemy(snapshot, unit_owner)
	return false


func _has_any_enemy(snapshot: Dictionary, unit_owner: Unit.Owner) -> bool:
	for key in snapshot.keys():
		if key is Vector2i:
			var cell_pos: Vector2i = key
			if snapshot[cell_pos]["owner"] != unit_owner:
				return true
	return false


func _check_terminal(snapshot: Dictionary, result: Dictionary) -> void:
	var llm_count: int = 0
	var human_count: int = 0
	for key in snapshot.keys():
		if key is Vector2i:
			var cell_pos: Vector2i = key
			if snapshot[cell_pos]["owner"] == Unit.Owner.LLM:
				llm_count += 1
			else:
				human_count += 1

	var llm_can_act: bool = _pick_acting_unit(snapshot, Unit.Owner.LLM) != Vector2i(-1, -1)
	var human_can_act: bool = _pick_acting_unit(snapshot, Unit.Owner.HUMAN) != Vector2i(-1, -1)
	var both_empty: bool = llm_count == 0 and human_count == 0
	var both_stuck: bool = not llm_can_act and not human_can_act
	var escaped_meta: Dictionary = _get_meta(snapshot)
	var llm_escaped: int = int(escaped_meta.get("llm_escaped", 0))
	var human_escaped: int = int(escaped_meta.get("human_escaped", 0))
	var llm_score: int = llm_count + llm_escaped
	var human_score: int = human_count + human_escaped

	result["llm_remaining"] = llm_count
	result["human_remaining"] = human_count
	result["llm_escaped"] = llm_escaped
	result["human_escaped"] = human_escaped
	result["llm_score"] = llm_score
	result["human_score"] = human_score

	if both_empty or both_stuck:
		result["is_finished"] = true
		if llm_score > human_score:
			result["winner"] = Unit.Owner.LLM
			result["event"] += " | Game over by stalemate. LLM wins on score %d-%d." % [llm_score, human_score]
		elif human_score > llm_score:
			result["winner"] = Unit.Owner.HUMAN
			result["event"] += " | Game over by stalemate. Human wins on score %d-%d." % [human_score, llm_score]
		else:
			result["winner"] = null
			result["event"] += " | Game over by stalemate. Tie on score %d-%d." % [llm_score, human_score]


func _ensure_snapshot_meta(snapshot: Dictionary) -> void:
	if not snapshot.has("__meta"):
		snapshot["__meta"] = {
			"llm_escaped": 0,
			"human_escaped": 0,
		}
		return
	var meta: Dictionary = snapshot["__meta"]
	if not meta.has("llm_escaped"):
		meta["llm_escaped"] = 0
	if not meta.has("human_escaped"):
		meta["human_escaped"] = 0
	snapshot["__meta"] = meta


func _get_meta(snapshot: Dictionary) -> Dictionary:
	_ensure_snapshot_meta(snapshot)
	return snapshot["__meta"]


func _increment_escaped(snapshot: Dictionary, unit_owner: Unit.Owner) -> void:
	var meta: Dictionary = _get_meta(snapshot)
	if unit_owner == Unit.Owner.LLM:
		meta["llm_escaped"] = int(meta.get("llm_escaped", 0)) + 1
	else:
		meta["human_escaped"] = int(meta.get("human_escaped", 0)) + 1
	snapshot["__meta"] = meta


func _owner_label(owner: Unit.Owner) -> String:
	return "LLM" if owner == Unit.Owner.LLM else "Human"
