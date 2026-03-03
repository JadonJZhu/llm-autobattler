class_name UnitData
extends RefCounted
## Shared unit enums/constants used by game logic and UI.

enum UnitType { A, B, C, D }
enum Owner { LLM, HUMAN }

const TYPE_LABELS: Dictionary = {
	UnitType.A: "A",
	UnitType.B: "B",
	UnitType.C: "C",
	UnitType.D: "D",
}

const UNIT_COSTS: Dictionary = {
	UnitType.A: 1,
	UnitType.B: 1,
	UnitType.C: 1,
	UnitType.D: 2,
}

const OWNER_COLORS: Dictionary = {
	Owner.LLM: Color(0.9, 0.4, 0.3),
	Owner.HUMAN: Color(0.3, 0.5, 0.9),
}

const TYPE_COLORS: Dictionary = {
	UnitType.A: Color(0.2, 0.7, 0.4),    # Green
	UnitType.B: Color(0.6, 0.3, 0.8),    # Purple
	UnitType.C: Color(0.9, 0.65, 0.2),   # Amber
	UnitType.D: Color(0.85, 0.25, 0.35), # Crimson
}


static func type_from_string(s: String) -> UnitType:
	match s.to_upper():
		"A": return UnitType.A
		"B": return UnitType.B
		"C": return UnitType.C
		"D": return UnitType.D
		_:
			push_error("Unknown unit type string: %s" % s)
			return UnitType.A


static func cost_of(unit_type: UnitType) -> int:
	return UNIT_COSTS[unit_type]
