"""Exporters (CSV / JSON / SQL), typed CSV loader, manifest with checksums, data-dictionary markdown."""
import csv
import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal

from . import config as C, schema as S
from . import __version__

CSV_DIALECT = dict(lineterminator="\n")


def fmt(f, v):
    if v is None:
        return None
    if f.type == "dec":
        return str(Decimal(v).quantize(Decimal(1).scaleb(-f.dp)))
    if f.type == "dt":
        return v.isoformat(timespec="seconds")
    if f.type == "date":
        return v.isoformat()
    if f.type == "bool":
        return "true" if v else "false"
    return str(v) if f.type == "str" else int(v)


def parse(f, s):
    if s is None or s == "":
        return None
    return {"dec": Decimal, "int": int, "date": date.fromisoformat, "dt": datetime.fromisoformat,
            "bool": lambda x: x == "true", "str": str}[f.type](s)


def sort_rows(tb, rows):
    return sorted(rows, key=lambda r: r[tb.order_by or tb.pk])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sql_lit(f, v):
    v = fmt(f, v)
    if v is None:
        return "NULL"
    if f.type in ("int",):
        return str(v)
    if f.type == "dec":
        return v
    if f.type == "bool":
        return "1" if v == "true" else "0"
    return "'" + str(v).replace("'", "''") + "'"


def ddl():
    sqlt = {"str": "TEXT", "int": "INTEGER", "date": "DATE", "dt": "TIMESTAMP", "bool": "INTEGER"}
    out = ["-- Generated from freight_audit/schema.py. Foreign keys are declared but seed.sql disables enforcement:",
           "-- UNKNOWN_SHIPMENT invoices intentionally reference a missing shipment (labelled in ground_truth).", ""]
    for tb in S.TABLES:
        cols, cons = [], [f"PRIMARY KEY ({tb.pk})"]
        for f in tb.fields:
            t = f"DECIMAL(14,{f.dp})" if f.type == "dec" else sqlt[f.type]
            nn = "" if (not f.required and f.name != tb.pk) else " NOT NULL"
            cols.append(f"  {f.name} {t}{nn}")
            if f.enum:
                vals = ",".join(f"'{e}'" if isinstance(e, str) else str(e) for e in f.enum)
                cons.append(f"CHECK ({f.name} IS NULL OR {f.name} IN ({vals}))")
            if f.fk:
                rt, rc = f.fk.split(".")
                cons.append(f"FOREIGN KEY ({f.name}) REFERENCES {rt}({rc})")
        out.append(f"CREATE TABLE {tb.name} (\n" + ",\n".join(cols + ["  " + c for c in cons]) + "\n);\n")
    return "\n".join(out)


def export_all(t, gt, out_dir, meta):
    """Write all artefacts. Returns the manifest dict. Output is byte-for-byte deterministic."""
    for sub in ("csv", "json", "sql", "ground_truth"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    counts = {}
    for tb in S.TABLES:
        rows = sort_rows(tb, t[tb.name])
        counts[tb.name] = len(rows)
        recs = [{f.name: fmt(f, r.get(f.name)) for f in tb.fields} for r in rows]
        with open(os.path.join(out_dir, "csv", f"{tb.name}.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, **CSV_DIALECT)
            w.writerow([f.name for f in tb.fields])
            for rec in recs:
                w.writerow(["" if v is None else v for v in rec.values()])
        with open(os.path.join(out_dir, "json", f"{tb.name}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(recs, fh, indent=0, ensure_ascii=False)
            fh.write("\n")
    with open(os.path.join(out_dir, "sql", "schema.sql"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ddl())
    with open(os.path.join(out_dir, "sql", "seed.sql"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("PRAGMA foreign_keys=OFF;\nBEGIN;\n")
        for tb in S.TABLES:
            for r in sort_rows(tb, t[tb.name]):
                fh.write(f"INSERT INTO {tb.name} ({','.join(f.name for f in tb.fields)}) VALUES ("
                         + ",".join(sql_lit(f, r.get(f.name)) for f in tb.fields) + ");\n")
        fh.write("COMMIT;\n")
    # ground truth: separate directory, never read by the generator's input tables or the auditor
    gt_sorted = sorted(gt, key=lambda r: (r["entity_type"], r["entity_id"]))
    def g(v): return str(v) if v is not None else ""
    with open(os.path.join(out_dir, "ground_truth", "ground_truth.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, **CSV_DIALECT)
        w.writerow(S.GROUND_TRUTH_FIELDS)
        for r in gt_sorted:
            w.writerow([g(r[k]) for k in S.GROUND_TRUTH_FIELDS])
    with open(os.path.join(out_dir, "ground_truth", "ground_truth.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump([{k: g(r[k]) for k in S.GROUND_TRUTH_FIELDS} for r in gt_sorted], fh, indent=0)
        fh.write("\n")
    files = {}
    for root, _, names in os.walk(out_dir):
        for n in sorted(names):
            if n in ("manifest.json",) or root.endswith("reports"):
                continue
            p = os.path.join(root, n)
            files[os.path.relpath(p, out_dir).replace(os.sep, "/")] = sha256(p)
    manifest = dict(
        generator_version=__version__, seed=meta["seed"], scale=meta["scale"], as_of=str(C.AS_OF),
        command=meta["command"], row_counts=counts, ground_truth_rows=len(gt),
        sources=[dict(name="Synthetic data", provenance="Generated entirely by freight_audit.generator from the fixed seed.",
                      external_data_used=False, license="Original synthetic data; no third-party data, no personal data",
                      note="Rate structure (lane x weight tier x service, dim divisors 139/166, accessorial types) is inspired by public "
                           "LTL/parcel tariff conventions; no tariff values were copied.")],
        sha256=dict(sorted(files.items())))
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def load_tables(out_dir):
    """Typed load of the INPUT tables from CSV (ground truth is deliberately not loaded here)."""
    t = {}
    for tb in S.TABLES:
        with open(os.path.join(out_dir, "csv", f"{tb.name}.csv"), newline="", encoding="utf-8") as fh:
            t[tb.name] = [{f.name: parse(f, row[f.name]) for f in tb.fields} for row in csv.DictReader(fh)]
    return t


def load_ground_truth(out_dir):
    rows = []
    with open(os.path.join(out_dir, "ground_truth", "ground_truth.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            for k in ("billed_total", "expected_total", "expected_variance"):
                r[k] = Decimal(r[k])
            rows.append(r)
    return rows


def dictionary_markdown():
    L = ["# Data dictionary", "",
         "_Generated from `freight_audit/schema.py` by `python -m freight_audit docs`. Do not edit by hand._", "",
         "Conventions: dates ISO-8601; timestamps naive UTC; money in USD with 2 dp; rates 4 dp; weights in lb. "
         "Every table has a single-column primary key. History is kept in append-only `*_events` tables; `current_status` columns are derived from the last event.", "",
         "## Entity relationship summary", ""]
    for tb in S.TABLES:
        if tb.relations:
            L.append(f"- **{tb.entity}** (`{tb.name}`): {tb.relations}")
    L += ["", "Optional relationships: `audit_exceptions.line_id` (null for invoice-level findings), `credit_notes` (only for approved exceptions), "
          "`invoice_lines.accessorial_code` (only ACCESSORIAL lines). Effective dating: `rate_cards.effective_from/to` select the contract by `shipments.ship_date`.", ""]
    for tb in S.TABLES:
        L += [f"## {tb.entity} — `{tb.name}`", "", tb.desc, "", f"Primary key: `{tb.pk}`", "",
              "| Field | Type | Req | Unit | Allowed values / rule | Unique | FK |", "|---|---|---|---|---|---|---|"]
        for f in tb.fields:
            allowed = (", ".join(map(str, f.enum)) + ". " if f.enum else "") + f.desc
            L.append(f"| `{f.name}` | {f.type}{'(' + str(f.dp) + ')' if f.type == 'dec' else ''} | {'Y' if f.required else 'N'} | {f.unit} | {allowed} | "
                     f"{'Y' if f.unique or f.name == tb.pk else ''} | {f.fk or ''} |")
        L.append("")
    L += ["## ground_truth (separate file, never an input feature)", "",
          "| Field | Meaning |", "|---|---|",
          "| entity_type | INVOICE (every invoice) or CREDIT_NOTE (every credit note) |",
          "| entity_id | FINV-… or CN-… |", "| invoice_id | Parent invoice |",
          f"| issue_type | One of {', '.join(C.GT_ISSUE_TYPES)} |",
          "| expected_decision | PAY / DISPUTE for invoices; ISSUE_AT_VARIANCE / CAP_AT_EXCEPTION_AMOUNT for credits |",
          "| billed_total, expected_total, expected_variance | Computed by the generator from the documented rules at injection time |",
          "| note | Short human description of the injection |", ""]
    return "\n".join(L)
