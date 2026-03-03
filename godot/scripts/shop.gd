class_name Shop
extends RefCounted
## Per-player shop and gold tracking. Pure data class with no scene awareness.

# --- Constants ---

const STARTING_GOLD: int = 3
const SHOP_SIZE: int = 3

# --- State ---

var available_types: Array[UnitData.UnitType]
var gold: int


func _init() -> void:
	gold = STARTING_GOLD
	available_types = []


static func create_randomized() -> Shop:
	var shop := Shop.new()
	var all_types: Array[UnitData.UnitType] = [
		UnitData.UnitType.A,
		UnitData.UnitType.B,
		UnitData.UnitType.C,
		UnitData.UnitType.D,
	]
	all_types.shuffle()
	shop.available_types.assign(all_types.slice(0, SHOP_SIZE))
	return shop


static func create_fixed(types: Array[UnitData.UnitType], starting_gold: int = STARTING_GOLD) -> Shop:
	var shop := Shop.new()
	shop.available_types.assign(types)
	shop.gold = maxi(0, starting_gold)
	return shop


func can_afford(type: UnitData.UnitType) -> bool:
	if type not in available_types:
		return false
	return gold >= UnitData.UNIT_COSTS[type]


func can_afford_any() -> bool:
	for type in available_types:
		if gold >= UnitData.UNIT_COSTS[type]:
			return true
	return false


func purchase(type: UnitData.UnitType) -> bool:
	if not can_afford(type):
		return false
	gold -= UnitData.UNIT_COSTS[type]
	return true


func get_purchase_summary() -> String:
	var parts: PackedStringArray = []
	for type in available_types:
		var label: String = UnitData.TYPE_LABELS[type]
		var cost: int = UnitData.UNIT_COSTS[type]
		parts.append("%s(%dg)" % [label, cost])
	return "%s | Gold: %d" % [", ".join(parts), gold]
