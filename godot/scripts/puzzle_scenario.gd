class_name PuzzleScenario
extends RefCounted
## Immutable-like data container for a scripted puzzle scenario.
## Opponent placements are consumed in order during prep turns.

var id: String = ""
var difficulty: int = 1

var llm_shop_types: Array[UnitData.UnitType] = []
var llm_gold: int = Shop.STARTING_GOLD

var opponent_shop_types: Array[UnitData.UnitType] = []
var opponent_gold: int = Shop.STARTING_GOLD

var opponent_placements: Array[Dictionary] = []
