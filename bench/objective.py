"""M10: the project objective, evaluated on measured data.

    J(config) = alpha * P_L + beta * T_decode + gamma * A_FPGA          (delta * E omitted, see below)

Configurations (all at the same noise point p): PyMatching on one CPU core, QSX-UF C++ on one CPU core, and every
QSX-UF RTL configuration that places and routes on the LFE5U-85F (LANES x PIPE). Inputs per configuration:
  P_L       results/M1/pl (Monte Carlo; RTL == C++ QSX-UF bit-exactly, so they share P_L)
  T_decode  p99 latency per d-round block: CPU measurement (M1) or sim cycles / PnR Fmax incl. shell (M2 report)
  A_FPGA    LUT4 after synthesis (0 for CPU decoders, which use a host core instead)
Each metric is normalised by its maximum over the configurations of that distance, so the weights are relative
priorities. The script reports the Pareto set (no configuration better in all three metrics) and, for a grid of
weights on the simplex, which configuration minimises J.
The energy term is omitted: CPU energy was not measured and the RTL activity proxy is not in Watts (BLOCKERS B3).
Output: results/M10/objective.json, results/M10/figs/objective_d{d}.png|pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench import plotstyle  # noqa: E402
from bench.provenance import write_result  # noqa: E402

R = ROOT / "results"


def J(p):
    return json.loads((R / p).read_text())["data"]


def configs(d: int, p: float) -> list[dict]:
    pl = J(f"M1/pl/pl_d{d}_p{p:g}.json")["decoders"]
    lat = {r["decoder"]: r for r in J("M1/latency.json") if r["d"] == d and abs(r["p"] - p) < 1e-9}
    out = []
    for dec, name in (("pymatching", "PyMatching (CPU)"), ("qsxuf-q5", "QSX-UF q5 (CPU)")):
        if dec in lat:
            out.append({"name": name, "kind": "cpu", "pl": pl[dec]["pl"], "pl_ci95": pl[dec]["ci95"],
                        "t_ns": lat[dec]["lat_ns_p99"], "lut": 0, "t_stage": "CPU measurement (1 thread)"})
    rep = J("M2/report.json")["configs"]
    for r in rep:
        if r["d"] == d and r["weights"] == "q5" and "latency_ns" in r:
            out.append({"name": f"QSX-UF RTL L{r['lanes']} P{r['pipe']}", "kind": "rtl", "pl": pl["qsxuf-q5"]["pl"],
                        "pl_ci95": pl["qsxuf-q5"]["ci95"], "t_ns": r["latency_ns"]["p99"], "lut": r["synth"]["LUT4"],
                        "fmax_mhz": r["pnr"]["fmax_mhz"], "t_stage": r["latency_ns"]["stage"]})
    return out


def pareto(cs: list[dict]) -> list[str]:
    keys = ("pl", "t_ns", "lut")
    front = []
    for a in cs:
        dominated = any(all(b[k] <= a[k] for k in keys) and any(b[k] < a[k] for k in keys) for b in cs if b is not a)
        if not dominated:
            front.append(a["name"])
    return front


def main() -> None:
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5")
    ap.add_argument("--p", type=float, default=0.003)
    ap.add_argument("--steps", type=int, default=20)
    a = ap.parse_args()
    plotstyle.apply()
    rows = []
    for d in map(int, a.distances.split(",")):
        cs = configs(d, a.p)
        if not cs:
            continue
        mx = {k: max(c[k] for c in cs) or 1.0 for k in ("pl", "t_ns", "lut")}
        grid = []
        for i in range(a.steps + 1):
            for j in range(a.steps + 1 - i):
                w = (i / a.steps, j / a.steps, (a.steps - i - j) / a.steps)  # (alpha, beta, gamma)
                score = [w[0] * c["pl"] / mx["pl"] + w[1] * c["t_ns"] / mx["t_ns"] + w[2] * c["lut"] / mx["lut"]
                         for c in cs]
                grid.append({"alpha": w[0], "beta": w[1], "gamma": w[2], "winner": cs[int(np.argmin(score))]["name"]})
        wins = {c["name"]: sum(g["winner"] == c["name"] for g in grid) / len(grid) for c in cs}
        rows.append({"d": d, "p": a.p, "configs": cs, "pareto": pareto(cs), "weight_grid": grid,
                     "win_fraction": wins, "normalisers": mx,
                     "note": "delta*E omitted (no CPU energy measurement; RTL activity proxy is not in Watts)"})
        print(d, "pareto:", rows[-1]["pareto"], {k: round(v, 2) for k, v in wins.items() if v > 0})
        # ternary-style map: alpha (x) vs beta (y), gamma = 1 - alpha - beta; color = winner
        names = sorted({g["winner"] for g in grid}, key=lambda n: [c["name"] for c in cs].index(n))
        fig, ax = plt.subplots(figsize=(4.8, 4.0))
        for k, n in enumerate(names):
            pts = [(g["alpha"], g["beta"]) for g in grid if g["winner"] == n]
            ax.scatter([q[0] for q in pts], [q[1] for q in pts], s=36, marker="s", color=plotstyle.SERIES[k],
                       label=n, edgecolors=plotstyle.SURFACE, linewidths=0.8, zorder=3)
        ax.set_xlabel("alpha (weight on P_L)")
        ax.set_ylabel("beta (weight on p99 latency)")
        ax.set_title(f"configuration minimising J, d={d}, p={a.p} (gamma = 1 - alpha - beta, area)", fontsize=8)
        ax.legend(fontsize=6, loc="upper right")
        plotstyle.save(fig, R / f"M10/figs/objective_d{d}.png")
    write_result(R / "M10/objective.json", rows, vars(a), None)


if __name__ == "__main__":
    main()
