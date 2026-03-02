class_name BattleSnapshot
extends RefCounted

var units: Dictionary = {}
var llm_escaped: int = 0
var human_escaped: int = 0


static func from_board_snapshot(board_snapshot: Dictionary) -> BattleSnapshot:
	var snapshot := BattleSnapshot.new()
	snapshot.units = board_snapshot.duplicate(true)
	return snapshot


func to_dictionary_with_meta() -> Dictionary:
	var snapshot: Dictionary = units.duplicate(true)
	snapshot["__meta"] = {
		"llm_escaped": llm_escaped,
		"human_escaped": human_escaped,
	}
	return snapshot
