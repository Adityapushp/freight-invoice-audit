"""Single source of truth for the data dictionary.
Drives: CSV/JSON/SQL export, typed CSV loading, enum/null validation, docs/DATA_DICTIONARY.md."""
from dataclasses import dataclass, field
from . import config as C

@dataclass
class Field:
    name: str
    type: str                 # str | int | dec | date | dt | bool
    required: bool = True
    desc: str = ""
    unit: str = ""
    enum: list = None
    fk: str = None            # "table.column"
    unique: bool = False
    dp: int = 2               # decimal places for dec

@dataclass
class Table:
    name: str
    entity: str
    desc: str
    pk: str
    fields: list
    relations: str = ""
    order_by: str = None

def F(name, type, required=True, desc="", **kw): return Field(name, type, required, desc, **kw)

SERVICE_ENUM = C.SERVICES
TIER_ENUM = [t[0] for t in C.TIERS]
INV_STATUS = list(C.INVOICE_TRANSITIONS) [1:]
EXC_STATUS = list(C.EXCEPTION_TRANSITIONS)[1:]
CN_STATUS = list(C.CREDIT_TRANSITIONS)[1:]

def _events(entity, table, fk_table, statuses):
    return Table(table, f"{entity}Event", f"Append-only status history for {entity}. Current status = last event; history is never overwritten.",
                 "event_id", [
        F("event_id", "str", desc="Primary key", unique=True),
        F(f"{entity.lower() if entity!='CreditNote' else 'credit_note'}_id" if False else fk_table[1], "str", fk=f"{fk_table[0]}.{fk_table[1]}", desc="Parent entity"),
        F("from_status", "str", False, "Previous status (null on creation)", enum=statuses),
        F("to_status", "str", desc="New status", enum=statuses),
        F("event_at", "dt", desc="When the transition happened (UTC, naive)"),
        F("actor", "str", desc="SYSTEM | AUDITOR | CARRIER | AP_TEAM", enum=["SYSTEM", "AUDITOR", "CARRIER", "AP_TEAM"]),
        F("note", "str", False, "Free-text context"),
    ], relations=f"{entity} 1:N {entity}Event", order_by="event_id")

TABLES = [
    Table("carriers", "Carrier", "Freight carrier under contract.", "carrier_id", [
        F("carrier_id", "str", desc="CAR-000001 pattern", unique=True),
        F("carrier_name", "str", desc="Synthetic name", unique=True),
        F("scac_code", "str", desc="4-letter carrier code (synthetic)", unique=True),
        F("service_mode", "str", desc="Primary mode", enum=["LTL", "PARCEL", "TL"]),
        F("onboarded_date", "date", desc="Must be <= first rate card effective_from"),
        F("status", "str", desc="Lifecycle state", enum=["ACTIVE", "INACTIVE"]),
    ], relations="Carrier 1:N RateCard; Carrier 1:N Shipment; Carrier 1:N FreightInvoice"),
    Table("lanes", "Lane", "Origin-region to destination-region corridor.", "lane_id", [
        F("lane_id", "str", unique=True),
        F("origin_region", "str", desc="Region code", enum=list(C.REGIONS)),
        F("dest_region", "str", desc="Region code", enum=list(C.REGIONS)),
        F("distance_miles", "int", desc="Deterministic from region centroids", unit="miles"),
    ], relations="Lane 1:N Shipment; Lane N:M RateCard (via rate_card_rates)"),
    Table("rate_cards", "RateCard", "Contract version for a carrier with effective dates, fuel %, dim divisor, minimum charge.", "rate_card_id", [
        F("rate_card_id", "str", desc="RATE-<carrier-id>-2026-<version>", unique=True),
        F("carrier_id", "str", fk="carriers.carrier_id"),
        F("version", "int", desc="01 = Jan contract, 02 = mid-year renegotiation"),
        F("effective_from", "date"), F("effective_to", "date", desc="Inclusive; must be >= effective_from"),
        F("fuel_surcharge_rate", "dec", desc="Contracted fuel surcharge as a fraction of base charge", dp=4),
        F("dim_divisor", "int", desc="Cubic inches per lb used for dimensional weight", unit="in^3/lb", enum=[139, 166]),
        F("min_charge", "dec", desc="Minimum base charge per shipment", unit="USD"),
        F("currency", "str", enum=["USD"]),
        F("status", "str", desc="EXPIRED if effective_to < as-of date", enum=["ACTIVE", "EXPIRED"]),
    ], relations="RateCard 1:N RateCardRate; RateCard N:M Accessorial (via rate_card_accessorials)"),
    Table("rate_card_rates", "RateCardRate", "Rate per lb by rate card, lane, service and weight tier (bridge Lane x RateCard).", "rate_line_id", [
        F("rate_line_id", "str", unique=True),
        F("rate_card_id", "str", fk="rate_cards.rate_card_id"),
        F("lane_id", "str", fk="lanes.lane_id"),
        F("service", "str", enum=SERVICE_ENUM),
        F("weight_tier", "str", enum=TIER_ENUM),
        F("min_weight_lb", "int", desc="Inclusive lower bound", unit="lb"),
        F("max_weight_lb", "int", False, "Exclusive upper bound; null for top tier", unit="lb"),
        F("rate_per_lb", "dec", desc="Contracted rate", unit="USD/lb", dp=4),
    ], relations="Unique (rate_card_id, lane_id, service, weight_tier)"),
    Table("accessorials", "Accessorial", "Catalogue of accessorial services.", "accessorial_code", [
        F("accessorial_code", "str", unique=True),
        F("description", "str"),
        F("trigger_event", "str", desc="Delivery-record event that justifies the charge"),
        F("standard_amount", "dec", desc="Reference list price (contracts override)", unit="USD"),
        F("requires_evidence", "bool"),
    ], relations="Accessorial N:M RateCard; Accessorial N:M Shipment (via shipment_accessorials)"),
    Table("rate_card_accessorials", "RateCardAccessorial", "Bridge: accessorials contracted on a rate card with the agreed amount.", "rca_id", [
        F("rca_id", "str", unique=True),
        F("rate_card_id", "str", fk="rate_cards.rate_card_id"),
        F("accessorial_code", "str", fk="accessorials.accessorial_code"),
        F("amount", "dec", unit="USD"),
    ], relations="Unique (rate_card_id, accessorial_code)"),
    Table("shipments", "Shipment", "A delivered consignment with actual dimensions and service.", "shipment_id", [
        F("shipment_id", "str", desc="SHP-2026-000001", unique=True),
        F("carrier_id", "str", fk="carriers.carrier_id"),
        F("lane_id", "str", fk="lanes.lane_id"),
        F("service", "str", enum=SERVICE_ENUM),
        F("ship_date", "date", desc="Pickup date; selects the effective rate card"),
        F("delivered_at", "dt", desc="= arrival of last ShipmentLeg"),
        F("pieces", "int", desc=">= 1"),
        F("length_in", "int", desc="Per piece", unit="in"), F("width_in", "int", desc="Per piece", unit="in"),
        F("height_in", "int", desc="Per piece", unit="in"),
        F("status", "str", desc="Only DELIVERED shipments are invoiceable", enum=["DELIVERED"]),
    ], relations="Shipment 1:N ShipmentLeg; 1:N WeightMeasurement; N:M Accessorial; 1:N FreightInvoice (>1 only for duplicate billing)"),
    Table("shipment_legs", "ShipmentLeg", "Movement segment; the last leg carries the delivery record.", "leg_id", [
        F("leg_id", "str", unique=True),
        F("shipment_id", "str", fk="shipments.shipment_id"),
        F("leg_seq", "int", desc="1-based, contiguous"),
        F("from_node", "str"), F("to_node", "str"),
        F("departed_at", "dt"), F("arrived_at", "dt", desc=">= departed_at"),
        F("leg_status", "str", enum=["COMPLETED"]),
    ], relations="Shipment 1:N ShipmentLeg"),
    Table("weight_measurements", "WeightMeasurement", "Weight observations. Exactly one ORIGIN_SCALE row per shipment is authoritative for audit.", "measurement_id", [
        F("measurement_id", "str", unique=True),
        F("shipment_id", "str", fk="shipments.shipment_id"),
        F("source", "str", enum=["SHIPPER_DECLARED", "ORIGIN_SCALE", "CARRIER_REWEIGH"]),
        F("weight_lb", "dec", unit="lb", dp=1),
        F("is_authoritative", "bool", desc="True only for ORIGIN_SCALE"),
        F("measured_at", "dt"),
    ], relations="Shipment 1:N WeightMeasurement"),
    Table("shipment_accessorials", "ShipmentAccessorial", "Bridge: accessorial events recorded in the delivery record (evidence).", "sa_id", [
        F("sa_id", "str", unique=True),
        F("shipment_id", "str", fk="shipments.shipment_id"),
        F("accessorial_code", "str", fk="accessorials.accessorial_code"),
        F("event_at", "dt", desc="Between ship and delivery"),
        F("evidence_ref", "str", desc="Synthetic scan/POD reference"),
    ], relations="Unique (shipment_id, accessorial_code)"),
    Table("freight_invoices", "FreightInvoice", "Carrier invoice for one shipment (header). Totals are derived from lines.", "invoice_id", [
        F("invoice_id", "str", desc="FINV-2026-000001", unique=True),
        F("carrier_id", "str", fk="carriers.carrier_id"),
        F("shipment_id", "str", desc="FK to shipments (deliberately orphaned only for UNKNOWN_SHIPMENT cases)", fk="shipments.shipment_id"),
        F("carrier_invoice_number", "str", desc="Carrier-side number", unique=True),
        F("rate_card_id_applied", "str", desc="Rate card the carrier says it priced with", fk="rate_cards.rate_card_id"),
        F("invoice_date", "date", desc=">= shipment delivery date"),
        F("due_date", "date", desc="invoice_date + 30 days"),
        F("currency", "str", enum=["USD"]),
        F("base_amount", "dec", desc="Sum of BASE lines", unit="USD"),
        F("fuel_amount", "dec", desc="Sum of FUEL lines", unit="USD"),
        F("accessorial_amount", "dec", desc="Sum of ACCESSORIAL lines", unit="USD"),
        F("total_amount", "dec", desc="base + fuel + accessorial", unit="USD"),
        F("current_status", "str", desc="Derived from last invoice_events row", enum=INV_STATUS),
    ], relations="FreightInvoice 1:N InvoiceLine; 1:N AuditException; 1:N InvoiceEvent"),
    Table("invoice_lines", "InvoiceLine", "Billed charge line: base freight, fuel surcharge or accessorial.", "line_id", [
        F("line_id", "str", desc="FLINE-<invoice-id>-01", unique=True),
        F("invoice_id", "str", fk="freight_invoices.invoice_id"),
        F("line_seq", "int", desc="1-based, contiguous"),
        F("line_type", "str", enum=["BASE", "FUEL", "ACCESSORIAL"]),
        F("accessorial_code", "str", False, "Required iff line_type = ACCESSORIAL", fk="accessorials.accessorial_code"),
        F("description", "str"),
        F("billed_weight_lb", "int", False, "BASE only", unit="lb"),
        F("weight_tier", "str", False, "BASE only", enum=TIER_ENUM),
        F("unit_rate", "dec", False, "BASE: USD/lb; FUEL: fraction of base", dp=4),
        F("amount", "dec", unit="USD"),
    ], relations="FreightInvoice 1:N InvoiceLine", order_by="line_id"),
    Table("audit_exceptions", "AuditException", "Line-level (or invoice-level) discrepancy between billed and expected charge, produced by the auditor.", "exception_id", [
        F("exception_id", "str", desc="FEX-2026-000001", unique=True),
        F("invoice_id", "str", fk="freight_invoices.invoice_id"),
        F("line_id", "str", False, "Null for invoice-level findings (unknown shipment, duplicate bill)", fk="invoice_lines.line_id"),
        F("exception_type", "str", enum=C.EXCEPTION_TYPES),
        F("billed_amount", "dec", unit="USD"), F("expected_amount", "dec", unit="USD"),
        F("variance_amount", "dec", desc="billed - expected", unit="USD"),
        F("severity", "str", desc="By |variance|: <10 LOW, <50 MEDIUM, else HIGH", enum=["LOW", "MEDIUM", "HIGH"]),
        F("explanation", "str", desc="Human-readable line-level reason"),
        F("detected_at", "dt"),
        F("current_status", "str", desc="Derived from last exception_events row", enum=EXC_STATUS),
    ], relations="AuditException 1:N ExceptionEvent; AuditException 1:0..1 CreditNote"),
    Table("credit_notes", "CreditNote", "Credit issued by the carrier for an approved dispute.", "credit_note_id", [
        F("credit_note_id", "str", desc="CN-2026-000001", unique=True),
        F("exception_id", "str", desc="Approved exception this credit settles", fk="audit_exceptions.exception_id", unique=True),
        F("invoice_id", "str", fk="freight_invoices.invoice_id"),
        F("carrier_id", "str", fk="carriers.carrier_id"),
        F("credit_amount", "dec", desc="Must be <= exception variance", unit="USD"),
        F("currency", "str", enum=["USD"]),
        F("issued_date", "date", False, "Set once ISSUED"),
        F("current_status", "str", desc="Derived from last credit_note_events row", enum=CN_STATUS),
    ], relations="AuditException 1:0..1 CreditNote"),
    _events("Invoice", "invoice_events", ("freight_invoices", "invoice_id"), INV_STATUS),
    _events("Exception", "exception_events", ("audit_exceptions", "exception_id"), EXC_STATUS),
    _events("CreditNote", "credit_note_events", ("credit_notes", "credit_note_id"), CN_STATUS),
]
BY_NAME = {t.name: t for t in TABLES}

GROUND_TRUTH_FIELDS = ["entity_type", "entity_id", "invoice_id", "issue_type", "expected_decision",
                       "billed_total", "expected_total", "expected_variance", "note"]
