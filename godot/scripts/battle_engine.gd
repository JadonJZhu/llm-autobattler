class_name BattleEngine
extends RefCounted
## Pure battle logic. Operates on snapshot dictionaries, never holds Node refs.
##
## Snapshot format: BattleSnapshot.units[Vector2i] → { "unit_type": UnitType, "owner": Owner, "placement_order": int }

const ROWS: int = GridConstants.ROWS
const COLS: int = GridConstants.COLS
static var NO_UNIT: Vector2i = Vector2i(-1, -1)

# --- Public ---

func execute_step(snapshot: BattleSnapshot, active_owner: UnitData.Owner) -> Dictionary:
	var units: Dictionary = snapshot.units
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

	var acting_unit := _pick_acting_unit(units, active_owner)
	if acting_unit == NO_UNIT:
		# No units can act — check terminal
		result["event"] = "No units can act for %s (turn skipped)" % _owner_label(active_owner)
		result["event_type"] = "pass"
		_check_terminal(snapshot, units, result)
		return result

	var unit_data: Dictionary = units[acting_unit]
	result["acting_unit_pos"] = acting_unit
	result["acting_unit_type"] = unit_data["unit_type"]

	var unit_type: UnitData.UnitType = unit_data["unit_type"]
	var act_method: Callable = _get_act_method(unit_type)
	act_method.call(snapshot, units, acting_unit, unit_data["owner"], result)

	_check_terminal(snapshot, units, result)
	return result


func _get_act_method(unit_type: UnitData.UnitType) -> Callable:
	match unit_type:
		UnitData.UnitType.A: return _act_a
		UnitData.UnitType.B: return _act_b
		UnitData.UnitType.C: return _act_c
		UnitData.UnitType.D: return _act_d
	push_error("BattleEngine: Unknown unit type: %d" % unit_type)
	return _act_a


## Check if neither side can make any more valid moves.
func is_stalemate(snapshot: BattleSnapshot) -> bool:
	var units: Dictionary = snapshot.units
	var llm_can_act := _pick_acting_unit(units, UnitData.Owner.LLM) != NO_UNIT
	var human_can_act := _pick_acting_unit(units, UnitData.Owner.HUMAN) != NO_UNIT
	return not llm_can_act and not human_can_act


# --- Unit Actions ---

func _act_a(
	snapshot: BattleSnapshot,
	units: Dictionary,
	pos: Vector2i,
	unit_owner: UnitData.Owner,
	result: Dictionary
) -> void:
	var ahead := _cell_ahead(pos, unit_owner)
	if _has_enemy_at(units, ahead, unit_owner):
		units.erase(ahead)
		result["removal"] = ahead
		result["event"] = "A at %s removes enemy at %s" % [pos, ahead]
		result["event_type"] = "attack"
	else:
		_try_advance(units, snapshot, pos, unit_owner, result)


func _act_b(
	snapshot: BattleSnapshot,
	units: Dictionary,
	pos: Vector2i,
	unit_owner: UnitData.Owner,
	result: Dictionary
) -> void:
	# Diagonal left ahead
	var ahead := _cell_ahead(pos, unit_owner)
	var diag_left := Vector2i(ahead.x, ahead.y - 1)

	if pos.y == 0:
		# On leftmost column — cannot attack, try advance
		_try_advance(units, snapshot, pos, unit_owner, result)
		return

	if _has_enemy_at(units, diag_left, unit_owner):
		units.erase(diag_left)
		result["removal"] = diag_left
		result["event"] = "B at %s removes enemy at %s" % [pos, diag_left]
		result["event_type"] = "attack"
	else:
		_try_advance(units, snapshot, pos, unit_owner, result)


func _act_c(
	snapshot: BattleSnapshot,
	units: Dictionary,
	pos: Vector2i,
	unit_owner: UnitData.Owner,
	result: Dictionary
) -> void:
	# Diagonal right ahead
	var ahead := _cell_ahead(pos, unit_owner)
	var diag_right := Vector2i(ahead.x, ahead.y + 1)

	if pos.y == COLS - 1:
		# On rightmost column — cannot attack, try advance
		_try_advance(units, snapshot, pos, unit_owner, result)
		return

	if _has_enemy_at(units, diag_right, unit_owner):
		units.erase(diag_right)
		result["removal"] = diag_right
		result["event"] = "C at %s removes enemy at %s" % [pos, diag_right]
		result["event_type"] = "attack"
	else:
		_try_advance(units, snapshot, pos, unit_owner, result)


func _act_d(_snapshot: BattleSnapshot, units: Dictionary, pos: Vector2i, unit_owner: UnitData.Owner, result: Dictionary) -> void:
	var closest := _find_closest_enemy(units, pos, unit_owner)
	if closest != NO_UNIT:
		units.erase(closest)
		result["removal"] = closest
		result["event"] = "D at %s removes enemy at %s" % [pos, closest]
		result["event_type"] = "attack"
	else:
		result["event"] = "D at %s has no enemies to target" % [pos]
		result["event_type"] = "pass"


# --- Helpers ---

func _cell_ahead(pos: Vector2i, unit_owner: UnitData.Owner) -> Vector2i:
	# LLM faces down (increasing row), Human faces up (decreasing row)
	if unit_owner == UnitData.Owner.LLM:
		return Vector2i(pos.x + 1, pos.y)
	else:
		return Vector2i(pos.x - 1, pos.y)


func _has_enemy_at(units: Dictionary, cell: Vector2i, unit_owner: UnitData.Owner) -> bool:
	if not units.has(cell):
		return false
	return units[cell]["owner"] != unit_owner


func _try_advance(
	units: Dictionary,
	snapshot: BattleSnapshot,
	pos: Vector2i,
	unit_owner: UnitData.Owner,
	result: Dictionary
) -> void:
	var ahead := _cell_ahead(pos, unit_owner)
	var type_label: String = UnitData.TYPE_LABELS[result["acting_unit_type"]]
	# Check if advancing goes off the board edge
	if ahead.x < 0 or ahead.x >= ROWS:
		if snapshot:
			_increment_escaped(snapshot, unit_owner)
		units.erase(pos)
		result["self_removal"] = pos
		result["event"] = "%s at %s escaped off the board" % [type_label, pos]
		result["event_type"] = "escaped"
		return

	# Check if the cell ahead is occupied (friendly or enemy — can't move into occupied)
	if units.has(ahead):
		result["event"] = "%s at %s cannot advance (cell %s occupied)" % [type_label, pos, ahead]
		result["event_type"] = "blocked"
		return

	# Advance
	var unit_data: Dictionary = units[pos]
	units.erase(pos)
	units[ahead] = unit_data
	result["move"] = { "from": pos, "to": ahead }
	type_label = UnitData.TYPE_LABELS[unit_data["unit_type"]]
	result["event"] = "%s advances from %s to %s" % [type_label, pos, ahead]
	result["event_type"] = "advance"


func _find_closest_enemy(units: Dictionary, pos: Vector2i, unit_owner: UnitData.Owner) -> Vector2i:
	var closest := NO_UNIT
	var best_distance: int = ROWS * COLS + 1

	# Collect enemies and sort by Manhattan distance, then col (left-to-right), then row (top-to-bottom)
	var enemies: Array[Vector2i] = []
	for cell_pos in units.keys():
		if units[cell_pos]["owner"] != unit_owner:
			enemies.append(cell_pos)

	if enemies.is_empty():
		return NO_UNIT

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


func _pick_acting_unit(units: Dictionary, active_owner: UnitData.Owner) -> Vector2i:
	## Find the highest-priority unit for the given owner that can act.
	## Priority: A > B > C > D, within same type: lower placement_order first.
	var candidates: Array[Vector2i] = _get_sorted_candidates(units, active_owner)
	for candidate in candidates:
		if _can_unit_act(units, candidate, active_owner):
			return candidate
	return NO_UNIT


func _get_sorted_candidates(units: Dictionary, active_owner: UnitData.Owner) -> Array[Vector2i]:
	var candidates: Array[Vector2i] = []
	for cell_pos in units.keys():
		if units[cell_pos]["owner"] == active_owner:
			candidates.append(cell_pos)

	if candidates.is_empty():
		return []

	# Sort by type priority (A=0, B=1, C=2, D=3), then placement_order
	candidates.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		var data_a: Dictionary = units[a]
		var data_b: Dictionary = units[b]
		if data_a["unit_type"] != data_b["unit_type"]:
			return data_a["unit_type"] < data_b["unit_type"]
		return data_a["placement_order"] < data_b["placement_order"]
	)

	return candidates


func _can_unit_act(units: Dictionary, unit_pos: Vector2i, unit_owner: UnitData.Owner) -> bool:
	if not units.has(unit_pos):
		return false
	var unit_data: Dictionary = units[unit_pos]
	var unit_type: UnitData.UnitType = unit_data["unit_type"]
	var ahead: Vector2i = _cell_ahead(unit_pos, unit_owner)
	var can_advance: bool = ahead.x < 0 or ahead.x >= ROWS or not units.has(ahead)

	# A and D have unique checks; B and C share diagonal-attack-or-advance logic
	match unit_type:
		UnitData.UnitType.A:
			return _has_enemy_at(units, ahead, unit_owner) or can_advance
		UnitData.UnitType.B:
			return _can_diagonal_attack_or_advance(units, unit_pos, ahead, unit_owner, -1, can_advance)
		UnitData.UnitType.C:
			return _can_diagonal_attack_or_advance(units, unit_pos, ahead, unit_owner, 1, can_advance)
		UnitData.UnitType.D:
			return _has_any_enemy(units, unit_owner)
	push_error("BattleEngine: Unknown unit type in _can_unit_act: %d" % unit_type)
	return false


func _can_diagonal_attack_or_advance(units: Dictionary, unit_pos: Vector2i,
		ahead: Vector2i, unit_owner: UnitData.Owner, col_offset: int,
		can_advance: bool) -> bool:
	var edge_col: int = 0 if col_offset < 0 else COLS - 1
	if unit_pos.y != edge_col:
		var diag := Vector2i(ahead.x, ahead.y + col_offset)
		if _has_enemy_at(units, diag, unit_owner):
			return true
	return can_advance


func _has_any_enemy(units: Dictionary, unit_owner: UnitData.Owner) -> bool:
	for cell_pos in units.keys():
		if units[cell_pos]["owner"] != unit_owner:
			return true
	return false


func _check_terminal(snapshot: BattleSnapshot, units: Dictionary, result: Dictionary) -> void:
	var llm_count: int = 0
	var human_count: int = 0
	for cell_pos in units.keys():
		if units[cell_pos]["owner"] == UnitData.Owner.LLM:
			llm_count += 1
		else:
			human_count += 1

	var llm_can_act: bool = _pick_acting_unit(units, UnitData.Owner.LLM) != NO_UNIT
	var human_can_act: bool = _pick_acting_unit(units, UnitData.Owner.HUMAN) != NO_UNIT
	var both_empty: bool = llm_count == 0 and human_count == 0
	var both_stuck: bool = not llm_can_act and not human_can_act
	var one_side_eliminated: bool = (llm_count == 0) != (human_count == 0)

	# Auto-score remaining units when the opposing side is fully eliminated
	if one_side_eliminated:
		if llm_count == 0:
			snapshot.human_escaped += human_count
			_clear_owner_units(units, UnitData.Owner.HUMAN)
		else:
			snapshot.llm_escaped += llm_count
			_clear_owner_units(units, UnitData.Owner.LLM)

	var llm_escaped: int = snapshot.llm_escaped
	var human_escaped: int = snapshot.human_escaped
	var llm_score: int = llm_escaped if one_side_eliminated else llm_count + llm_escaped
	var human_score: int = human_escaped if one_side_eliminated else human_count + human_escaped

	result["llm_remaining"] = 0 if one_side_eliminated else llm_count
	result["human_remaining"] = 0 if one_side_eliminated else human_count
	result["llm_escaped"] = llm_escaped
	result["human_escaped"] = human_escaped
	result["llm_score"] = llm_score
	result["human_score"] = human_score

	if both_empty or both_stuck or one_side_eliminated:
		result["is_finished"] = true
		if llm_score > human_score:
			result["winner"] = UnitData.Owner.LLM
			result["event"] += " | Game over by stalemate. LLM wins on score %d-%d." % [llm_score, human_score]
		elif human_score > llm_score:
			result["winner"] = UnitData.Owner.HUMAN
			result["event"] += " | Game over by stalemate. Human wins on score %d-%d." % [human_score, llm_score]
		else:
			result["winner"] = null
			result["event"] += " | Game over by stalemate. Tie on score %d-%d." % [llm_score, human_score]

func _clear_owner_units(units: Dictionary, unit_owner: UnitData.Owner) -> void:
	var to_remove: Array[Vector2i] = []
	for cell_pos in units.keys():
		if units[cell_pos]["owner"] == unit_owner:
			to_remove.append(cell_pos)
	for cell_pos in to_remove:
		units.erase(cell_pos)


func _increment_escaped(snapshot: BattleSnapshot, unit_owner: UnitData.Owner) -> void:
	if unit_owner == UnitData.Owner.LLM:
		snapshot.llm_escaped += 1
	else:
		snapshot.human_escaped += 1


func _owner_label(owner: UnitData.Owner) -> String:
	return "LLM" if owner == UnitData.Owner.LLM else "Human"
