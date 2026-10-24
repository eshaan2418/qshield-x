"""Regenerate every figure used by the paper from results/ (no experiment is re-run here).

M1: bench/m1_plots.py      -> results/M1/figs/
M2: bench/m2_report.py     -> results/M2/figs/ (+ results/M2/report.json)
M4: runtime comparison     -> results/M4/figs/runtime.png, warmup.png
M5: V8 patch before/after  -> results/M5/figs/anytrue_fusion.png
M6: GNN vs UF vs MWPM, adaptive policy -> results/M6/figs/
M7: privacy-utility        -> results/M7/figs/privacy_utility.png
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench import m1_plots, m2_report, plotstyle  # noqa: E402

R = ROOT / "results"


def J(p):
    return json.loads((R / p).read_text())["data"]


def m4() -> None:
    import matplotlib.pyplot as plt

    rows = J("M4/runtime.json")
    figs = R / "M4/figs"
    figs.mkdir(parents=True, exist_ok=True)
    order = ["native-O3-neon", "native-O3-word", "native-novec-word", "d8-simd-default", "d8-scalar-default",
             "d8-simd-liftoff-only", "d8-scalar-liftoff-only", "chrome-simd-default", "chrome-scalar-default"]
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    w = 0.8 / len(rows)
    for i, r in enumerate(rows):
        by = {x["label"]: x for x in r["runs"]}
        labs = [k for k in order if k in by]
        ax.barh([j + (i - (len(rows) - 1) / 2) * w for j in range(len(labs))],
                [by[k]["steady_ns_per_shot"] for k in labs], height=w * 0.9, color=plotstyle.SERIES[i],
                label=f"d={r['d']}", zorder=3)
    ax.set_yticks(range(len(labs)), labs)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("steady-state decode time per d-round block (ns, best of 5 passes)")
    ax.legend()
    plotstyle.save(fig, figs / "runtime.png")
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    r = rows[-1]
    for i, lab in enumerate(["d8-simd-default", "d8-simd-liftoff-only", "chrome-simd-default", "node-simd"]):
        x = next((x for x in r["runs"] if x["label"] == lab), None)
        if x and "warmup_ns_per_shot" in x:
            ax.plot(range(1, len(x["warmup_ns_per_shot"]) + 1), x["warmup_ns_per_shot"], label=lab, ms=3,
                    **plotstyle.style(i))
    ax.set_yscale("log")
    ax.set_xlabel("call index (500 blocks per call)")
    ax.set_ylabel(f"ns per block, d={r['d']}")
    ax.legend()
    plotstyle.save(fig, figs / "warmup.png")


def m5() -> None:
    import matplotlib.pyplot as plt

    rows = J("M5/anytrue_fusion.json")
    figs = R / "M5/figs"
    figs.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    labs = [f"{r['workload']}\n{r['metric'].replace('_ns_per_shot', '')}" if "qsx" in r["workload"]
            else f"micro, {r['nonzero_block_fraction']:g} non-zero" for r in rows]
    y = [r["ratio"] for r in rows]
    lo = [r["ratio"] - r["ratio_ci95"][0] for r in rows]
    hi = [r["ratio_ci95"][1] - r["ratio"] for r in rows]
    ax.errorbar(y, range(len(rows)), xerr=[lo, hi], fmt="o", color=plotstyle.SERIES[0], capsize=3, zorder=3)
    ax.axvline(1.0, color=plotstyle.INK2, lw=0.8)
    ax.set_yticks(range(len(rows)), labs, fontsize=6)
    ax.invert_yaxis()
    ax.set_xlabel("time ratio patched / unpatched d8 (median, bootstrap 95% CI)")
    plotstyle.save(fig, figs / "anytrue_fusion.png")


def m6() -> None:
    import matplotlib.pyplot as plt

    figs = R / "M6/figs"
    figs.mkdir(parents=True, exist_ok=True)
    fig, axs = plt.subplots(1, 2, figsize=(7.6, 3.4), sharey=False)
    for ax, d in zip(axs, (3, 5)):
        ev = J(f"M6/gnn_d{d}/eval.json")
        for i, (k, lab) in enumerate((("pymatching", "PyMatching"), ("qsxuf-q5", "QSX-UF q5"), ("gnn", "GNN"))):
            ps = [e["p"] for e in ev]
            pl = [e[k]["pl"] for e in ev]
            err = [[e[k]["pl"] - e[k]["ci95"][0] for e in ev], [e[k]["ci95"][1] - e[k]["pl"] for e in ev]]
            ax.errorbar(ps, pl, yerr=err, label=lab, capsize=2, ms=4, **plotstyle.style(i))
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"d={d}")
        ax.set_xlabel("physical error rate p")
    axs[0].set_ylabel("P_L per d-round block (95% CI)")
    axs[0].legend()
    plotstyle.save(fig, figs / "gnn_pl.png")
    ad = J("M6/adaptive_d5.json")["results"]
    strategies = ["fixed-UF", "adaptive-UF", "oracle-UF", "fixed-PM", "adaptive-hybrid", "oracle-PM"]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    sc = list(ad)
    w = 0.8 / len(strategies)
    for i, s in enumerate(strategies):
        xs = [j + (i - (len(strategies) - 1) / 2) * w for j in range(len(sc))]
        v = [ad[k]["strategies"][s]["pl"] for k in sc]
        e = [[ad[k]["strategies"][s]["pl"] - ad[k]["strategies"][s]["ci95"][0] for k in sc],
             [ad[k]["strategies"][s]["ci95"][1] - ad[k]["strategies"][s]["pl"] for k in sc]]
        ax.bar(xs, v, width=w * 0.9, color=plotstyle.SERIES[i], label=s, zorder=3, yerr=e, capsize=1.5,
               error_kw={"elinewidth": 0.7, "ecolor": plotstyle.INK2})
    ax.set_xticks(range(len(sc)), sc)
    ax.set_ylabel("P_L per d-round block, d=5 (95% CI)")
    ax.legend(ncol=3, fontsize=6)
    plotstyle.save(fig, figs / "adaptive.png")


def m7() -> None:
    import matplotlib.pyplot as plt

    res = J("M7/federated_d3.json")
    figs = R / "M7/figs"
    figs.mkdir(parents=True, exist_ok=True)
    sites = list(res["pymatching_reference"])
    dp = sorted(k for k in res if k.startswith("fedavg-dp"))
    regimes = ["local-only", "centralized", "fedavg", "fedavg-iid"] + dp
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    w = 0.8 / len(sites)
    for i, s in enumerate(sites):
        vals = []
        for g in regimes:
            ev = res[g] if g in ("local-only", "centralized") else res[g]["eval"]
            vals.append(ev[s]["pl"] / max(res["pymatching_reference"][s]["pl"], 1e-12))
        ax.bar([j + (i - (len(sites) - 1) / 2) * w for j in range(len(regimes))], vals, width=w * 0.9,
               color=plotstyle.SERIES[i], label=s, zorder=3)
    labels = []
    for g in regimes:
        eps = res[g].get("dp", {}).get("epsilon") if isinstance(res[g], dict) and "dp" in res[g] else None
        labels.append(g + (f"\neps={eps:.2g}" if eps is not None else ""))
    ax.set_xticks(range(len(regimes)), labels, fontsize=6)
    ax.axhline(1.0, color=plotstyle.INK2, lw=0.8)
    ax.set_ylabel("P_L(GNN) / P_L(PyMatching), per site")
    ax.legend()
    plotstyle.save(fig, figs / "privacy_utility.png")


def main() -> None:
    plotstyle.apply()
    m1_plots.main()
    m2_report.main()
    for f in (m4, m5, m6, m7):
        f()
    print("figures OK")


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
