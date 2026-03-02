class_name LlmFallback
extends RefCounted

func pick_random_placement(board: GameBoard, llm_shop: Shop) -> Dictionary:
	var affordable_types: Array[UnitData.UnitType] = []
	for unit_type in llm_shop.available_types:
		if llm_shop.can_afford(unit_type):
			affordable_types.append(unit_type)

	if affordable_types.is_empty():
		return {}

	var chosen_type: UnitData.UnitType = affordable_types[randi() % affordable_types.size()]
	var empty_positions: Array[Vector2i] = board.get_empty_positions_for(UnitData.Owner.LLM)
	if empty_positions.is_empty():
		return {}

	var chosen_pos: Vector2i = empty_positions[randi() % empty_positions.size()]
	return {
		"unit_type": chosen_type,
		"position": chosen_pos,
	}
