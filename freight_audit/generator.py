"""Deterministic synthetic data generator.
Order: master data -> shipments/delivery records -> valid invoices -> injected anomalies -> audit -> workflow events -> credits.
Outcomes (exceptions, credits) are DERIVED from the documented rules by running the auditor, never assigned independently."""
import hashlib
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from . import config as C, ids
from .audit import Index, expected_charges, audit_invoices, root_cause
from .pricing import D, money, dim_weight, chargeable_weight, tier_for, tier_index, base_charge, fuel_charge

ADJ = ["Apex", "Blue", "Cardinal", "Delta", "Eagle", "Falcon", "Granite", "Harbor", "Iron", "Juniper"]
NOUN = ["Line", "Haul", "Cargo", "Express", "Route", "Link", "Carriers", "Transit", "Logistics", "Move"]
HUBS = ["MEM", "IND", "DFW", "ATL", "DEN", "CVG", "ORD", "KCI"]
CUTOFF = datetime.combine(C.AS_OF, time(23, 59))


def stream(seed, name):
    """Independent, reproducible RNG per generation stage (changing one stage never shifts another)."""
    return random.Random(int.from_bytes(hashlib.sha256(f"{seed}:{name}".encode()).digest()[:8], "big"))


def q(x, places):
    return D(x).quantize(Decimal(1).scaleb(-places))


def at(d, h=9, m=0):
    return datetime.combine(d, time(h, m))


# ------------------------------------------------------------------ master data
def build_master(seed, n_carriers):
    r = stream(seed, "master")
    t = defaultdict(list)
    # lanes
    n = 0
    for o, (ox, oy) in C.REGIONS.items():
        for dd, (dx, dy) in C.REGIONS.items():
            n += 1
            dist = max(150, int(math.hypot(ox - dx, oy - dy)))
            t["lanes"].append(dict(lane_id=ids.lane_id(n), origin_region=o, dest_region=dd, distance_miles=dist))
    lane_dist = {l["lane_id"]: l["distance_miles"] for l in t["lanes"]}
    for code, desc, trig, amt, ev in C.ACCESSORIALS:
        t["accessorials"].append(dict(accessorial_code=code, description=desc, trigger_event=trig,
                                      standard_amount=money(amt), requires_evidence=ev))
    used_scac = set()
    split = set(r.sample(range(1, n_carriers + 1), max(1, round(C.SPLIT_CARD_FRACTION * n_carriers))))
    rl = rca = 0
    meta = {}
    lane_ids = [l["lane_id"] for l in t["lanes"]]
    for i in range(1, n_carriers + 1):
        cid = ids.carrier_id(i)
        name = f"{ADJ[(i - 1) % 10]} {NOUN[((i - 1) // 10) % 10]} Freight" + (f" {(i - 1) // 100 + 1}" if i > 100 else "")
        while True:
            scac = "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4))
            if scac not in used_scac:
                used_scac.add(scac); break
        onboarded = date(2020, 1, 1) + timedelta(days=r.randint(0, 2000))
        t["carriers"].append(dict(carrier_id=cid, carrier_name=name, scac_code=scac,
                                  service_mode=r.choice(["LTL", "PARCEL", "TL"]), onboarded_date=onboarded, status="ACTIVE"))
        lanes = sorted(r.sample(lane_ids, min(len(lane_ids), r.randint(12, 24))))
        services = ["GROUND"] + r.sample(["EXPRESS", "ECONOMY"], r.randint(1, 2))
        services = [s for s in C.SERVICES if s in services]
        factor = r.uniform(0.85, 1.2)
        divisor = r.choice([139, 166])
        min_charge = q(r.choice([35, 40, 45, 50, 60]), 2)
        fuel1 = q(r.uniform(0.08, 0.18), 4)
        codes = sorted(r.sample([a[0] for a in C.ACCESSORIALS], r.randint(4, 7)))
        acc_amt = {c: money(D(next(a[3] for a in C.ACCESSORIALS if a[0] == c)) * D(round(r.uniform(0.8, 1.4), 3))) for c in codes}
        versions = [(1, C.SHIP_START.replace(month=1, day=1), date(2026, 6, 30) if i in split else C.YEAR_END, fuel1, D(1))]
        if i in split:
            disc = D(round(r.uniform(0.90, 0.97), 4))
            versions.append((2, C.RENEWAL_DATE, C.YEAR_END, q(max(D("0.05"), fuel1 + D(round(r.uniform(-0.02, 0.01), 4))), 4), disc))
        meta[cid] = dict(lanes=lanes, services=services)
        for v, eff_from, eff_to, fuel, disc in versions:
            rid = ids.rate_card_id(cid, v)
            t["rate_cards"].append(dict(rate_card_id=rid, carrier_id=cid, version=v, effective_from=eff_from, effective_to=eff_to,
                                        fuel_surcharge_rate=fuel, dim_divisor=divisor, min_charge=min_charge, currency="USD",
                                        status="EXPIRED" if eff_to < C.AS_OF else "ACTIVE"))
            for lane in lanes:
                for svc in services:
                    for tier, lo, hi in C.TIERS:
                        rl += 1
                        base = (0.10 + 0.00035 * lane_dist[lane]) * C.SERVICE_MULT[svc] * C.TIER_MULT[tier] * factor
                        t["rate_card_rates"].append(dict(rate_line_id=ids.rate_line_id(rl), rate_card_id=rid, lane_id=lane,
                                                         service=svc, weight_tier=tier, min_weight_lb=lo, max_weight_lb=hi,
                                                         rate_per_lb=q(D(round(base, 6)) * disc, 4)))
            for c in codes:
                rca += 1
                t["rate_card_accessorials"].append(dict(rca_id=ids.rca_id(rca), rate_card_id=rid, accessorial_code=c, amount=acc_amt[c]))
    return t, meta, lane_dist


# ------------------------------------------------------------------ shipments and delivery records
def build_shipments(seed, t, meta, lane_dist, n_ship):
    r = stream(seed, "shipments")
    card1 = {c["carrier_id"]: c for c in t["rate_cards"] if c["version"] == 1}
    carriers = [c["carrier_id"] for c in t["carriers"]]
    span = (C.SHIP_END - C.SHIP_START).days
    for n in range(1, n_ship + 1):
        sid = ids.shipment_id(n)
        cid = r.choice(carriers)
        lane = r.choice(meta[cid]["lanes"])
        svcs = meta[cid]["services"]
        svc = r.choices(svcs, [C.SERVICE_WEIGHTS[s] for s in svcs])[0]
        ship_date = C.SHIP_START + timedelta(days=r.randint(0, span))
        div = card1[cid]["dim_divisor"]
        if r.random() < C.BOUNDARY_WEIGHT_PROB:            # boundary case: exactly on / next to a tier edge
            target = r.choice(C.TIER_BOUNDARIES) + r.choice([-1, 0, 1])
            pieces = 1
            L = W = H = max(4, int((target * 0.6 * div) ** (1 / 3)))
            actual = D(target)
        else:
            pieces = r.choices([1, 2, 3, 4, 6], [55, 20, 12, 7, 6])[0]
            L, W, H = (r.randint(6, 48) for _ in range(3))
            dimf = L * W * H * pieces / div
            f = r.uniform(0.35, 0.95) if r.random() < C.BULKY_PROB else r.uniform(1.05, 3.5)
            actual = q(max(1.0, min(6000.0, dimf * f)), 1)
        dist = lane_dist[lane]
        ground = 1 + math.ceil(dist / 600)
        days = {"GROUND": ground, "EXPRESS": max(1, math.ceil(dist / 1200)), "ECONOMY": ground + 2}[svc]
        pickup = at(ship_date, r.randint(8, 16), r.choice([0, 15, 30, 45]))
        delivered = at(ship_date + timedelta(days=days), r.randint(9, 18), r.choice([0, 15, 30, 45]))
        t["shipments"].append(dict(shipment_id=sid, carrier_id=cid, lane_id=lane, service=svc, ship_date=ship_date,
                                   delivered_at=delivered, pieces=pieces, length_in=L, width_in=W, height_in=H, status="DELIVERED"))
        # legs (last leg arrival == delivery record)
        lane_row = next(l for l in t["lanes"] if l["lane_id"] == lane) if False else None
        nlegs = 1 if dist < 400 else r.choice([1, 2]) if dist < 1500 else r.choice([2, 3])
        o, d_ = t["lanes"][int(lane[-4:]) - 1]["origin_region"], t["lanes"][int(lane[-4:]) - 1]["dest_region"]
        nodes = [f"ORG-{o}"] + [f"HUB-{r.choice(HUBS)}" for _ in range(nlegs - 1)] + [f"DST-{d_}"]
        seg = (delivered - pickup) / nlegs
        for k in range(1, nlegs + 1):
            t["shipment_legs"].append(dict(leg_id=ids.leg_id(sid, k), shipment_id=sid, leg_seq=k, from_node=nodes[k - 1], to_node=nodes[k],
                                           departed_at=pickup + seg * (k - 1),
                                           arrived_at=delivered if k == nlegs else pickup + seg * k, leg_status="COMPLETED"))
        # weights
        t["weight_measurements"] += [
            dict(measurement_id=ids.measurement_id(sid, 1), shipment_id=sid, source="SHIPPER_DECLARED",
                 weight_lb=q(actual * D(round(r.uniform(0.9, 1.1), 3)), 1), is_authoritative=False, measured_at=pickup - timedelta(hours=3)),
            dict(measurement_id=ids.measurement_id(sid, 2), shipment_id=sid, source="ORIGIN_SCALE",
                 weight_lb=actual, is_authoritative=True, measured_at=pickup - timedelta(hours=1))]
        if r.random() < 0.6:
            t["weight_measurements"].append(dict(measurement_id=ids.measurement_id(sid, 3), shipment_id=sid, source="CARRIER_REWEIGH",
                                                 weight_lb=q(actual * D(round(r.uniform(0.97, 1.06), 3)), 1),
                                                 is_authoritative=False, measured_at=pickup + timedelta(hours=3)))
        # accessorial events (delivery record)
        for code, p in C.ACC_PROB.items():
            if r.random() < p:
                ev = pickup + (delivered - pickup) * r.uniform(0.2, 1.0)
                t["shipment_accessorials"].append(dict(sa_id=ids.sa_id(sid, code), shipment_id=sid, accessorial_code=code,
                                                       event_at=ev.replace(microsecond=0), evidence_ref=f"EVD-{sid[-6:]}-{code[:3]}"))
    for leg in t["shipment_legs"]:   # whole-second timestamps keep exports stable
        leg["departed_at"] = leg["departed_at"].replace(microsecond=0)
        leg["arrived_at"] = leg["arrived_at"].replace(microsecond=0)


# ------------------------------------------------------------------ invoice construction
def build_lines(ix, ship, card, exp, issue, r):
    """Return (applied_card_id, line specs) for an invoice; None if the shipment cannot carry this anomaly."""
    cid, lane, svc = ship["carrier_id"], ship["lane_id"], ship["service"]
    applied, wt, tier, rate = card, exp["weight"], exp["tier"], exp["rate"]
    fuel_rate, min_charge = D(card["fuel_surcharge_rate"]), card["min_charge"]
    if issue == "RATE_CARD_EXPIRED":
        old = [c for c in ix.cards_by_carrier[cid] if c["rate_card_id"] != card["rate_card_id"] and c["effective_to"] < ship["ship_date"]]
        if not old:
            return None
        applied = old[0]
        rate = ix.rates[(applied["rate_card_id"], lane, svc, tier)]
        fuel_rate, min_charge = D(applied["fuel_surcharge_rate"]), applied["min_charge"]
    elif issue == "WEIGHT_TIER_MISAPPLIED":
        i = tier_index(tier)
        if i == 0:
            return None
        tier = C.TIERS[i - 1][0]                      # lighter tier => higher per-lb rate
        rate = ix.rates[(card["rate_card_id"], lane, svc, tier)]
    elif issue == "DIM_WEIGHT_MISCALC":
        wrong = dim_weight(ship["length_in"], ship["width_in"], ship["height_in"], ship["pieces"], card["dim_divisor"] - 25)
        wt = chargeable_weight(exp["actual"], wrong)
        if wt <= exp["weight"]:
            return None
        tier = tier_for(wt)
        rate = ix.rates[(card["rate_card_id"], lane, svc, tier)]
    elif issue == "FUEL_RATE_WRONG":
        fuel_rate = q(fuel_rate + D(round(r.uniform(0.03, 0.07), 4)), 4)
    base = base_charge(wt, rate, min_charge)
    fuel = fuel_charge(base, fuel_rate)
    specs = [dict(line_type="BASE", accessorial_code=None, description=f"Freight {svc} {lane}", billed_weight_lb=wt,
                  weight_tier=tier, unit_rate=D(rate), amount=base),
             dict(line_type="FUEL", accessorial_code=None, description="Fuel surcharge", billed_weight_lb=None,
                  weight_tier=None, unit_rate=fuel_rate, amount=fuel)]
    if issue == "SURCHARGE_DUPLICATED":
        specs.append(dict(specs[1]))
    for code, amt in exp["accessorials"].items():
        specs.append(dict(line_type="ACCESSORIAL", accessorial_code=code, description=f"Accessorial {code}",
                          billed_weight_lb=None, weight_tier=None, unit_rate=None, amount=amt))
    if issue == "INVALID_ACCESSORIAL":
        cands = sorted(c for (rc, c) in ix.card_acc if rc == card["rate_card_id"] and c not in ix.ship_acc.get(ship["shipment_id"], ()))
        if not cands:
            return None
        code = r.choice(cands)
        specs.append(dict(line_type="ACCESSORIAL", accessorial_code=code, description=f"Accessorial {code}",
                          billed_weight_lb=None, weight_tier=None, unit_rate=None, amount=ix.card_acc[(card["rate_card_id"], code)]))
    billed = sum((s["amount"] for s in specs), Decimal("0.00"))
    if issue not in ("NONE", "UNKNOWN_SHIPMENT") and billed - exp["total"] <= Decimal(C.TOLERANCE):
        return None                                    # anomaly must produce a real overcharge
    return applied["rate_card_id"], specs


def build_invoices(seed, t, n_invoices):
    r = stream(seed, "invoices")
    ix = Index(t)
    cards = {}
    exp_cache = {}

    def exp_for(s):
        if s["shipment_id"] not in exp_cache:
            card = ix.card_at(s["carrier_id"], s["ship_date"])
            exp_cache[s["shipment_id"]] = (card, expected_charges(ix, s, card))
        return exp_cache[s["shipment_id"]]

    n_dup = max(1, round(C.ISSUE_RATES["DUPLICATE_BILLING"] * n_invoices))
    chosen = r.sample(t["shipments"], n_invoices - n_dup)
    r.shuffle(chosen)
    plans, assigned = [], set()
    for issue, rate in C.ISSUE_RATES.items():
        if issue == "DUPLICATE_BILLING":
            continue
        want, got = max(1, round(rate * n_invoices)), 0
        for s in chosen:
            if got >= want:
                break
            if s["shipment_id"] in assigned:
                continue
            card, exp = exp_for(s)
            res = build_lines(ix, s, card, exp, "UNKNOWN_SHIPMENT" if issue == "UNKNOWN_SHIPMENT" else issue, r)
            if res:
                assigned.add(s["shipment_id"]); got += 1
                plans.append(dict(ship=s, issue=issue, applied=res[0], specs=res[1],
                                  exp_total=Decimal("0.00") if issue == "UNKNOWN_SHIPMENT" else exp["total"]))
    for s in chosen:
        if s["shipment_id"] in assigned:
            continue
        card, exp = exp_for(s)
        res = build_lines(ix, s, card, exp, "NONE", r)
        plans.append(dict(ship=s, issue="NONE", applied=res[0], specs=res[1], exp_total=exp["total"]))
    clean = [p for p in plans if p["issue"] == "NONE"]
    for p in r.sample(clean, n_dup):                   # duplicates: repeat of an already-valid invoice
        plans.append(dict(ship=p["ship"], issue="DUPLICATE_BILLING", applied=p["applied"], specs=[dict(x) for x in p["specs"]],
                          exp_total=Decimal("0.00"), dup_of=p))
    latest = C.AS_OF - timedelta(days=C.LATEST_INVOICE_DATE_LAG)
    for p in plans:
        p["invoice_date"] = None
    for p in plans:
        if "dup_of" not in p:
            p["invoice_date"] = min(p["ship"]["delivered_at"].date() + timedelta(days=r.randint(1, 10)), latest)
    for p in plans:
        if "dup_of" in p:
            p["invoice_date"] = min(p["dup_of"]["invoice_date"] + timedelta(days=r.randint(5, 20)), latest)
    plans.sort(key=lambda p: (p["invoice_date"], p["ship"]["shipment_id"], "dup_of" in p))
    unknown_n = 0
    scac = {c["carrier_id"]: c["scac_code"] for c in t["carriers"]}
    gt = []
    for n, p in enumerate(plans, 1):
        iid = ids.invoice_id(n)
        p["id"] = iid
        ship_ref = p["ship"]["shipment_id"]
        if p["issue"] == "UNKNOWN_SHIPMENT":
            unknown_n += 1
            ship_ref = ids.unknown_shipment_id(unknown_n)
        cid = p["ship"]["carrier_id"]
        lines = []
        for k, sp in enumerate(p["specs"], 1):
            lines.append(dict(line_id=ids.line_id(iid, k), invoice_id=iid, line_seq=k, **sp))
        sums = {ty: sum((l["amount"] for l in lines if l["line_type"] == ty), Decimal("0.00")) for ty in ("BASE", "FUEL", "ACCESSORIAL")}
        total = sum(sums.values(), Decimal("0.00"))
        t["freight_invoices"].append(dict(
            invoice_id=iid, carrier_id=cid, shipment_id=ship_ref, carrier_invoice_number=f"{scac[cid]}-{n:07d}",
            rate_card_id_applied=p["applied"], invoice_date=p["invoice_date"], due_date=p["invoice_date"] + timedelta(days=30),
            currency="USD", base_amount=sums["BASE"], fuel_amount=sums["FUEL"], accessorial_amount=sums["ACCESSORIAL"],
            total_amount=total, current_status="RECEIVED"))
        t["invoice_lines"] += lines
        note = {"UNKNOWN_SHIPMENT": f"billed shipment {ship_ref} does not exist (real: {p['ship']['shipment_id']})",
                "DUPLICATE_BILLING": f"repeat bill of {p['dup_of']['id']}" if "dup_of" in p else ""}.get(p["issue"], "")
        gt.append(dict(entity_type="INVOICE", entity_id=iid, invoice_id=iid, issue_type=p["issue"],
                       expected_decision="PAY" if p["issue"] == "NONE" else "DISPUTE", billed_total=total,
                       expected_total=p["exp_total"], expected_variance=total - p["exp_total"], note=note))
    return gt


# ------------------------------------------------------------------ audit workflow, credit notes, events
def _tdelta(r, d_lo, d_hi, h_lo=0, h_hi=0):
    return timedelta(days=r.randint(d_lo, d_hi), hours=r.randint(h_lo, h_hi))


def build_workflow(seed, t, gt):
    r = stream(seed, "workflow")
    raw = audit_invoices(t)
    raw.sort(key=lambda e: (e["invoice_id"], e["line_id"] or ""))
    inv_by = {i["invoice_id"]: i for i in t["freight_invoices"]}
    by_inv = defaultdict(list)
    ev_n = dict(IEV=0, XEV=0, CEV=0)
    ev_tbl = dict(IEV="invoice_events", XEV="exception_events", CEV="credit_note_events")
    ev_fk = dict(IEV="invoice_id", XEV="exception_id", CEV="credit_note_id")
    state = {}

    def ev(prefix, entity, to, when, actor, note=None):
        if when > CUTOFF:
            return False
        ev_n[prefix] += 1
        frm = state.get(entity)
        t[ev_tbl[prefix]].append(dict(event_id=ids.event_id(prefix, ev_n[prefix]), **{ev_fk[prefix]: entity},
                                      from_status=frm, to_status=to, event_at=when, actor=actor, note=note))
        state[entity] = to
        return True

    for n, e in enumerate(raw, 1):
        e["exception_id"] = ids.exception_id(n)
        by_inv[e["invoice_id"]].append(e)
    cn_n = 0
    audit_at, terminal_at = {}, {}
    for inv in t["freight_invoices"]:
        iid = inv["invoice_id"]
        a = at(inv["invoice_date"], 9) + _tdelta(r, 1, 4, 0, 8)
        audit_at[iid] = a
        ev("IEV", iid, "RECEIVED", at(inv["invoice_date"], 9), "SYSTEM", "invoice received from carrier")
        ev("IEV", iid, "AUDITED", a, "AUDITOR", "automated audit run")
        excs = by_inv.get(iid, [])
        if not excs:
            ap = a + _tdelta(r, 1, 3, 0, 4)
            ev("IEV", iid, "APPROVED_FOR_PAYMENT", ap, "AUDITOR", "no exceptions")
            ev("IEV", iid, "PAID", at(inv["invoice_date"], 10) + timedelta(days=r.randint(20, 40)), "AP_TEAM")
            continue
        ev("IEV", iid, "DISPUTED", a + timedelta(hours=1), "AUDITOR", f"{len(excs)} exception(s)")
        root = root_cause({e["exception_type"] for e in excs})
        rebut = r.random() < C.REBUTTAL_PROB.get(root, 0.10)
        ends = []
        for e in excs:
            xid = e["exception_id"]
            e["detected_at"] = a + timedelta(minutes=30)
            v = abs(e["variance_amount"])
            e["severity"] = next(s for lim, s in C.SEVERITY_BANDS if lim is None or v < lim)
            ev("XEV", xid, "OPEN", e["detected_at"], "SYSTEM", e["exception_type"])
            rv = a + _tdelta(r, 1, 3, 1, 5)
            ev("XEV", xid, "UNDER_REVIEW", rv, "AUDITOR")
            dec = rv + _tdelta(r, 1, 10, 1, 5)
            if rebut:
                ok = ev("XEV", xid, "REJECTED", dec, "AUDITOR", "carrier rebuttal accepted")
                if ok:
                    ends.append(dec)
                continue
            if not ev("XEV", xid, "APPROVED", dec, "AUDITOR", "dispute upheld"):
                continue
            cn_n += 1
            cid = ids.credit_note_id(cn_n)
            cn = dict(credit_note_id=cid, exception_id=xid, invoice_id=iid, carrier_id=inv["carrier_id"],
                      credit_amount=e["variance_amount"], currency="USD", issued_date=None, current_status="DRAFT")
            d0 = dec + _tdelta(r, 0, 2, 1, 5)
            if not ev("CEV", cid, "DRAFT", d0, "CARRIER", "credit drafted for approved dispute"):
                cn_n -= 1                              # credit not yet drafted at AS_OF: exception stays APPROVED
                continue
            t["credit_notes"].append(cn)
            d1 = d0 + _tdelta(r, 1, 5, 1, 5)
            if ev("CEV", cid, "ISSUED", d1, "CARRIER"):
                cn["issued_date"] = d1.date()
                d2 = d1 + _tdelta(r, 3, 14, 1, 5)
                if d2 + timedelta(hours=1) <= CUTOFF and ev("CEV", cid, "APPLIED", d2, "AP_TEAM", "applied against open balance"):
                    if ev("XEV", xid, "CREDITED", d2 + timedelta(hours=1), "SYSTEM"):
                        ends.append(d2 + timedelta(hours=1))
        if len(ends) == len(excs):
            res = max(ends) + _tdelta(r, 0, 1, 1, 5)
            if ev("IEV", iid, "RESOLVED", res, "AUDITOR", "all exceptions closed"):
                ev("IEV", iid, "PAID", res + _tdelta(r, 5, 25, 1, 5), "AP_TEAM", "paid net of credits")
    # inject: credit note exceeds exception amount (ground-truth labelled)
    exc_by_id = {e["exception_id"]: e for e in raw}
    cns = t["credit_notes"]
    gt_cn = {c["credit_note_id"]: "NONE" for c in cns}
    if cns:
        k = max(1, round(C.CREDIT_EXCEEDS_RATE * len(cns)))
        material = [c for c in cns if c["credit_amount"] >= Decimal("1.00")]   # so the overstatement is visible above tolerance
        for c in r.sample(material, min(k, len(material))):
            c["credit_amount"] = money(c["credit_amount"] * D(round(r.uniform(1.15, 1.60), 3)))
            gt_cn[c["credit_note_id"]] = "CREDIT_EXCEEDS_EXCEPTION"
    for c in cns:
        var = exc_by_id[c["exception_id"]]["variance_amount"]
        bad = gt_cn[c["credit_note_id"]] != "NONE"
        gt.append(dict(entity_type="CREDIT_NOTE", entity_id=c["credit_note_id"], invoice_id=c["invoice_id"],
                       issue_type=gt_cn[c["credit_note_id"]],
                       expected_decision="CAP_AT_EXCEPTION_AMOUNT" if bad else "ISSUE_AT_VARIANCE",
                       billed_total=c["credit_amount"], expected_total=var, expected_variance=c["credit_amount"] - var,
                       note="credit exceeds approved exception amount" if bad else ""))
    for e in raw:
        e["current_status"] = state[e["exception_id"]]
    t["audit_exceptions"] = raw
    for i in t["freight_invoices"]:
        i["current_status"] = state[i["invoice_id"]]
    for c in cns:
        c["current_status"] = state[c["credit_note_id"]]


# ------------------------------------------------------------------ entry point
def generate(seed=C.DEFAULT_SEED, carriers=100, shipments=20000, invoices=15000):
    if shipments < invoices:
        raise ValueError("need shipments >= invoices (one invoice per shipment, plus duplicates)")
    t, meta, lane_dist = build_master(seed, carriers)
    for name in ("shipments", "shipment_legs", "weight_measurements", "shipment_accessorials", "freight_invoices", "invoice_lines",
                 "audit_exceptions", "credit_notes", "invoice_events", "exception_events", "credit_note_events"):
        t[name] = []
    build_shipments(seed, t, meta, lane_dist, shipments)
    gt = build_invoices(seed, t, invoices)
    build_workflow(seed, t, gt)
    return dict(t), gt
