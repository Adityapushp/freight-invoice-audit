import re
from collections import Counter
from freight_audit import config as C
from freight_audit.generator import generate

def test_volume_and_id_conventions(starter):
    t, gt = starter
    assert len(t["carriers"]) == 10 and len(t["shipments"]) == 500 and len(t["freight_invoices"]) == 375
    assert t["carriers"][0]["carrier_id"] == "CAR-000001"
    assert t["rate_cards"][0]["rate_card_id"] == "RATE-CAR-000001-2026-01"
    assert t["shipments"][0]["shipment_id"] == "SHP-2026-000001"
    assert t["freight_invoices"][0]["invoice_id"] == "FINV-2026-000001"
    assert t["invoice_lines"][0]["line_id"] == "FLINE-FINV-2026-000001-01"
    assert re.fullmatch(r"FEX-2026-\d{6}", t["audit_exceptions"][0]["exception_id"])

def test_same_seed_identical_different_seed_differs():
    a = generate(1, 5, 100, 70); b = generate(1, 5, 100, 70); c = generate(2, 5, 100, 70)
    assert a[0]["freight_invoices"] == b[0]["freight_invoices"] and a[1] == b[1]
    assert a[0]["freight_invoices"] != c[0]["freight_invoices"]

def test_every_required_edge_case_present(starter):
    _, gt = starter
    seen = Counter(g["issue_type"] for g in gt)
    for k in ("UNKNOWN_SHIPMENT", "RATE_CARD_EXPIRED", "WEIGHT_TIER_MISAPPLIED", "SURCHARGE_DUPLICATED",
              "CREDIT_EXCEEDS_EXCEPTION", "DUPLICATE_BILLING", "INVALID_ACCESSORIAL", "DIM_WEIGHT_MISCALC"):
        assert seen[k] > 0, k

def test_baseline_has_boundary_weights_and_dim_weight_cases(starter):
    t, _ = starter
    auth = {w["shipment_id"]: w["weight_lb"] for w in t["weight_measurements"] if w["is_authoritative"]}
    assert any(int(w) in (49, 50, 51, 149, 150, 151, 499, 500, 501, 999, 1000, 1001) and w == int(w) for w in auth.values())
    lines = {l["invoice_id"]: l for l in t["invoice_lines"] if l["line_type"] == "BASE"}
    inv_ship = {i["invoice_id"]: i["shipment_id"] for i in t["freight_invoices"]}
    dim_billed = sum(1 for iid, l in lines.items() if inv_ship[iid] in auth and l["billed_weight_lb"] > auth[inv_ship[iid]] + 1)
    assert dim_billed > 20

def test_scale_is_parameterised():
    t, gt = generate(7, 3, 40, 30)
    assert len(t["shipments"]) == 40 and len(t["freight_invoices"]) == 30
