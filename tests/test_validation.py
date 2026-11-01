import copy, os, sqlite3, tempfile
from freight_audit.validate import validate
from freight_audit.export import export_all, load_tables, load_ground_truth

def failed(t, gt):
    return set(validate(t, gt).summary()["failed"])

def test_starter_passes_all_checks(starter):
    t, gt = starter
    assert validate(t, gt).ok

# ---- negative tests: the validator must catch deliberate corruption ----
def test_detects_duplicate_primary_key(fresh):
    t, gt = fresh; t["carriers"].append(dict(t["carriers"][0]))
    assert "primary_key_uniqueness" in failed(t, gt)

def test_detects_unlabelled_orphan_fk(fresh):
    t, gt = fresh; t["shipments"][0]["lane_id"] = "LANE-9999"
    assert "foreign_key_integrity" in failed(t, gt)

def test_detects_bad_enum(fresh):
    t, gt = fresh; t["shipments"][0]["service"] = "TELEPORT"
    assert "enums_and_required" in failed(t, gt)

def test_detects_broken_total(fresh):
    t, gt = fresh; t["freight_invoices"][0]["total_amount"] += 1
    assert "arithmetic_reconciliation" in failed(t, gt)

def test_detects_illegal_lifecycle_jump(fresh):
    t, gt = fresh; t["invoice_events"][1]["to_status"] = "PAID"
    assert "lifecycle_transitions" in failed(t, gt)

def test_detects_date_reversal(fresh):
    t, gt = fresh; t["freight_invoices"][0]["invoice_date"] = t["shipments"][0]["ship_date"].replace(year=2020)
    assert "date_ordering" in failed(t, gt)

def test_detects_credit_over_exception(fresh):
    t, gt = fresh; t["credit_notes"][0]["credit_amount"] += 100
    assert "credit_reconciliation" in failed(t, gt)

def test_detects_ground_truth_leak_column(fresh):
    from freight_audit import schema as S
    S.BY_NAME["shipments"].fields.append(S.F("issue_type", "str"))
    try:
        assert "no_ground_truth_in_input_tables" in failed(*fresh)
    finally:
        S.BY_NAME["shipments"].fields.pop()

# ---- export round-trip, reproducibility, SQL seed ----
def test_export_roundtrip_and_checksums_stable(starter):
    t, gt = starter
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        m1 = export_all(t, gt, a, dict(seed=1, scale={}, command="x")); m2 = export_all(t, gt, b, dict(seed=1, scale={}, command="x"))
        assert m1["sha256"] == m2["sha256"]
        t2, gt2 = load_tables(a), load_ground_truth(a)
        assert validate(t2, gt2).ok
        assert len(t2["freight_invoices"]) == len(t["freight_invoices"])

def test_sql_seed_loads_and_matches_counts(starter):
    t, gt = starter
    with tempfile.TemporaryDirectory() as d:
        export_all(t, gt, d, dict(seed=1, scale={}, command="x"))
        con = sqlite3.connect(":memory:")
        con.executescript(open(os.path.join(d, "sql", "schema.sql")).read())
        con.executescript(open(os.path.join(d, "sql", "seed.sql")).read())
        assert con.execute("select count(*) from freight_invoices").fetchone()[0] == len(t["freight_invoices"])
        bad = con.execute("select count(*) from freight_invoices i left join shipments s using(shipment_id) where s.shipment_id is null").fetchone()[0]
        assert bad == sum(1 for g in gt if g["issue_type"] == "UNKNOWN_SHIPMENT")
