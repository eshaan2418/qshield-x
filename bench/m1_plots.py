"""M1 analysis: P_L curves with 95% CIs, threshold crossings, latency table."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from bench.stats import crossing  # noqa: E402

M1 = ROOT / "results/M1"
LABEL = {"pymatching": "PyMatching 2.4 (MWPM)", "qsxuf-unweighted": "QSX-UF unweighted", "qsxuf-q5": "QSX-UF q5"}


def main() -> None:
    pts = [json.loads(f.read_text())["data"] for f in sorted((M1 / "pl").glob("pl_*.json"))]
    curves: dict = defaultdict(lambda: defaultdict(list))
    for r in pts:
        for k, v in r["decoders"].items():
            curves[k][r["d"]].append((r["p"], v["pl"], v["ci95"][0], v["ci95"][1], v["errors"], r["shots"]))
    figs = M1 / "figs"
    figs.mkdir(parents=True, exist_ok=True)
    fig, axs = plt.subplots(1, len(curves), figsize=(5 * len(curves), 4.2), sharey=True)
    summary = {"thresholds": {}, "points": len(pts)}
    for ax, (k, byd) in zip(axs, sorted(curves.items())):
        for d in sorted(byd):
            s = sorted(byd[d])
            ps = [x[0] for x in s]
            pl = [x[1] for x in s]
            lo = [max(x[1] - x[2], 0) for x in s]
            hi = [x[3] - x[1] for x in s]
            ax.errorbar(ps, pl, yerr=[lo, hi], marker="o", ms=3, capsize=2, label=f"d={d}")
        ds = sorted(byd)
        cr = {}
        for d0, d1 in zip(ds, ds[1:]):
            a = sorted(byd[d0])
            b = sorted(byd[d1])
            c = crossing([x[0] for x in a], [x[1] for x in a], [x[1] for x in b])
            cr[f"{d0}-{d1}"] = c
        summary["thresholds"][k] = cr
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(LABEL.get(k, k))
        ax.set_xlabel("physical error rate p")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    axs[0].set_ylabel("logical error per d-round block, P_L (95% CI)")
    fig.tight_layout()
    fig.savefig(figs / "pl_vs_p.png", dpi=150)

    # ratio plot UF/PM
    fig, ax = plt.subplots(figsize=(5, 4))
    for w in ["qsxuf-unweighted", "qsxuf-q5"]:
        for d in sorted(curves[w]):
            a = dict((x[0], x[1]) for x in curves[w][d])
            b = dict((x[0], x[1]) for x in curves["pymatching"][d])
            ps = sorted(p for p in a if b.get(p, 0) > 0)
            ax.plot(ps, [a[p] / b[p] for p in ps], marker="o" if w.endswith("q5") else "x", ms=3,
                    ls="-" if w.endswith("q5") else "--", label=f"{LABEL[w]} d={d}")
    ax.axhline(1, color="k", lw=0.8)
    ax.set_xscale("log")
    ax.set_xlabel("p")
    ax.set_ylabel("P_L(QSX-UF) / P_L(PyMatching)")
    ax.legend(fontsize=6, ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figs / "pl_ratio.png", dpi=150)

    lat_f = M1 / "latency.json"
    if lat_f.exists():
        rows = json.loads(lat_f.read_text())["data"]
        fig, ax = plt.subplots(figsize=(6, 4))
        for k in LABEL:
            for p in sorted({r["p"] for r in rows}):
                rr = sorted([r for r in rows if r["decoder"] == k and r["p"] == p], key=lambda r: r["d"])
                if rr:
                    ax.plot([r["d"] for r in rr], [r["lat_ns_p99"] / 1000 for r in rr], marker="o", ms=3,
                            label=f"{LABEL[k]} p={p}")
        ax.set_yscale("log")
        ax.set_xlabel("distance d")
        ax.set_ylabel("p99 latency per d-round block (µs, 1 CPU thread)")
        ax.legend(fontsize=6)
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        fig.savefig(figs / "cpu_latency_p99.png", dpi=150)
        summary["latency_table"] = [{k: r[k] for k in ("d", "p", "decoder", "lat_ns_p50", "lat_ns_p99",
                                                       "throughput_shots_per_s")} for r in rows]
    write_result(M1 / "summary.json", summary, {"source": "results/M1/pl/*.json, results/M1/latency.json"}, None)
    print(json.dumps(summary["thresholds"], indent=1))


if __name__ == "__main__":
    main()
