extends GutTest


func _make_shop(types: Array[UnitData.UnitType], gold: int = 3) -> Shop:
	var shop := Shop.new()
	shop.available_types = types
	shop.gold = gold
	return shop


# =============================================================================
# A. Purchase Logic
# =============================================================================

func test_purchase_deducts_gold():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A, UnitData.UnitType.B, UnitData.UnitType.C]
	var shop := _make_shop(types, 3)
	shop.purchase(UnitData.UnitType.A)
	assert_eq(shop.gold, 2, "Purchasing A (cost 1) should deduct 1 gold")


func test_purchase_d_deducts_2_gold():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.D]
	var shop := _make_shop(types, 3)
	shop.purchase(UnitData.UnitType.D)
	assert_eq(shop.gold, 1, "Purchasing D (cost 2) should deduct 2 gold")


func test_purchase_returns_true_on_success():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A]
	var shop := _make_shop(types, 3)
	assert_true(shop.purchase(UnitData.UnitType.A), "Purchase should return true on success")


func test_purchase_when_broke_returns_false():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A]
	var shop := _make_shop(types, 0)
	assert_false(shop.purchase(UnitData.UnitType.A), "Purchase should fail with 0 gold")
	assert_eq(shop.gold, 0, "Gold should remain unchanged on failed purchase")


func test_purchase_unavailable_type_returns_false():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A, UnitData.UnitType.B]
	var shop := _make_shop(types, 3)
	assert_false(shop.purchase(UnitData.UnitType.C), "Purchasing unavailable type should fail")


# =============================================================================
# B. can_afford
# =============================================================================

func test_can_afford_with_sufficient_gold():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A]
	var shop := _make_shop(types, 1)
	assert_true(shop.can_afford(UnitData.UnitType.A))


func test_can_afford_with_insufficient_gold():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.D]
	var shop := _make_shop(types, 1)
	assert_false(shop.can_afford(UnitData.UnitType.D), "D costs 2, only 1 gold available")


func test_can_afford_with_missing_type():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A]
	var shop := _make_shop(types, 3)
	assert_false(shop.can_afford(UnitData.UnitType.C), "Type not in available_types should not be affordable")


# =============================================================================
# C. can_afford_any
# =============================================================================

func test_can_afford_any_with_gold():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A]
	var shop := _make_shop(types, 1)
	assert_true(shop.can_afford_any())


func test_can_afford_any_when_broke():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A]
	var shop := _make_shop(types, 0)
	assert_false(shop.can_afford_any())


func test_can_afford_any_only_d_with_1_gold():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.D]
	var shop := _make_shop(types, 1)
	assert_false(shop.can_afford_any(), "D costs 2 but only 1 gold available")


# =============================================================================
# D. Edge Cases
# =============================================================================

func test_starting_gold_is_3():
	var shop := Shop.new()
	assert_eq(shop.gold, 3, "Default starting gold should be 3")


func test_purchase_summary_format():
	var types: Array[UnitData.UnitType] = [UnitData.UnitType.A, UnitData.UnitType.B, UnitData.UnitType.D]
	var shop := _make_shop(types, 2)
	var summary := shop.get_purchase_summary()
	assert_string_contains(summary, "A(1g)")
	assert_string_contains(summary, "B(1g)")
	assert_string_contains(summary, "D(2g)")
	assert_string_contains(summary, "Gold: 2")
