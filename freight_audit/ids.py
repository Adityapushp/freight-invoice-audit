"""Deterministic, zero-padded ID helpers. IDs are immutable and generated from counters only."""
import re

def carrier_id(n): return f"CAR-{n:06d}"
def rate_card_id(carrier, v): return f"RATE-{carrier}-2026-{v:02d}"
def lane_id(n): return f"LANE-{n:04d}"
def rate_line_id(n): return f"RLINE-{n:07d}"
def rca_id(n): return f"RCA-{n:06d}"
def shipment_id(n): return f"SHP-2026-{n:06d}"
def leg_id(shp, k): return f"LEG-{shp}-{k:02d}"
def measurement_id(shp, k): return f"WM-{shp}-{k:02d}"
def sa_id(shp, code): return f"SACC-{shp}-{code}"
def invoice_id(n): return f"FINV-2026-{n:06d}"
def line_id(inv, k): return f"FLINE-{inv}-{k:02d}"
def exception_id(n): return f"FEX-2026-{n:06d}"
def credit_note_id(n): return f"CN-2026-{n:06d}"
def event_id(prefix, n): return f"{prefix}-{n:07d}"
def unknown_shipment_id(n): return f"SHP-2026-{900000 + n:06d}"   # well-formed but never created

PATTERNS = {
    "carriers": r"CAR-\d{6}", "lanes": r"LANE-\d{4}", "rate_cards": r"RATE-CAR-\d{6}-2026-\d{2}",
    "rate_card_rates": r"RLINE-\d{7}", "rate_card_accessorials": r"RCA-\d{6}",
    "shipments": r"SHP-2026-\d{6}", "shipment_legs": r"LEG-SHP-2026-\d{6}-\d{2}",
    "weight_measurements": r"WM-SHP-2026-\d{6}-\d{2}", "shipment_accessorials": r"SACC-SHP-2026-\d{6}-[A-Z_]+",
    "freight_invoices": r"FINV-2026-\d{6}", "invoice_lines": r"FLINE-FINV-2026-\d{6}-\d{2}",
    "audit_exceptions": r"FEX-2026-\d{6}", "credit_notes": r"CN-2026-\d{6}",
    "invoice_events": r"IEV-\d{7}", "exception_events": r"XEV-\d{7}", "credit_note_events": r"CEV-\d{7}",
}

def matches(table, value):
    p = PATTERNS.get(table)
    return True if p is None else re.fullmatch(p, value) is not None
