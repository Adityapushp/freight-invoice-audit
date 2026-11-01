"""Independent invoice auditor + evaluation metrics.
Reads ONLY the input tables (never ground truth). Ground truth is used solely in evaluate()."""
from collections import defaultdict
from decimal import Decimal
from . import config as C
from .pricing import D, money, dim_weight, chargeable_weight, tier_for, base_charge, fuel_charge

TOL = Decimal(C.TOLERANCE)
ZERO = Decimal("0.00")


class Index:
    """Lookup structures built from table rows (native-typed)."""
    def __init__(self, t):
        self.shipments = {r["shipment_id"]: r for r in t["shipments"]}
        self.cards = {r["rate_card_id"]: r for r in t["rate_cards"]}
        self.cards_by_carrier = defaultdict(list)
        for r in t["rate_cards"]:
            self.cards_by_carrier[r["carrier_id"]].append(r)
        self.rates = {(r["rate_card_id"], r["lane_id"], r["service"], r["weight_tier"]): r["rate_per_lb"]
                      for r in t["rate_card_rates"]}
        self.card_acc = {(r["rate_card_id"], r["accessorial_code"]): r["amount"] for r in t["rate_card_accessorials"]}
        self.ship_acc = defaultdict(set)
        for r in t["shipment_accessorials"]:
            self.ship_acc[r["shipment_id"]].add(r["accessorial_code"])
        self.weight = {r["shipment_id"]: r["weight_lb"] for r in t["weight_measurements"] if r["is_authoritative"]}
        self.lines = defaultdict(list)
        for r in t["invoice_lines"]:
            self.lines[r["invoice_id"]].append(r)

    def card_at(self, carrier_id, d):
        for c in self.cards_by_carrier.get(carrier_id, []):
            if c["effective_from"] <= d <= c["effective_to"]:
                return c
        return None


def expected_charges(ix, ship, card):
    """Expected freight for a shipment under a rate card (the documented rule set)."""
    actual = ix.weight[ship["shipment_id"]]
    dim = dim_weight(ship["length_in"], ship["width_in"], ship["height_in"], ship["pieces"], card["dim_divisor"])
    wt = chargeable_weight(actual, dim)
    tier = tier_for(wt)
    rate = ix.rates[(card["rate_card_id"], ship["lane_id"], ship["service"], tier)]
    base = base_charge(wt, rate, card["min_charge"])
    fuel = fuel_charge(base, card["fuel_surcharge_rate"])
    acc = {code: ix.card_acc[(card["rate_card_id"], code)]
           for code in sorted(ix.ship_acc.get(ship["shipment_id"], ())) if (card["rate_card_id"], code) in ix.card_acc}
    return dict(actual=actual, dim=dim, weight=wt, tier=tier, rate=rate, base=base, fuel=fuel,
                accessorials=acc, total=base + fuel + sum(acc.values(), ZERO))


def _exc(inv, line, typ, billed, expected, why):
    billed, expected = money(billed), money(expected)
    return dict(invoice_id=inv["invoice_id"], line_id=line["line_id"] if line else None, exception_type=typ,
                billed_amount=billed, expected_amount=expected, variance_amount=billed - expected, explanation=why)


def _audit_one(inv, lines, ix, seen):
    out = []
    ship = ix.shipments.get(inv["shipment_id"])
    if ship is None:
        return [_exc(inv, None, "UNKNOWN_SHIPMENT", inv["total_amount"], 0,
                     f"Invoice references shipment {inv['shipment_id']} which does not exist; whole invoice unsupported.")]
    key = (inv["carrier_id"], inv["shipment_id"])
    if key in seen:
        return [_exc(inv, None, "DUPLICATE_BILLING", inv["total_amount"], 0,
                     f"Shipment {inv['shipment_id']} already billed on {seen[key]}; this invoice is a repeat bill.")]
    seen[key] = inv["invoice_id"]
    card = ix.card_at(ship["carrier_id"], ship["ship_date"])
    if card is None:
        return [_exc(inv, None, "RATE_MISMATCH", inv["total_amount"], 0, "No rate card effective on ship date.")]
    exp = expected_charges(ix, ship, card)
    applied = ix.cards.get(inv["rate_card_id_applied"])
    expired = applied is None or not (applied["effective_from"] <= ship["ship_date"] <= applied["effective_to"])

    base_flagged = False
    base_lines = [l for l in lines if l["line_type"] == "BASE"]
    for i, l in enumerate(base_lines):
        expected = exp["base"] if i == 0 else ZERO
        v = l["amount"] - expected
        if abs(v) <= TOL:
            continue
        base_flagged = True
        if i > 0:
            out.append(_exc(inv, l, "RATE_MISMATCH", l["amount"], 0, "Second base-freight line for the same shipment."))
        elif expired:
            out.append(_exc(inv, l, "RATE_CARD_EXPIRED", l["amount"], expected,
                            f"Priced with {inv['rate_card_id_applied']} (effective {applied['effective_from']}..{applied['effective_to']}) "
                            f"but shipment shipped {ship['ship_date']}; {card['rate_card_id']} applies."))
        elif l["billed_weight_lb"] != exp["weight"]:
            out.append(_exc(inv, l, "DIM_WEIGHT_MISCALC", l["amount"], expected,
                            f"Billed {l['billed_weight_lb']} lb vs expected {exp['weight']} lb (actual {exp['actual']} lb, "
                            f"dim {exp['dim']} lb at divisor {card['dim_divisor']})."))
        elif l["weight_tier"] != exp["tier"]:
            out.append(_exc(inv, l, "WEIGHT_TIER_MISAPPLIED", l["amount"], expected,
                            f"Weight {exp['weight']} lb belongs to tier {exp['tier']} (rate {exp['rate']}/lb) but billed at tier {l['weight_tier']} ({l['unit_rate']}/lb)."))
        else:
            out.append(_exc(inv, l, "RATE_MISMATCH", l["amount"], expected,
                            f"Unit rate {l['unit_rate']} vs contract {exp['rate']} for tier {exp['tier']}."))

    for i, l in enumerate(sorted([l for l in lines if l["line_type"] == "FUEL"], key=lambda x: x["line_seq"])):
        if i > 0:
            out.append(_exc(inv, l, "SURCHARGE_DUPLICATED", l["amount"], 0,
                            "Additional fuel surcharge line; fuel is billed once per shipment."))
            continue
        v = l["amount"] - exp["fuel"]
        if abs(v) <= TOL:
            continue
        if D(l["unit_rate"]) != D(card["fuel_surcharge_rate"]):
            typ = "RATE_CARD_EXPIRED" if expired else "FUEL_RATE_WRONG"
            why = (f"Fuel billed at {l['unit_rate']} vs contracted {card['fuel_surcharge_rate']}"
                   + (f" (expired card {inv['rate_card_id_applied']})." if expired else "."))
        else:
            typ = "FUEL_ON_BASE_VARIANCE"
            why = f"Fuel recalculated on expected base {exp['base']} at {card['fuel_surcharge_rate']}; follows base-line variance."
        out.append(_exc(inv, l, typ, l["amount"], exp["fuel"], why))

    used = set()
    for l in sorted([l for l in lines if l["line_type"] == "ACCESSORIAL"], key=lambda x: x["line_seq"]):
        code = l["accessorial_code"]
        contracted = exp["accessorials"].get(code)
        if contracted is None or code in used:
            reason = ("no delivery-record event for this accessorial" if code not in ix.ship_acc.get(ship["shipment_id"], ())
                      else "accessorial not contracted on rate card" if contracted is None else "accessorial billed twice")
            out.append(_exc(inv, l, "INVALID_ACCESSORIAL", l["amount"], 0, f"{code}: {reason}."))
        elif abs(l["amount"] - contracted) > TOL:
            out.append(_exc(inv, l, "ACCESSORIAL_RATE_MISMATCH", l["amount"], contracted,
                            f"{code} billed {l['amount']} vs contracted {contracted}."))
        used.add(code)
    return out


def audit_invoices(t, ix=None):
    ix = ix or Index(t)
    out, seen = [], {}
    for inv in sorted(t["freight_invoices"], key=lambda r: (r["invoice_date"], r["invoice_id"])):
        lines = sorted(ix.lines.get(inv["invoice_id"], []), key=lambda l: l["line_seq"])
        out += _audit_one(inv, lines, ix, seen)
    return out


def root_cause(types):
    for p in C.ROOT_PRIORITY:
        if p in types:
            return p
    return "FUEL_ON_BASE_VARIANCE" if types else "NONE"


def reconcile_credits(t):
    """Credit notes whose amount exceeds the variance of the exception they settle."""
    exc = {e["exception_id"]: e for e in t["audit_exceptions"]}
    return sorted(cn["credit_note_id"] for cn in t["credit_notes"]
                  if cn["credit_amount"] > exc[cn["exception_id"]]["variance_amount"] + TOL)


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return dict(tp=tp, fp=fp, fn=fn, precision=round(p, 4), recall=round(r, 4),
                f1=round(2 * p * r / (p + r), 4) if p + r else 0.0)


def evaluate(t, gt):
    """Compare a fresh audit run against ground truth."""
    pred = audit_invoices(t)
    by_inv = defaultdict(list)
    for e in pred:
        by_inv[e["invoice_id"]].append(e)
    pred_root = {i["invoice_id"]: root_cause({e["exception_type"] for e in by_inv.get(i["invoice_id"], [])})
                 for i in t["freight_invoices"]}
    gt_inv = {r["entity_id"]: r for r in gt if r["entity_type"] == "INVOICE"}
    per_type = {}
    for typ in C.INJECTED_INVOICE_ISSUES:
        tp = sum(1 for i, g in gt_inv.items() if g["issue_type"] == typ and pred_root[i] == typ)
        fp = sum(1 for i, g in gt_inv.items() if g["issue_type"] != typ and pred_root[i] == typ)
        fn = sum(1 for i, g in gt_inv.items() if g["issue_type"] == typ and pred_root[i] != typ)
        per_type[typ] = _prf(tp, fp, fn)
    tp = sum(1 for i, g in gt_inv.items() if g["issue_type"] != "NONE" and pred_root[i] != "NONE")
    fp = sum(1 for i, g in gt_inv.items() if g["issue_type"] == "NONE" and pred_root[i] != "NONE")
    fn = sum(1 for i, g in gt_inv.items() if g["issue_type"] != "NONE" and pred_root[i] == "NONE")
    var_ok = var_n = 0
    for i, g in gt_inv.items():
        if g["issue_type"] == "NONE":
            continue
        var_n += 1
        pv = sum((e["variance_amount"] for e in by_inv.get(i, [])), ZERO)
        var_ok += abs(pv - g["expected_variance"]) <= TOL
    cn_gt = {r["entity_id"] for r in gt if r["entity_type"] == "CREDIT_NOTE" and r["issue_type"] == "CREDIT_EXCEEDS_EXCEPTION"}
    cn_pred = set(reconcile_credits(t))
    true_over = sum((g["expected_variance"] for g in gt_inv.values() if g["issue_type"] != "NONE"), ZERO)
    found = sum((e["variance_amount"] for e in pred), ZERO)
    applied = {cn["credit_note_id"] for cn in t["credit_notes"] if cn["current_status"] == "APPLIED"}
    credited = sum((cn["credit_amount"] for cn in t["credit_notes"] if cn["credit_note_id"] in applied), ZERO)
    return {
        "invoices": len(gt_inv), "anomalous_invoices": sum(1 for g in gt_inv.values() if g["issue_type"] != "NONE"),
        "overall_detection": _prf(tp, fp, fn),
        "per_issue_type": per_type,
        "credit_exceeds_detection": _prf(len(cn_gt & cn_pred), len(cn_pred - cn_gt), len(cn_gt - cn_pred)),
        "variance_explained": {"invoices_with_matching_variance": var_ok, "of": var_n,
                               "rate": round(var_ok / var_n, 4) if var_n else 1.0},
        "dollars": {"true_overbilling_usd": str(true_over), "flagged_variance_usd": str(found),
                    "credits_applied_usd": str(credited)},
    }
