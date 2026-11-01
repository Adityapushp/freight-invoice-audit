"""Dataset validation: PK uniqueness, FK integrity, enums/nulls, ID formats, date ordering, arithmetic,
lifecycle transitions, duplicates, credit reconciliation, ground-truth consistency and leakage."""
from collections import Counter, defaultdict
from decimal import Decimal
from . import config as C, schema as S, ids
from .audit import Index, audit_invoices, reconcile_credits

TOL = Decimal(C.TOLERANCE)
ZERO = Decimal("0.00")


class Report:
    def __init__(self):
        self.checks = []

    def add(self, name, errors, info=""):
        self.checks.append(dict(check=name, passed=not errors, failures=len(errors), examples=errors[:5], info=info))

    @property
    def ok(self):
        return all(c["passed"] for c in self.checks)

    def summary(self):
        return dict(passed=self.ok, checks=len(self.checks), failed=[c["check"] for c in self.checks if not c["passed"]], details=self.checks)


def validate(t, gt=None):
    R = Report()
    # 1. primary keys
    errs = []
    for tb in S.TABLES:
        c = Counter(r[tb.pk] for r in t[tb.name])
        errs += [f"{tb.name}.{tb.pk} duplicate {k}" for k, n in c.items() if n > 1]
    R.add("primary_key_uniqueness", errs)
    # 2. declared unique columns + composite uniques
    errs = []
    for tb in S.TABLES:
        for f in tb.fields:
            if f.unique and f.name != tb.pk:
                c = Counter(r[f.name] for r in t[tb.name])
                errs += [f"{tb.name}.{f.name} duplicate {k}" for k, n in c.items() if n > 1]
    for tbl, cols in [("rate_card_rates", ("rate_card_id", "lane_id", "service", "weight_tier")),
                      ("rate_card_accessorials", ("rate_card_id", "accessorial_code")),
                      ("shipment_accessorials", ("shipment_id", "accessorial_code")),
                      ("rate_cards", ("carrier_id", "version")), ("shipment_legs", ("shipment_id", "leg_seq")),
                      ("invoice_lines", ("invoice_id", "line_seq"))]:
        c = Counter(tuple(r[k] for k in cols) for r in t[tbl])
        errs += [f"{tbl} composite {cols} duplicate {k}" for k, n in c.items() if n > 1]
    R.add("unique_constraints", errs)
    # 3. id formats
    errs = [f"{tb.name}.{tb.pk}={r[tb.pk]}" for tb in S.TABLES for r in t[tb.name] if not ids.matches(tb.name, r[tb.pk])]
    R.add("id_format", errs)
    # 4. enums / required
    errs = []
    for tb in S.TABLES:
        for r in t[tb.name]:
            for f in tb.fields:
                v = r.get(f.name)
                if v is None and f.required and f.name != "from_status":
                    errs.append(f"{tb.name}.{f.name} null in {r[tb.pk]}")
                if v is not None and f.enum and v not in f.enum:
                    errs.append(f"{tb.name}.{f.name}={v!r} not allowed")
    R.add("enums_and_required", errs)
    # 5. foreign keys (invoice->shipment orphans are allowed ONLY if labelled UNKNOWN_SHIPMENT)
    gt_unknown = {g["entity_id"] for g in (gt or []) if g["entity_type"] == "INVOICE" and g["issue_type"] == "UNKNOWN_SHIPMENT"}
    errs, orphan_inv = [], set()
    for tb in S.TABLES:
        for f in tb.fields:
            if not f.fk:
                continue
            rt, rc = f.fk.split(".")
            keys = {r[rc] for r in t[rt]}
            for r in t[tb.name]:
                if r.get(f.name) is not None and r[f.name] not in keys:
                    if tb.name == "freight_invoices" and f.name == "shipment_id":
                        orphan_inv.add(r["invoice_id"])
                    else:
                        errs.append(f"{tb.name}.{f.name}={r[f.name]} missing in {rt}")
    if gt is not None:
        errs += [f"unlabelled orphan invoice {i}" for i in orphan_inv - gt_unknown]
        errs += [f"labelled UNKNOWN_SHIPMENT but not orphaned: {i}" for i in gt_unknown - orphan_inv]
    R.add("foreign_key_integrity", errs, info=f"{len(orphan_inv)} intentional orphan invoice(s) (UNKNOWN_SHIPMENT)")
    # 6. date ordering
    errs = []
    ship = {s["shipment_id"]: s for s in t["shipments"]}
    for c in t["rate_cards"]:
        if c["effective_from"] > c["effective_to"]:
            errs.append(f"{c['rate_card_id']} effective dates reversed")
    for tb_, a, b in [("shipment_legs", "departed_at", "arrived_at")]:
        errs += [f"{r['leg_id']} {a}>{b}" for r in t[tb_] if r[a] > r[b]]
    last_leg = {}
    for l in t["shipment_legs"]:
        if l["leg_seq"] >= last_leg.get(l["shipment_id"], (0, None))[0]:
            last_leg[l["shipment_id"]] = (l["leg_seq"], l["arrived_at"])
    for s in t["shipments"]:
        if s["delivered_at"] != last_leg[s["shipment_id"]][1]:
            errs.append(f"{s['shipment_id']} delivered_at != last leg arrival")
        if s["delivered_at"].date() < s["ship_date"]:
            errs.append(f"{s['shipment_id']} delivered before shipped")
    for i in t["freight_invoices"]:
        s = ship.get(i["shipment_id"])
        if s and i["invoice_date"] < s["delivered_at"].date():
            errs.append(f"{i['invoice_id']} invoiced before delivery")
        if i["due_date"] < i["invoice_date"]:
            errs.append(f"{i['invoice_id']} due before invoice")
    inv = {i["invoice_id"]: i for i in t["freight_invoices"]}
    for e in t["audit_exceptions"]:
        if e["detected_at"].date() < inv[e["invoice_id"]]["invoice_date"]:
            errs.append(f"{e['exception_id']} detected before invoice date")
    R.add("date_ordering", errs)
    # 7. arithmetic reconciliation
    errs = []
    lines = defaultdict(list)
    for l in t["invoice_lines"]:
        lines[l["invoice_id"]].append(l)
    for i in t["freight_invoices"]:
        ls = lines[i["invoice_id"]]
        parts = {ty: sum((l["amount"] for l in ls if l["line_type"] == ty), ZERO) for ty in ("BASE", "FUEL", "ACCESSORIAL")}
        if (parts["BASE"], parts["FUEL"], parts["ACCESSORIAL"]) != (i["base_amount"], i["fuel_amount"], i["accessorial_amount"]):
            errs.append(f"{i['invoice_id']} subtotals != lines")
        if i["total_amount"] != sum(parts.values(), ZERO):
            errs.append(f"{i['invoice_id']} total != sum(lines)")
        seqs = sorted(l["line_seq"] for l in ls)
        if seqs != list(range(1, len(ls) + 1)):
            errs.append(f"{i['invoice_id']} line_seq not contiguous")
        for l in ls:
            if (l["line_type"] == "ACCESSORIAL") != (l["accessorial_code"] is not None):
                errs.append(f"{l['line_id']} accessorial_code/line_type mismatch")
    for e in t["audit_exceptions"]:
        if e["variance_amount"] != e["billed_amount"] - e["expected_amount"]:
            errs.append(f"{e['exception_id']} variance != billed - expected")
    R.add("arithmetic_reconciliation", errs)
    # 8. lifecycle transitions + chronology + current status
    errs = []
    for ev_tbl, fk, trans, parent, ptbl in [("invoice_events", "invoice_id", C.INVOICE_TRANSITIONS, "freight_invoices", "invoice_id"),
                                           ("exception_events", "exception_id", C.EXCEPTION_TRANSITIONS, "audit_exceptions", "exception_id"),
                                           ("credit_note_events", "credit_note_id", C.CREDIT_TRANSITIONS, "credit_notes", "credit_note_id")]:
        chain = defaultdict(list)
        for e in sorted(t[ev_tbl], key=lambda e: e["event_id"]):
            chain[e[fk]].append(e)
        for pid, evs in chain.items():
            prev, prev_t = None, None
            for e in evs:
                if e["from_status"] != prev:
                    errs.append(f"{ev_tbl} {e['event_id']} from_status {e['from_status']} != previous {prev}")
                if e["to_status"] not in trans.get(prev, []):
                    errs.append(f"{ev_tbl} {e['event_id']} illegal {prev}->{e['to_status']}")
                if prev_t and e["event_at"] < prev_t:
                    errs.append(f"{ev_tbl} {e['event_id']} out of chronological order")
                prev, prev_t = e["to_status"], e["event_at"]
        cur = {r[ptbl]: r["current_status"] for r in t[parent]}
        for pid, st in cur.items():
            if not chain.get(pid) or chain[pid][-1]["to_status"] != st:
                errs.append(f"{parent} {pid} current_status != last event")
    cn_x = {c["exception_id"]: c for c in t["credit_notes"]}
    for e in t["audit_exceptions"]:   # credited only with an applied credit note
        if e["current_status"] == "CREDITED" and cn_x.get(e["exception_id"], {}).get("current_status") != "APPLIED":
            errs.append(f"{e['exception_id']} CREDITED without APPLIED credit note")
    xstat = {e["exception_id"]: e["current_status"] for e in t["audit_exceptions"]}
    for c in t["credit_notes"]:    # applied credit <=> exception CREDITED
        if c["current_status"] == "APPLIED" and xstat[c["exception_id"]] != "CREDITED":
            errs.append(f"{c['credit_note_id']} APPLIED but exception not CREDITED")
    R.add("lifecycle_transitions", errs)
    # 9. duplicate bills
    pairs = Counter((i["carrier_id"], i["shipment_id"]) for i in t["freight_invoices"] if i["invoice_id"] not in orphan_inv)
    dup_pairs = {k for k, n in pairs.items() if n > 1}
    errs = []
    if gt is not None:
        gt_dup = {g["entity_id"] for g in gt if g["issue_type"] == "DUPLICATE_BILLING"}
        flagged = {e["invoice_id"] for e in t["audit_exceptions"] if e["exception_type"] == "DUPLICATE_BILLING"}
        if flagged != gt_dup:
            errs.append(f"duplicate-bill detections differ from labels (missed {len(gt_dup - flagged)}, extra {len(flagged - gt_dup)})")
        if len(gt_dup) != sum(n - 1 for n in pairs.values() if n > 1):
            errs.append("labelled duplicates != repeat (carrier, shipment) pairs")
    R.add("duplicate_detection", errs, info=f"{len(dup_pairs)} shipment(s) billed more than once")
    # 10. credits reconcile to approved disputes
    errs = []
    xs = {e["exception_id"]: e for e in t["audit_exceptions"]}
    approved = {ev["exception_id"] for ev in t["exception_events"] if ev["to_status"] == "APPROVED"}
    for c in t["credit_notes"]:
        if c["exception_id"] not in approved:
            errs.append(f"{c['credit_note_id']} settles exception without APPROVED event")
        x = xs[c["exception_id"]]
        if c["invoice_id"] != x["invoice_id"]:
            errs.append(f"{c['credit_note_id']} invoice mismatch")
    exceeding = set(reconcile_credits(t))
    if gt is not None:
        want = {g["entity_id"] for g in gt if g["issue_type"] == "CREDIT_EXCEEDS_EXCEPTION"}
        errs += [f"credit exceeds exception but unlabelled: {c}" for c in exceeding - want]
        errs += [f"labelled CREDIT_EXCEEDS but does not exceed: {c}" for c in want - exceeding]
    R.add("credit_reconciliation", errs, info=f"{len(exceeding)} credit note(s) exceed their exception amount (labelled edge case)")
    # 11. ground-truth consistency
    errs = []
    if gt is not None:
        gi = {g["entity_id"] for g in gt if g["entity_type"] == "INVOICE"}
        if gi != set(inv):
            errs.append("ground truth invoice set != invoice table")
        for g in gt:
            if g["issue_type"] not in C.GT_ISSUE_TYPES:
                errs.append(f"unknown issue_type {g['issue_type']}")
        cov = Counter(g["issue_type"] for g in gt)
        errs += [f"no examples of {k}" for k in C.GT_ISSUE_TYPES[1:] if cov[k] == 0]
    R.add("ground_truth_consistency_and_coverage", errs)
    # 12. expected charges reproducible: auditor output == stored exceptions
    try:
        again = audit_invoices(t)
        stored = sorted((e["invoice_id"], e["line_id"] or "", e["exception_type"], str(e["variance_amount"])) for e in t["audit_exceptions"])
        fresh = sorted((e["invoice_id"], e["line_id"] or "", e["exception_type"], str(e["variance_amount"])) for e in again)
        R.add("expected_charges_reproducible", [] if stored == fresh else ["stored exceptions differ from a fresh audit run"])
    except KeyError as ex:   # corrupted reference data: report instead of crashing
        R.add("expected_charges_reproducible", [f"auditor could not recompute expected charges (missing key {ex})"])
    # 13. no leakage of labels into input tables
    banned = {"issue_type", "ground_truth", "is_anomaly", "expected_decision", "anomaly", "label"}
    errs = [f"{tb.name}.{f.name}" for tb in S.TABLES for f in tb.fields if f.name in banned]
    R.add("no_ground_truth_in_input_tables", errs)
    # 14. delivery/weight sanity: one authoritative weight per shipment; delivered before invoicing
    errs = []
    auth = Counter(w["shipment_id"] for w in t["weight_measurements"] if w["is_authoritative"])
    errs += [f"{s} has {auth.get(s, 0)} authoritative weights" for s in ship if auth.get(s, 0) != 1]
    R.add("one_authoritative_weight_per_shipment", errs)
    return R
