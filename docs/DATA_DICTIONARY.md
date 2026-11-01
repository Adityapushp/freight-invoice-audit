# Data dictionary

_Generated from `freight_audit/schema.py` by `python -m freight_audit docs`. Do not edit by hand._

Conventions: dates ISO-8601; timestamps naive UTC; money in USD with 2 dp; rates 4 dp; weights in lb. Every table has a single-column primary key. History is kept in append-only `*_events` tables; `current_status` columns are derived from the last event.

## Entity relationship summary

- **Carrier** (`carriers`): Carrier 1:N RateCard; Carrier 1:N Shipment; Carrier 1:N FreightInvoice
- **Lane** (`lanes`): Lane 1:N Shipment; Lane N:M RateCard (via rate_card_rates)
- **RateCard** (`rate_cards`): RateCard 1:N RateCardRate; RateCard N:M Accessorial (via rate_card_accessorials)
- **RateCardRate** (`rate_card_rates`): Unique (rate_card_id, lane_id, service, weight_tier)
- **Accessorial** (`accessorials`): Accessorial N:M RateCard; Accessorial N:M Shipment (via shipment_accessorials)
- **RateCardAccessorial** (`rate_card_accessorials`): Unique (rate_card_id, accessorial_code)
- **Shipment** (`shipments`): Shipment 1:N ShipmentLeg; 1:N WeightMeasurement; N:M Accessorial; 1:N FreightInvoice (>1 only for duplicate billing)
- **ShipmentLeg** (`shipment_legs`): Shipment 1:N ShipmentLeg
- **WeightMeasurement** (`weight_measurements`): Shipment 1:N WeightMeasurement
- **ShipmentAccessorial** (`shipment_accessorials`): Unique (shipment_id, accessorial_code)
- **FreightInvoice** (`freight_invoices`): FreightInvoice 1:N InvoiceLine; 1:N AuditException; 1:N InvoiceEvent
- **InvoiceLine** (`invoice_lines`): FreightInvoice 1:N InvoiceLine
- **AuditException** (`audit_exceptions`): AuditException 1:N ExceptionEvent; AuditException 1:0..1 CreditNote
- **CreditNote** (`credit_notes`): AuditException 1:0..1 CreditNote
- **InvoiceEvent** (`invoice_events`): Invoice 1:N InvoiceEvent
- **ExceptionEvent** (`exception_events`): Exception 1:N ExceptionEvent
- **CreditNoteEvent** (`credit_note_events`): CreditNote 1:N CreditNoteEvent

Optional relationships: `audit_exceptions.line_id` (null for invoice-level findings), `credit_notes` (only for approved exceptions), `invoice_lines.accessorial_code` (only ACCESSORIAL lines). Effective dating: `rate_cards.effective_from/to` select the contract by `shipments.ship_date`.

## Carrier — `carriers`

Freight carrier under contract.

Primary key: `carrier_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `carrier_id` | str | Y |  | CAR-000001 pattern | Y |  |
| `carrier_name` | str | Y |  | Synthetic name | Y |  |
| `scac_code` | str | Y |  | 4-letter carrier code (synthetic) | Y |  |
| `service_mode` | str | Y |  | LTL, PARCEL, TL. Primary mode |  |  |
| `onboarded_date` | date | Y |  | Must be <= first rate card effective_from |  |  |
| `status` | str | Y |  | ACTIVE, INACTIVE. Lifecycle state |  |  |

## Lane — `lanes`

Origin-region to destination-region corridor.

Primary key: `lane_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `lane_id` | str | Y |  |  | Y |  |
| `origin_region` | str | Y |  | NE, SE, MW, SW, W, NW. Region code |  |  |
| `dest_region` | str | Y |  | NE, SE, MW, SW, W, NW. Region code |  |  |
| `distance_miles` | int | Y | miles | Deterministic from region centroids |  |  |

## RateCard — `rate_cards`

Contract version for a carrier with effective dates, fuel %, dim divisor, minimum charge.

Primary key: `rate_card_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `rate_card_id` | str | Y |  | RATE-<carrier-id>-2026-<version> | Y |  |
| `carrier_id` | str | Y |  |  |  | carriers.carrier_id |
| `version` | int | Y |  | 01 = Jan contract, 02 = mid-year renegotiation |  |  |
| `effective_from` | date | Y |  |  |  |  |
| `effective_to` | date | Y |  | Inclusive; must be >= effective_from |  |  |
| `fuel_surcharge_rate` | dec(4) | Y |  | Contracted fuel surcharge as a fraction of base charge |  |  |
| `dim_divisor` | int | Y | in^3/lb | 139, 166. Cubic inches per lb used for dimensional weight |  |  |
| `min_charge` | dec(2) | Y | USD | Minimum base charge per shipment |  |  |
| `currency` | str | Y |  | USD.  |  |  |
| `status` | str | Y |  | ACTIVE, EXPIRED. EXPIRED if effective_to < as-of date |  |  |

## RateCardRate — `rate_card_rates`

Rate per lb by rate card, lane, service and weight tier (bridge Lane x RateCard).

Primary key: `rate_line_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `rate_line_id` | str | Y |  |  | Y |  |
| `rate_card_id` | str | Y |  |  |  | rate_cards.rate_card_id |
| `lane_id` | str | Y |  |  |  | lanes.lane_id |
| `service` | str | Y |  | GROUND, EXPRESS, ECONOMY.  |  |  |
| `weight_tier` | str | Y |  | T1, T2, T3, T4, T5.  |  |  |
| `min_weight_lb` | int | Y | lb | Inclusive lower bound |  |  |
| `max_weight_lb` | int | N | lb | Exclusive upper bound; null for top tier |  |  |
| `rate_per_lb` | dec(4) | Y | USD/lb | Contracted rate |  |  |

## Accessorial — `accessorials`

Catalogue of accessorial services.

Primary key: `accessorial_code`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `accessorial_code` | str | Y |  |  | Y |  |
| `description` | str | Y |  |  |  |  |
| `trigger_event` | str | Y |  | Delivery-record event that justifies the charge |  |  |
| `standard_amount` | dec(2) | Y | USD | Reference list price (contracts override) |  |  |
| `requires_evidence` | bool | Y |  |  |  |  |

## RateCardAccessorial — `rate_card_accessorials`

Bridge: accessorials contracted on a rate card with the agreed amount.

Primary key: `rca_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `rca_id` | str | Y |  |  | Y |  |
| `rate_card_id` | str | Y |  |  |  | rate_cards.rate_card_id |
| `accessorial_code` | str | Y |  |  |  | accessorials.accessorial_code |
| `amount` | dec(2) | Y | USD |  |  |  |

## Shipment — `shipments`

A delivered consignment with actual dimensions and service.

Primary key: `shipment_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `shipment_id` | str | Y |  | SHP-2026-000001 | Y |  |
| `carrier_id` | str | Y |  |  |  | carriers.carrier_id |
| `lane_id` | str | Y |  |  |  | lanes.lane_id |
| `service` | str | Y |  | GROUND, EXPRESS, ECONOMY.  |  |  |
| `ship_date` | date | Y |  | Pickup date; selects the effective rate card |  |  |
| `delivered_at` | dt | Y |  | = arrival of last ShipmentLeg |  |  |
| `pieces` | int | Y |  | >= 1 |  |  |
| `length_in` | int | Y | in | Per piece |  |  |
| `width_in` | int | Y | in | Per piece |  |  |
| `height_in` | int | Y | in | Per piece |  |  |
| `status` | str | Y |  | DELIVERED. Only DELIVERED shipments are invoiceable |  |  |

## ShipmentLeg — `shipment_legs`

Movement segment; the last leg carries the delivery record.

Primary key: `leg_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `leg_id` | str | Y |  |  | Y |  |
| `shipment_id` | str | Y |  |  |  | shipments.shipment_id |
| `leg_seq` | int | Y |  | 1-based, contiguous |  |  |
| `from_node` | str | Y |  |  |  |  |
| `to_node` | str | Y |  |  |  |  |
| `departed_at` | dt | Y |  |  |  |  |
| `arrived_at` | dt | Y |  | >= departed_at |  |  |
| `leg_status` | str | Y |  | COMPLETED.  |  |  |

## WeightMeasurement — `weight_measurements`

Weight observations. Exactly one ORIGIN_SCALE row per shipment is authoritative for audit.

Primary key: `measurement_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `measurement_id` | str | Y |  |  | Y |  |
| `shipment_id` | str | Y |  |  |  | shipments.shipment_id |
| `source` | str | Y |  | SHIPPER_DECLARED, ORIGIN_SCALE, CARRIER_REWEIGH.  |  |  |
| `weight_lb` | dec(1) | Y | lb |  |  |  |
| `is_authoritative` | bool | Y |  | True only for ORIGIN_SCALE |  |  |
| `measured_at` | dt | Y |  |  |  |  |

## ShipmentAccessorial — `shipment_accessorials`

Bridge: accessorial events recorded in the delivery record (evidence).

Primary key: `sa_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `sa_id` | str | Y |  |  | Y |  |
| `shipment_id` | str | Y |  |  |  | shipments.shipment_id |
| `accessorial_code` | str | Y |  |  |  | accessorials.accessorial_code |
| `event_at` | dt | Y |  | Between ship and delivery |  |  |
| `evidence_ref` | str | Y |  | Synthetic scan/POD reference |  |  |

## FreightInvoice — `freight_invoices`

Carrier invoice for one shipment (header). Totals are derived from lines.

Primary key: `invoice_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `invoice_id` | str | Y |  | FINV-2026-000001 | Y |  |
| `carrier_id` | str | Y |  |  |  | carriers.carrier_id |
| `shipment_id` | str | Y |  | FK to shipments (deliberately orphaned only for UNKNOWN_SHIPMENT cases) |  | shipments.shipment_id |
| `carrier_invoice_number` | str | Y |  | Carrier-side number | Y |  |
| `rate_card_id_applied` | str | Y |  | Rate card the carrier says it priced with |  | rate_cards.rate_card_id |
| `invoice_date` | date | Y |  | >= shipment delivery date |  |  |
| `due_date` | date | Y |  | invoice_date + 30 days |  |  |
| `currency` | str | Y |  | USD.  |  |  |
| `base_amount` | dec(2) | Y | USD | Sum of BASE lines |  |  |
| `fuel_amount` | dec(2) | Y | USD | Sum of FUEL lines |  |  |
| `accessorial_amount` | dec(2) | Y | USD | Sum of ACCESSORIAL lines |  |  |
| `total_amount` | dec(2) | Y | USD | base + fuel + accessorial |  |  |
| `current_status` | str | Y |  | RECEIVED, AUDITED, APPROVED_FOR_PAYMENT, DISPUTED, RESOLVED, PAID. Derived from last invoice_events row |  |  |

## InvoiceLine — `invoice_lines`

Billed charge line: base freight, fuel surcharge or accessorial.

Primary key: `line_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `line_id` | str | Y |  | FLINE-<invoice-id>-01 | Y |  |
| `invoice_id` | str | Y |  |  |  | freight_invoices.invoice_id |
| `line_seq` | int | Y |  | 1-based, contiguous |  |  |
| `line_type` | str | Y |  | BASE, FUEL, ACCESSORIAL.  |  |  |
| `accessorial_code` | str | N |  | Required iff line_type = ACCESSORIAL |  | accessorials.accessorial_code |
| `description` | str | Y |  |  |  |  |
| `billed_weight_lb` | int | N | lb | BASE only |  |  |
| `weight_tier` | str | N |  | T1, T2, T3, T4, T5. BASE only |  |  |
| `unit_rate` | dec(4) | N |  | BASE: USD/lb; FUEL: fraction of base |  |  |
| `amount` | dec(2) | Y | USD |  |  |  |

## AuditException — `audit_exceptions`

Line-level (or invoice-level) discrepancy between billed and expected charge, produced by the auditor.

Primary key: `exception_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `exception_id` | str | Y |  | FEX-2026-000001 | Y |  |
| `invoice_id` | str | Y |  |  |  | freight_invoices.invoice_id |
| `line_id` | str | N |  | Null for invoice-level findings (unknown shipment, duplicate bill) |  | invoice_lines.line_id |
| `exception_type` | str | Y |  | UNKNOWN_SHIPMENT, DUPLICATE_BILLING, RATE_CARD_EXPIRED, DIM_WEIGHT_MISCALC, WEIGHT_TIER_MISAPPLIED, RATE_MISMATCH, SURCHARGE_DUPLICATED, INVALID_ACCESSORIAL, ACCESSORIAL_RATE_MISMATCH, FUEL_RATE_WRONG, FUEL_ON_BASE_VARIANCE.  |  |  |
| `billed_amount` | dec(2) | Y | USD |  |  |  |
| `expected_amount` | dec(2) | Y | USD |  |  |  |
| `variance_amount` | dec(2) | Y | USD | billed - expected |  |  |
| `severity` | str | Y |  | LOW, MEDIUM, HIGH. By |variance|: <10 LOW, <50 MEDIUM, else HIGH |  |  |
| `explanation` | str | Y |  | Human-readable line-level reason |  |  |
| `detected_at` | dt | Y |  |  |  |  |
| `current_status` | str | Y |  | OPEN, UNDER_REVIEW, APPROVED, REJECTED, CREDITED. Derived from last exception_events row |  |  |

## CreditNote — `credit_notes`

Credit issued by the carrier for an approved dispute.

Primary key: `credit_note_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `credit_note_id` | str | Y |  | CN-2026-000001 | Y |  |
| `exception_id` | str | Y |  | Approved exception this credit settles | Y | audit_exceptions.exception_id |
| `invoice_id` | str | Y |  |  |  | freight_invoices.invoice_id |
| `carrier_id` | str | Y |  |  |  | carriers.carrier_id |
| `credit_amount` | dec(2) | Y | USD | Must be <= exception variance |  |  |
| `currency` | str | Y |  | USD.  |  |  |
| `issued_date` | date | N |  | Set once ISSUED |  |  |
| `current_status` | str | Y |  | DRAFT, ISSUED, APPLIED. Derived from last credit_note_events row |  |  |

## InvoiceEvent — `invoice_events`

Append-only status history for Invoice. Current status = last event; history is never overwritten.

Primary key: `event_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `event_id` | str | Y |  | Primary key | Y |  |
| `invoice_id` | str | Y |  | Parent entity |  | freight_invoices.invoice_id |
| `from_status` | str | N |  | RECEIVED, AUDITED, APPROVED_FOR_PAYMENT, DISPUTED, RESOLVED, PAID. Previous status (null on creation) |  |  |
| `to_status` | str | Y |  | RECEIVED, AUDITED, APPROVED_FOR_PAYMENT, DISPUTED, RESOLVED, PAID. New status |  |  |
| `event_at` | dt | Y |  | When the transition happened (UTC, naive) |  |  |
| `actor` | str | Y |  | SYSTEM, AUDITOR, CARRIER, AP_TEAM. SYSTEM | AUDITOR | CARRIER | AP_TEAM |  |  |
| `note` | str | N |  | Free-text context |  |  |

## ExceptionEvent — `exception_events`

Append-only status history for Exception. Current status = last event; history is never overwritten.

Primary key: `event_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `event_id` | str | Y |  | Primary key | Y |  |
| `exception_id` | str | Y |  | Parent entity |  | audit_exceptions.exception_id |
| `from_status` | str | N |  | OPEN, UNDER_REVIEW, APPROVED, REJECTED, CREDITED. Previous status (null on creation) |  |  |
| `to_status` | str | Y |  | OPEN, UNDER_REVIEW, APPROVED, REJECTED, CREDITED. New status |  |  |
| `event_at` | dt | Y |  | When the transition happened (UTC, naive) |  |  |
| `actor` | str | Y |  | SYSTEM, AUDITOR, CARRIER, AP_TEAM. SYSTEM | AUDITOR | CARRIER | AP_TEAM |  |  |
| `note` | str | N |  | Free-text context |  |  |

## CreditNoteEvent — `credit_note_events`

Append-only status history for CreditNote. Current status = last event; history is never overwritten.

Primary key: `event_id`

| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |
|---|---|---|---|---|---|---|
| `event_id` | str | Y |  | Primary key | Y |  |
| `credit_note_id` | str | Y |  | Parent entity |  | credit_notes.credit_note_id |
| `from_status` | str | N |  | DRAFT, ISSUED, APPLIED. Previous status (null on creation) |  |  |
| `to_status` | str | Y |  | DRAFT, ISSUED, APPLIED. New status |  |  |
| `event_at` | dt | Y |  | When the transition happened (UTC, naive) |  |  |
| `actor` | str | Y |  | SYSTEM, AUDITOR, CARRIER, AP_TEAM. SYSTEM | AUDITOR | CARRIER | AP_TEAM |  |  |
| `note` | str | N |  | Free-text context |  |  |

## ground_truth (separate file, never an input feature)

| Field | Meaning |
|---|---|
| entity_type | INVOICE (every invoice) or CREDIT_NOTE (every credit note) |
| entity_id | FINV-… or CN-… |
| invoice_id | Parent invoice |
| issue_type | One of NONE, UNKNOWN_SHIPMENT, RATE_CARD_EXPIRED, WEIGHT_TIER_MISAPPLIED, SURCHARGE_DUPLICATED, DUPLICATE_BILLING, INVALID_ACCESSORIAL, DIM_WEIGHT_MISCALC, FUEL_RATE_WRONG, CREDIT_EXCEEDS_EXCEPTION |
| expected_decision | PAY / DISPUTE for invoices; ISSUE_AT_VARIANCE / CAP_AT_EXCEPTION_AMOUNT for credits |
| billed_total, expected_total, expected_variance | Computed by the generator from the documented rules at injection time |
| note | Short human description of the injection |
