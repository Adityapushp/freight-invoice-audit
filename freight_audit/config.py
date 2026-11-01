"""Central constants. Everything tunable lives here so the generator is parameterised, not hard-coded."""
from datetime import date

DEFAULT_SEED = 20261022
AS_OF = date(2026, 10, 22)            # "today" inside the simulated world
SHIP_START = date(2026, 1, 1)
SHIP_END = date(2026, 9, 30)          # recent shipments leave invoices/disputes genuinely in flight at AS_OF
LATEST_INVOICE_DATE_LAG = 5           # invoices are dated at least this many days before AS_OF (so the audit has run)
RENEWAL_DATE = date(2026, 7, 1)       # carriers on a 2-card year switch from card 01 to card 02 here
YEAR_END = date(2026, 12, 31)

PROFILES = {
    "starter": dict(carriers=10, shipments=500, invoices=375),
    "full": dict(carriers=100, shipments=20000, invoices=15000),
}

SERVICES = ["GROUND", "EXPRESS", "ECONOMY"]
SERVICE_MULT = {"GROUND": 1.0, "EXPRESS": 1.8, "ECONOMY": 0.8}
SERVICE_WEIGHTS = {"GROUND": 0.60, "EXPRESS": 0.15, "ECONOMY": 0.25}

# weight tiers: lower bound inclusive, upper exclusive
TIERS = [("T1", 0, 50), ("T2", 50, 150), ("T3", 150, 500), ("T4", 500, 1000), ("T5", 1000, None)]
TIER_MULT = {"T1": 1.0, "T2": 0.80, "T3": 0.62, "T4": 0.50, "T5": 0.42}
TIER_BOUNDARIES = [50, 150, 500, 1000]

REGIONS = {  # rough region centroids (miles) -> deterministic lane distances
    "NE": (1800, 900), "SE": (1500, 200), "MW": (1000, 800),
    "SW": (700, 150), "W": (100, 500), "NW": (150, 900),
}

# (code, description, trigger event, standard amount, requires_evidence)
ACCESSORIALS = [
    ("RESIDENTIAL", "Residential delivery", "RESIDENTIAL_DELIVERY_SCAN", "4.50", True),
    ("LIFTGATE", "Liftgate service", "LIFTGATE_USED", "35.00", True),
    ("APPOINTMENT", "Delivery appointment", "APPOINTMENT_CONFIRMED", "12.00", True),
    ("INSIDE_DELIVERY", "Inside delivery", "INSIDE_DELIVERY_SCAN", "45.00", True),
    ("DETENTION", "Detention / waiting time", "DETENTION_TIMESTAMP", "60.00", True),
    ("REDELIVERY", "Redelivery attempt", "REDELIVERY_SCAN", "30.00", True),
    ("LIMITED_ACCESS", "Limited-access location", "LIMITED_ACCESS_FLAG", "25.00", True),
]
ACC_PROB = {"RESIDENTIAL": 0.18, "LIFTGATE": 0.08, "APPOINTMENT": 0.10, "INSIDE_DELIVERY": 0.04,
            "DETENTION": 0.03, "REDELIVERY": 0.02, "LIMITED_ACCESS": 0.02}

# ---- injected anomaly plan: fraction of invoices ----
ISSUE_RATES = {
    "UNKNOWN_SHIPMENT": 0.008,
    "RATE_CARD_EXPIRED": 0.010,
    "WEIGHT_TIER_MISAPPLIED": 0.025,
    "SURCHARGE_DUPLICATED": 0.015,
    "DUPLICATE_BILLING": 0.025,
    "INVALID_ACCESSORIAL": 0.030,
    "DIM_WEIGHT_MISCALC": 0.020,
    "FUEL_RATE_WRONG": 0.012,
}
CREDIT_EXCEEDS_RATE = 0.04            # fraction of credit notes
BOUNDARY_WEIGHT_PROB = 0.05           # shipments deliberately placed on tier boundaries
BULKY_PROB = 0.25                     # shipments where dim weight > actual weight
SPLIT_CARD_FRACTION = 0.30            # carriers renegotiated mid-year (card 02)

INJECTED_INVOICE_ISSUES = list(ISSUE_RATES)
GT_ISSUE_TYPES = ["NONE"] + INJECTED_INVOICE_ISSUES + ["CREDIT_EXCEEDS_EXCEPTION"]
# priority used to pick the root cause of an invoice (derived exception types never root)
ROOT_PRIORITY = ["UNKNOWN_SHIPMENT", "DUPLICATE_BILLING", "RATE_CARD_EXPIRED", "DIM_WEIGHT_MISCALC",
                 "WEIGHT_TIER_MISAPPLIED", "RATE_MISMATCH", "SURCHARGE_DUPLICATED",
                 "INVALID_ACCESSORIAL", "ACCESSORIAL_RATE_MISMATCH", "FUEL_RATE_WRONG"]
EXCEPTION_TYPES = ROOT_PRIORITY + ["FUEL_ON_BASE_VARIANCE"]

# lifecycle state machines: {from: [to,...]}; None = creation
INVOICE_TRANSITIONS = {None: ["RECEIVED"], "RECEIVED": ["AUDITED"],
                       "AUDITED": ["APPROVED_FOR_PAYMENT", "DISPUTED"],
                       "APPROVED_FOR_PAYMENT": ["PAID"], "DISPUTED": ["RESOLVED"], "RESOLVED": ["PAID"], "PAID": []}
EXCEPTION_TRANSITIONS = {None: ["OPEN"], "OPEN": ["UNDER_REVIEW"], "UNDER_REVIEW": ["APPROVED", "REJECTED"],
                         "APPROVED": ["CREDITED"], "REJECTED": [], "CREDITED": []}
CREDIT_TRANSITIONS = {None: ["DRAFT"], "DRAFT": ["ISSUED"], "ISSUED": ["APPLIED"], "APPLIED": []}

# probability the carrier's rebuttal is accepted (exception REJECTED) by root cause
REBUTTAL_PROB = {"DUPLICATE_BILLING": 0.02, "UNKNOWN_SHIPMENT": 0.05, "SURCHARGE_DUPLICATED": 0.03,
                 "INVALID_ACCESSORIAL": 0.12, "WEIGHT_TIER_MISAPPLIED": 0.10, "DIM_WEIGHT_MISCALC": 0.15,
                 "RATE_CARD_EXPIRED": 0.06, "FUEL_RATE_WRONG": 0.08, "RATE_MISMATCH": 0.10,
                 "ACCESSORIAL_RATE_MISMATCH": 0.10}
TOLERANCE = "0.01"                    # |billed - expected| above this raises an exception
SEVERITY_BANDS = [(10, "LOW"), (50, "MEDIUM"), (None, "HIGH")]   # by absolute variance (USD)
