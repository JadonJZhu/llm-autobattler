class_name Shop
extends RefCounted
## Per-player shop and gold tracking. Pure data class with no scene awareness.

# --- Constants ---

const STARTING_GOLD: int = 3
const SHOP_SIZE: int = 3

# --- State ---

var available_types: Array[Unit.UnitType]
var gold: int


func _init() -> void:
	gold = STARTING_GOLD
	available_types = []


static func create_randomized() -> Shop:
	var shop := Shop.new()
	var all_types: Array[Unit.UnitType] = [
		Unit.UnitType.A,
		Unit.UnitType.B,
		Unit.UnitType.C,
		Unit.UnitType.D,
	]
	all_types.shuffle()
	shop.available_types.assign(all_types.slice(0, SHOP_SIZE))
	return shop


func can_afford(type: Unit.UnitType) -> bool:
	if type not in available_types:
		return false
	return gold >= Unit.UNIT_COSTS[type]


func can_afford_any() -> bool:
	for type in available_types:
		if gold >= Unit.UNIT_COSTS[type]:
			return true
	return false


func purchase(type: Unit.UnitType) -> bool:
	if not can_afford(type):
		return false
	gold -= Unit.UNIT_COSTS[type]
	return true


func get_purchase_summary() -> String:
	var parts: PackedStringArray = []
	for type in available_types:
		var label: String = Unit.TYPE_LABELS[type]
		var cost: int = Unit.UNIT_COSTS[type]
		parts.append("%s(%dg)" % [label, cost])
	return "%s | Gold: %d" % [", ".join(parts), gold]
