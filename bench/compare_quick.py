"""`make reproduce-quick` acceptance: the reduced re-runs in build/ must agree with the committed results/.

  * M1: for every reduced P_L point, the 95% Clopper-Pearson interval of each decoder overlaps the committed one
        (different seeds and fewer shots, so exact equality is not expected).
  * M2: quick co-simulation total mismatches == 0.
  * M4: every reduced runtime row is bit-exact across all builds/engines.
Exit code non-zero on any disagreement; writes build/rq/compare.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def J(p: Path):
    return json.loads(p.read_text())["data"]


def main() -> int:
    rq = ROOT / "build/rq"
    checks, bad = [], []
    for f in sorted((rq / "M1").glob("pl_*.json")):
        ref = ROOT / "results/M1/pl" / f.name
        if not ref.exists():
            bad.append(f"no committed point for {f.name}")
            continue
        a, b = J(f)["decoders"], J(ref)["decoders"]
        for k in sorted(set(a) & set(b)):
            lo1, hi1 = a[k]["ci95"]
            lo2, hi2 = b[k]["ci95"]
            ok = lo1 <= hi2 and lo2 <= hi1
            checks.append({"check": f"M1 {f.stem} {k}", "quick": a[k]["pl"], "committed": b[k]["pl"], "ok": ok})
            if not ok:
                bad.append(checks[-1]["check"])
    cs = ROOT / "build/cosim_quick/summary.json"
    mm = J(cs)["total_mismatches"] if cs.exists() else None
    checks.append({"check": "M2 cosim-quick mismatches", "value": mm, "ok": mm == 0})
    if mm != 0:
        bad.append("cosim-quick")
    m4 = rq / "m4.json"
    if m4.exists():
        for r in J(m4):
            checks.append({"check": f"M4 d={r['d']} bit-exact", "ok": r["bit_exact"]})
            if not r["bit_exact"]:
                bad.append(f"M4 d={r['d']}")
    else:
        bad.append("missing build/rq/m4.json")
    rq.mkdir(parents=True, exist_ok=True)
    (rq / "compare.json").write_text(json.dumps({"checks": checks, "failures": bad}, indent=1))
    for c in checks:
        print(("OK  " if c["ok"] else "BAD ") + c["check"])
    print("reproduce-quick:", "PASS" if not bad else f"FAIL {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
