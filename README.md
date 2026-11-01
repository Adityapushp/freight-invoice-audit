# Freight Invoice Audit — synthetic data, auditor, validation

72-hour challenge: *validate freight invoices against contracted rates, shipment characteristics, accessorials and delivery records.*
Pure Python 3.10+ standard library (pytest only for tests). No external data.

## Quick start

```bash
git clone <this repo> && cd freight-invoice-audit
pip install -r requirements-dev.txt            # pytest only
python -m freight_audit generate --profile starter   # 10 carriers / 500 shipments / 375 invoices (committed in data/starter)
python -m freight_audit generate --profile full      # 100 carriers / 20,000 shipments / 15,000 invoices (~10 s, ~150 MB, git-ignored)
python -m freight_audit validate --profile full      # 14 validation checks
python -m freight_audit audit    --profile full      # precision/recall vs ground truth
python -m freight_audit repro    --profile full      # regenerate twice, compare row counts + SHA-256
python -m pytest -q                                  # 24 tests
```
`make all` runs the lot. Seed defaults to `20261022`; override with `--seed`, scale with `--carriers/--shipments/--invoices`. Starter and full use the **same generator** — only the parameters differ.

## What it produces (`data/<profile>/`)
| Path | Content |
|---|---|
| `csv/`, `json/` | 17 tables (11 required entities + bridge/rate-line/event tables) |
| `sql/schema.sql`, `sql/seed.sql` | DDL with PK/FK/CHECK + INSERTs (SQLite-compatible) |
| `ground_truth/ground_truth.{csv,json}` | Label for **every** invoice and credit note; kept apart from inputs |
| `manifest.json` | seed, scale, command, row counts, SHA-256 of every file, source/provenance |
| `reports/` | `validation_summary.json`, `evaluation.json` |

Schema and rules: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) (generated from `freight_audit/schema.py`, the single source of truth).
Evidence from the full run is committed in `reports/full/` and `reports/*/reproducibility_*.json`.

## How it works
```
master data (Carrier, Lane, RateCard, RateCardRate, Accessorial, RateCardAccessorial)
  -> Shipment + ShipmentLeg + WeightMeasurement + ShipmentAccessorial (delivery record)
  -> valid invoices priced by pricing.py
  -> labelled anomaly injection (ground_truth)
  -> audit.py recomputes expected charges from the inputs only -> AuditException
  -> workflow events (invoice / exception / credit-note history) -> CreditNote
```
**Expected-charge rule (`pricing.py`, Decimal, ROUND_HALF_UP):**
1. Contract = the rate card of the carrier effective on `ship_date`.
2. Authoritative weight = the single `ORIGIN_SCALE` measurement; dim weight = ceil(L×W×H×pieces ÷ contract divisor).
3. Billable weight = max(ceil(actual), dim weight); tier by billable weight (lower bound inclusive: 50 lb → T2).
4. Base = max(min_charge, billable × rate(lane, service, tier)); fuel = base × contracted fuel %; accessorials only if a delivery-record event exists **and** the accessorial is contracted.

**Injected edge cases** (one root cause per invoice; ≈14.5 % of invoices; each guaranteed to be a real overcharge):
`UNKNOWN_SHIPMENT`, `RATE_CARD_EXPIRED` (priced on the superseded card), `WEIGHT_TIER_MISAPPLIED`, `SURCHARGE_DUPLICATED`, `CREDIT_EXCEEDS_EXCEPTION`, plus `DUPLICATE_BILLING`, `INVALID_ACCESSORIAL`, `DIM_WEIGHT_MISCALC` (wrong divisor), `FUEL_RATE_WRONG`. Baseline also has dim-weight-billed shipments (~25 % bulky), fuel surcharges, and shipments placed exactly on tier boundaries (49/50/51, 149/150/151, …).

**Derived, not random:** invoice subtotals/totals from lines; exceptions from the auditor; exception severity from variance; credit notes from approved exceptions; statuses from event history; invoice status from exception outcomes. Dates are checked against `AS_OF = 2026-10-22`, so recent invoices are genuinely still open/disputed.

## Results (full dataset, seed 20261022)
- 282,415 rows; 15,000 invoices, 2,175 anomalous (14.5 %); 2,943 exceptions; 2,678 credit notes (107 deliberately exceed their exception).
- Auditor: precision = recall = 1.00 overall and per issue type; flagged variance $106,804.22 = injected overbilling to the cent.
- Validation: 14/14 checks pass. Reproducibility: 2 runs → 38 files, identical SHA-256.

## Design decisions & trade-offs
- **One invoice = one shipment** (per-PRO billing). Keeps line-level traceability simple; duplicates appear as a 2nd invoice for the same shipment.
- **Exceptions are produced by an auditor that never reads ground truth**; ground truth only scores it. Exceptions are per line, so one root cause can yield derived exceptions (e.g. fuel on an inflated base → `FUEL_ON_BASE_VARIANCE`).
- **Orphan FK is intentional** for `UNKNOWN_SHIPMENT`; the validator requires orphans == labelled set (no silent corruption). `seed.sql` disables FK enforcement for that reason.
- **Per-stage RNG streams** (`sha256(seed:stage)`) so changing one stage doesn't reshuffle the others.
- Rebuttal outcomes use documented per-type probabilities (`config.REBUTTAL_PROB`); everything else follows from rules.

## Limitations (be upfront)
- **F1 = 1.0 is a pipeline-consistency result, not a claim of real-world accuracy:** the auditor implements the same documented rules the generator violates. Real invoices have noise (tolerances, rounding, partial data) that this does not model. A harder benchmark would add near-miss/ambiguous cases and noisy fields.
- Only overbilling is modelled (no under-billing, no missing accessorial lines, no multi-shipment consolidated invoices, no currency/tax).
- Distances are region-centroid based; rates are plausible, not real tariffs. Median invoice ≈ $87 (parcel/small-LTL scale).
- Bit-for-bit reproducibility is verified on CPython 3.12; other major versions may change `random` internals.

## Provenance / lawful use
No external datasets were used. Structure (lane × weight tier × service, dim divisors 139/166, accessorial types) follows public industry conventions for schema inspiration only; all values are synthetic. See `manifest.json → sources`.

## AI usage
See [`AI_USAGE.md`](AI_USAGE.md) and [`PROMPT_HISTORY.md`](PROMPT_HISTORY.md).
