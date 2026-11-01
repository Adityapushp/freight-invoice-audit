from freight_audit.audit import evaluate, audit_invoices
from freight_audit import config as C

def test_detection_matches_ground_truth(starter):
    t, gt = starter
    ev = evaluate(t, gt)
    assert ev["overall_detection"]["f1"] >= 0.99
    for typ in C.INJECTED_INVOICE_ISSUES:
        assert ev["per_issue_type"][typ]["recall"] == 1.0, typ
        assert ev["per_issue_type"][typ]["precision"] == 1.0, typ
    assert ev["credit_exceeds_detection"]["f1"] == 1.0

def test_exceptions_explain_line_level_variance(starter):
    t, gt = starter
    assert ev_rate(evaluate(t, gt)) == 1.0
    for e in t["audit_exceptions"]:
        assert e["explanation"] and e["variance_amount"] == e["billed_amount"] - e["expected_amount"]

def ev_rate(ev): return ev["variance_explained"]["rate"]

def test_clean_invoices_raise_no_exceptions(starter):
    t, gt = starter
    clean = {g["entity_id"] for g in gt if g["entity_type"] == "INVOICE" and g["issue_type"] == "NONE"}
    assert not clean & {e["invoice_id"] for e in audit_invoices(t)}

def test_auditor_never_needs_ground_truth():
    import inspect, freight_audit.audit as a
    assert "ground_truth" not in inspect.getsource(a.audit_invoices) and "gt" not in inspect.signature(a.audit_invoices).parameters
