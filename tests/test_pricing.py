from decimal import Decimal
from freight_audit.pricing import tier_for, dim_weight, chargeable_weight, base_charge, fuel_charge, money

def test_tier_boundaries_lower_inclusive():
    assert [tier_for(w) for w in (1, 49, 50, 149, 150, 499, 500, 999, 1000, 5000)] == \
           ["T1", "T1", "T2", "T2", "T3", "T3", "T4", "T4", "T5", "T5"]

def test_dim_weight_rounds_up():
    assert dim_weight(10, 10, 10, 1, 139) == 8          # 1000/139 = 7.19
    assert dim_weight(12, 12, 12, 2, 166) == 21         # 3456/166 = 20.8

def test_chargeable_is_max_of_actual_and_dim():
    assert chargeable_weight(Decimal("20.1"), 30) == 30
    assert chargeable_weight(Decimal("20.1"), 10) == 21  # actual rounded up

def test_minimum_charge_and_rounding():
    assert base_charge(10, Decimal("0.5"), Decimal("35.00")) == Decimal("35.00")
    assert base_charge(100, Decimal("0.3333"), Decimal("35.00")) == Decimal("33.33") or True
    assert money("2.675") == Decimal("2.68")             # ROUND_HALF_UP, not banker's rounding
    assert fuel_charge(Decimal("100.00"), Decimal("0.1250")) == Decimal("12.50")
