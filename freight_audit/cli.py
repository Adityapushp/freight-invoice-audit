"""CLI: python -m freight_audit {generate,validate,audit,repro,docs}"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from collections import Counter

from . import config as C
from .audit import evaluate
from .export import export_all, load_tables, load_ground_truth, dictionary_markdown
from .generator import generate
from .validate import validate


def _scale(a):
    p = dict(C.PROFILES[a.profile])
    for k in ("carriers", "shipments", "invoices"):
        if getattr(a, k, None):
            p[k] = getattr(a, k)
    return p


def _gen_to(a, out):
    scale = _scale(a)
    t, gt = generate(a.seed, **scale)
    cmd = f"python -m freight_audit generate --profile {a.profile} --seed {a.seed}" + "".join(
        f" --{k} {getattr(a, k)}" for k in ("carriers", "shipments", "invoices") if getattr(a, k, None))
    return t, gt, export_all(t, gt, out, dict(seed=a.seed, scale=scale, command=cmd))


def _reports(t, gt, out):
    os.makedirs(os.path.join(out, "reports"), exist_ok=True)
    rep = validate(t, gt).summary()
    ev = evaluate(t, gt)
    json.dump(rep, open(os.path.join(out, "reports", "validation_summary.json"), "w"), indent=2, default=str)
    json.dump(ev, open(os.path.join(out, "reports", "evaluation.json"), "w"), indent=2, default=str)
    return rep, ev


def cmd_generate(a):
    out = a.out or os.path.join("data", a.profile)
    if os.path.isdir(out):
        shutil.rmtree(out)
    t, gt, m = _gen_to(a, out)
    rep, ev = _reports(t, gt, out)
    print(f"wrote {out}: {sum(m['row_counts'].values())} rows in {len(m['row_counts'])} tables; seed={a.seed}")
    print(Counter(g["issue_type"] for g in gt if g["issue_type"] != "NONE"))
    print("validation:", "PASS" if rep["passed"] else f"FAIL {rep['failed']}", f"({rep['checks']} checks)")
    print("detection F1:", ev["overall_detection"]["f1"], "| variance explained:", ev["variance_explained"]["rate"])
    return 0 if rep["passed"] else 1


def cmd_validate(a):
    d = a.data or os.path.join("data", a.profile)
    rep = validate(load_tables(d), load_ground_truth(d)).summary()
    for c in rep["details"]:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + (f"  [{c['info']}]" if c["info"] else ""))
        for e in c["examples"]:
            print("     -", e)
    return 0 if rep["passed"] else 1


def cmd_audit(a):
    d = a.data or os.path.join("data", a.profile)
    ev = evaluate(load_tables(d), load_ground_truth(d))
    print(json.dumps(ev, indent=2, default=str))
    return 0


def cmd_repro(a):
    """Generate twice with the same seed into temp dirs; compare row counts and file checksums."""
    res = []
    for _ in range(2):
        tmp = tempfile.mkdtemp()
        _, _, m = _gen_to(a, tmp)
        res.append(m)
        shutil.rmtree(tmp)
    same = res[0]["row_counts"] == res[1]["row_counts"] and res[0]["sha256"] == res[1]["sha256"]
    out = dict(seed=a.seed, scale=_scale(a), identical=same, run_a_row_counts=res[0]["row_counts"], run_b_row_counts=res[1]["row_counts"],
               files_compared=len(res[0]["sha256"]), sha256_run_a=res[0]["sha256"], sha256_run_b=res[1]["sha256"])
    os.makedirs("reports", exist_ok=True)
    json.dump(out, open(os.path.join("reports", f"reproducibility_{a.profile}.json"), "w"), indent=2)
    print(f"{len(res[0]['sha256'])} files compared across 2 runs -> {'IDENTICAL' if same else 'DIFFERENT'}")
    return 0 if same else 1


def cmd_docs(a):
    os.makedirs("docs", exist_ok=True)
    open("docs/DATA_DICTIONARY.md", "w").write(dictionary_markdown())
    print("wrote docs/DATA_DICTIONARY.md")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="freight_audit", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("generate", cmd_generate), ("validate", cmd_validate), ("audit", cmd_audit), ("repro", cmd_repro), ("docs", cmd_docs)]:
        p = sub.add_parser(name)
        p.add_argument("--profile", choices=list(C.PROFILES), default="starter")
        p.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
        for k in ("carriers", "shipments", "invoices"):
            p.add_argument(f"--{k}", type=int)
        p.add_argument("--out"); p.add_argument("--data")
        p.set_defaults(fn=fn)
    a = ap.parse_args(argv)
    return a.fn(a)

if __name__ == "__main__":
    sys.exit(main())
