"""M2: where the RTL core's cycles go (stage: sim, cycle-exact HwModel).

Per shot, with R growth rounds, NCH = ceil(V / LANES) and PIPE in {0, 1}, the FSM spends
  label  = LABEL iterations + (R+1)*PIPE          (min-label propagation, R+1 phases)
  scans  = (R+1) * 2*NCH                          (cluster parity/boundary + activity broadcast, LANES per cycle)
  ctrl   = (R+1) [CHK] + R [GROW] + 1 [DINIT] + 1 [PEH]
  dist   = DIST iterations + PIPE                 (BFS distances)
  peel   = PEEL iterations                        (self-timed peeling)
The script asserts label+scans+ctrl+dist+peel == cycles for every OK shot, so the decomposition is exact.
Output: results/M2/cycle_breakdown.json, results/M2/figs/cycle_breakdown.png|pdf
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
import qsxdec  # noqa: E402

from bench import plotstyle  # noqa: E402
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build  # noqa: E402

PARTS = ["label", "scans", "ctrl", "dist", "peel"]


def main() -> None:
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5,7,9")
    ap.add_argument("--p", type=float, default=0.003)
    ap.add_argument("--lanes", default="8,32,V")
    ap.add_argument("--shots", type=int, default=50_000)
    ap.add_argument("--seed", type=int, default=3003)
    a = ap.parse_args()
    rows = []
    for d in map(int, a.distances.split(",")):
        c, g = build(d, a.p, weights="q5")
        gp = ROOT / "build" / "m2hw" / f"bd_d{d}.qsxg"
        gp.parent.mkdir(parents=True, exist_ok=True)
        g.write(str(gp))
        dets = c.compile_detector_sampler(seed=a.seed + d).sample(a.shots).astype(np.uint8)
        dec = qsxdec.Decoder(str(gp))
        for ls in a.lanes.split(","):
            L = dec.V if ls == "V" else int(ls)
            for P in (0, 1):
                _, st, cyc, parts = dec.decode_batch_hw(dets, lanes=L, pipe=P, breakdown=True)
                ok = st == 0
                R, li, di, pi = (parts[ok, k].astype(np.int64) for k in range(4))
                nch = math.ceil(dec.V / L)
                comp = {"label": li + (R + 1) * P, "scans": (R + 1) * 2 * nch, "ctrl": (R + 1) + R + 2,
                        "dist": di + P, "peel": pi}
                total = sum(comp.values())
                assert np.array_equal(total, cyc[ok].astype(np.int64)), "cycle decomposition mismatch"
                rows.append({"d": d, "p": a.p, "lanes": L, "lanes_label": ls, "pipe": P, "shots": int(ok.sum()),
                             "mean_cycles": float(cyc[ok].mean()),
                             "mean": {k: float(v.mean()) for k, v in comp.items()},
                             "share": {k: float(v.sum() / total.sum()) for k, v in comp.items()},
                             "mean_growth_rounds": float(R.mean()), "stage": "sim (cycle-exact HwModel)"})
                print(d, ls, P, {k: round(v, 2) for k, v in rows[-1]["share"].items()}, flush=True)
    write_result(ROOT / "results/M2/cycle_breakdown.json", rows, vars(a), a.seed)

    plotstyle.apply()
    sel = [r for r in rows if r["pipe"] == 0]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    labels = [f"d={r['d']}\nL={r['lanes_label']}" for r in sel]
    left = np.zeros(len(sel))
    for i, k in enumerate(PARTS):
        v = np.array([r["mean"][k] for r in sel])
        ax.barh(range(len(sel)), v, left=left, color=plotstyle.SERIES[i], label=k, height=0.7,
                edgecolor=plotstyle.SURFACE, linewidth=1.0, zorder=3)
        left += v
    ax.set_yticks(range(len(sel)), labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel(f"mean core cycles per decode (cycle-exact model, p={a.p}, PIPE=0)")
    ax.legend(ncol=5, loc="lower right", fontsize=7)
    plotstyle.save(fig, ROOT / "results/M2/figs/cycle_breakdown.png")


if __name__ == "__main__":
    main()
