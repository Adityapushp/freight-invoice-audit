-- Generated from freight_audit/schema.py. Foreign keys are declared but seed.sql disables enforcement:
-- UNKNOWN_SHIPMENT invoices intentionally reference a missing shipment (labelled in ground_truth).

CREATE TABLE carriers (
  carrier_id TEXT NOT NULL,
  carrier_name TEXT NOT NULL,
  scac_code TEXT NOT NULL,
  service_mode TEXT NOT NULL,
  onboarded_date DATE NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (carrier_id),
  CHECK (service_mode IS NULL OR service_mode IN ('LTL','PARCEL','TL')),
  CHECK (status IS NULL OR status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE lanes (
  lane_id TEXT NOT NULL,
  origin_region TEXT NOT NULL,
  dest_region TEXT NOT NULL,
  distance_miles INTEGER NOT NULL,
  PRIMARY KEY (lane_id),
  CHECK (origin_region IS NULL OR origin_region IN ('NE','SE','MW','SW','W','NW')),
  CHECK (dest_region IS NULL OR dest_region IN ('NE','SE','MW','SW','W','NW'))
);

CREATE TABLE rate_cards (
  rate_card_id TEXT NOT NULL,
  carrier_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NOT NULL,
  fuel_surcharge_rate DECIMAL(14,4) NOT NULL,
  dim_divisor INTEGER NOT NULL,
  min_charge DECIMAL(14,2) NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (rate_card_id),
  FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id),
  CHECK (dim_divisor IS NULL OR dim_divisor IN (139,166)),
  CHECK (currency IS NULL OR currency IN ('USD')),
  CHECK (status IS NULL OR status IN ('ACTIVE','EXPIRED'))
);

CREATE TABLE rate_card_rates (
  rate_line_id TEXT NOT NULL,
  rate_card_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  service TEXT NOT NULL,
  weight_tier TEXT NOT NULL,
  min_weight_lb INTEGER NOT NULL,
  max_weight_lb INTEGER,
  rate_per_lb DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (rate_line_id),
  FOREIGN KEY (rate_card_id) REFERENCES rate_cards(rate_card_id),
  FOREIGN KEY (lane_id) REFERENCES lanes(lane_id),
  CHECK (service IS NULL OR service IN ('GROUND','EXPRESS','ECONOMY')),
  CHECK (weight_tier IS NULL OR weight_tier IN ('T1','T2','T3','T4','T5'))
);

CREATE TABLE accessorials (
  accessorial_code TEXT NOT NULL,
  description TEXT NOT NULL,
  trigger_event TEXT NOT NULL,
  standard_amount DECIMAL(14,2) NOT NULL,
  requires_evidence INTEGER NOT NULL,
  PRIMARY KEY (accessorial_code)
);

CREATE TABLE rate_card_accessorials (
  rca_id TEXT NOT NULL,
  rate_card_id TEXT NOT NULL,
  accessorial_code TEXT NOT NULL,
  amount DECIMAL(14,2) NOT NULL,
  PRIMARY KEY (rca_id),
  FOREIGN KEY (rate_card_id) REFERENCES rate_cards(rate_card_id),
  FOREIGN KEY (accessorial_code) REFERENCES accessorials(accessorial_code)
);

CREATE TABLE shipments (
  shipment_id TEXT NOT NULL,
  carrier_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  service TEXT NOT NULL,
  ship_date DATE NOT NULL,
  delivered_at TIMESTAMP NOT NULL,
  pieces INTEGER NOT NULL,
  length_in INTEGER NOT NULL,
  width_in INTEGER NOT NULL,
  height_in INTEGER NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (shipment_id),
  FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id),
  FOREIGN KEY (lane_id) REFERENCES lanes(lane_id),
  CHECK (service IS NULL OR service IN ('GROUND','EXPRESS','ECONOMY')),
  CHECK (status IS NULL OR status IN ('DELIVERED'))
);

CREATE TABLE shipment_legs (
  leg_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  leg_seq INTEGER NOT NULL,
  from_node TEXT NOT NULL,
  to_node TEXT NOT NULL,
  departed_at TIMESTAMP NOT NULL,
  arrived_at TIMESTAMP NOT NULL,
  leg_status TEXT NOT NULL,
  PRIMARY KEY (leg_id),
  FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id),
  CHECK (leg_status IS NULL OR leg_status IN ('COMPLETED'))
);

CREATE TABLE weight_measurements (
  measurement_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  source TEXT NOT NULL,
  weight_lb DECIMAL(14,1) NOT NULL,
  is_authoritative INTEGER NOT NULL,
  measured_at TIMESTAMP NOT NULL,
  PRIMARY KEY (measurement_id),
  FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id),
  CHECK (source IS NULL OR source IN ('SHIPPER_DECLARED','ORIGIN_SCALE','CARRIER_REWEIGH'))
);

CREATE TABLE shipment_accessorials (
  sa_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  accessorial_code TEXT NOT NULL,
  event_at TIMESTAMP NOT NULL,
  evidence_ref TEXT NOT NULL,
  PRIMARY KEY (sa_id),
  FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id),
  FOREIGN KEY (accessorial_code) REFERENCES accessorials(accessorial_code)
);

CREATE TABLE freight_invoices (
  invoice_id TEXT NOT NULL,
  carrier_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  carrier_invoice_number TEXT NOT NULL,
  rate_card_id_applied TEXT NOT NULL,
  invoice_date DATE NOT NULL,
  due_date DATE NOT NULL,
  currency TEXT NOT NULL,
  base_amount DECIMAL(14,2) NOT NULL,
  fuel_amount DECIMAL(14,2) NOT NULL,
  accessorial_amount DECIMAL(14,2) NOT NULL,
  total_amount DECIMAL(14,2) NOT NULL,
  current_status TEXT NOT NULL,
  PRIMARY KEY (invoice_id),
  FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id),
  FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id),
  FOREIGN KEY (rate_card_id_applied) REFERENCES rate_cards(rate_card_id),
  CHECK (currency IS NULL OR currency IN ('USD')),
  CHECK (current_status IS NULL OR current_status IN ('RECEIVED','AUDITED','APPROVED_FOR_PAYMENT','DISPUTED','RESOLVED','PAID'))
);

CREATE TABLE invoice_lines (
  line_id TEXT NOT NULL,
  invoice_id TEXT NOT NULL,
  line_seq INTEGER NOT NULL,
  line_type TEXT NOT NULL,
  accessorial_code TEXT,
  description TEXT NOT NULL,
  billed_weight_lb INTEGER,
  weight_tier TEXT,
  unit_rate DECIMAL(14,4),
  amount DECIMAL(14,2) NOT NULL,
  PRIMARY KEY (line_id),
  FOREIGN KEY (invoice_id) REFERENCES freight_invoices(invoice_id),
  CHECK (line_type IS NULL OR line_type IN ('BASE','FUEL','ACCESSORIAL')),
  FOREIGN KEY (accessorial_code) REFERENCES accessorials(accessorial_code),
  CHECK (weight_tier IS NULL OR weight_tier IN ('T1','T2','T3','T4','T5'))
);

CREATE TABLE audit_exceptions (
  exception_id TEXT NOT NULL,
  invoice_id TEXT NOT NULL,
  line_id TEXT,
  exception_type TEXT NOT NULL,
  billed_amount DECIMAL(14,2) NOT NULL,
  expected_amount DECIMAL(14,2) NOT NULL,
  variance_amount DECIMAL(14,2) NOT NULL,
  severity TEXT NOT NULL,
  explanation TEXT NOT NULL,
  detected_at TIMESTAMP NOT NULL,
  current_status TEXT NOT NULL,
  PRIMARY KEY (exception_id),
  FOREIGN KEY (invoice_id) REFERENCES freight_invoices(invoice_id),
  FOREIGN KEY (line_id) REFERENCES invoice_lines(line_id),
  CHECK (exception_type IS NULL OR exception_type IN ('UNKNOWN_SHIPMENT','DUPLICATE_BILLING','RATE_CARD_EXPIRED','DIM_WEIGHT_MISCALC','WEIGHT_TIER_MISAPPLIED','RATE_MISMATCH','SURCHARGE_DUPLICATED','INVALID_ACCESSORIAL','ACCESSORIAL_RATE_MISMATCH','FUEL_RATE_WRONG','FUEL_ON_BASE_VARIANCE')),
  CHECK (severity IS NULL OR severity IN ('LOW','MEDIUM','HIGH')),
  CHECK (current_status IS NULL OR current_status IN ('OPEN','UNDER_REVIEW','APPROVED','REJECTED','CREDITED'))
);

CREATE TABLE credit_notes (
  credit_note_id TEXT NOT NULL,
  exception_id TEXT NOT NULL,
  invoice_id TEXT NOT NULL,
  carrier_id TEXT NOT NULL,
  credit_amount DECIMAL(14,2) NOT NULL,
  currency TEXT NOT NULL,
  issued_date DATE,
  current_status TEXT NOT NULL,
  PRIMARY KEY (credit_note_id),
  FOREIGN KEY (exception_id) REFERENCES audit_exceptions(exception_id),
  FOREIGN KEY (invoice_id) REFERENCES freight_invoices(invoice_id),
  FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id),
  CHECK (currency IS NULL OR currency IN ('USD')),
  CHECK (current_status IS NULL OR current_status IN ('DRAFT','ISSUED','APPLIED'))
);

CREATE TABLE invoice_events (
  event_id TEXT NOT NULL,
  invoice_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  event_at TIMESTAMP NOT NULL,
  actor TEXT NOT NULL,
  note TEXT,
  PRIMARY KEY (event_id),
  FOREIGN KEY (invoice_id) REFERENCES freight_invoices(invoice_id),
  CHECK (from_status IS NULL OR from_status IN ('RECEIVED','AUDITED','APPROVED_FOR_PAYMENT','DISPUTED','RESOLVED','PAID')),
  CHECK (to_status IS NULL OR to_status IN ('RECEIVED','AUDITED','APPROVED_FOR_PAYMENT','DISPUTED','RESOLVED','PAID')),
  CHECK (actor IS NULL OR actor IN ('SYSTEM','AUDITOR','CARRIER','AP_TEAM'))
);

CREATE TABLE exception_events (
  event_id TEXT NOT NULL,
  exception_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  event_at TIMESTAMP NOT NULL,
  actor TEXT NOT NULL,
  note TEXT,
  PRIMARY KEY (event_id),
  FOREIGN KEY (exception_id) REFERENCES audit_exceptions(exception_id),
  CHECK (from_status IS NULL OR from_status IN ('OPEN','UNDER_REVIEW','APPROVED','REJECTED','CREDITED')),
  CHECK (to_status IS NULL OR to_status IN ('OPEN','UNDER_REVIEW','APPROVED','REJECTED','CREDITED')),
  CHECK (actor IS NULL OR actor IN ('SYSTEM','AUDITOR','CARRIER','AP_TEAM'))
);

CREATE TABLE credit_note_events (
  event_id TEXT NOT NULL,
  credit_note_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  event_at TIMESTAMP NOT NULL,
  actor TEXT NOT NULL,
  note TEXT,
  PRIMARY KEY (event_id),
  FOREIGN KEY (credit_note_id) REFERENCES credit_notes(credit_note_id),
  CHECK (from_status IS NULL OR from_status IN ('DRAFT','ISSUED','APPLIED')),
  CHECK (to_status IS NULL OR to_status IN ('DRAFT','ISSUED','APPLIED')),
  CHECK (actor IS NULL OR actor IN ('SYSTEM','AUDITOR','CARRIER','AP_TEAM'))
);
