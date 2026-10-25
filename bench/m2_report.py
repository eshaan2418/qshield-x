"""M2 report: resources vs bounded latency (Pareto), hardware vs CPU p99 latency.

Inputs (all must exist):
  results/M2/fpga/fpga_*.json      synth (Yosys) cells + pnr (nextpnr-ecp5) Fmax/utilisation per config
  results/M2/hw_cycles.json        cycle distributions (cycle-exact HwModel, co-sim verified)
  results/M2/shell_latency.json    end-to-end shell overhead cycles (Verilator qsx_top)
  results/M2/toggle_proxy.json     switching-activity estimate
  results/M1/latency.json          CPU latency (1 thread)
Every derived number keeps the stages it was combined from, e.g. "sim cycles / pnr Fmax".
Latency in ns = cycles / Fmax(pnr). The *bounded* (worst-case) latency is the configured cycle budget; the
reported p99/max are over Stim-sampled syndromes.
Output: results/M2/report.json, results/M2/figs/{pareto,hw_vs_cpu,lanes}.png|pdf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench import plotstyle  # noqa: E402
from bench.provenance import write_result  # noqa: E402

R = ROOT / "results"
P_REF = 0.003
T_ROUND_NS = 1000.0  # assumed syndrome-round time (typical superconducting cycle); a parameter, not a measurement


def J(p):
    return json.loads((R / p).read_text())["data"]


def main() -> None:
    import matplotlib.pyplot as plt

    plotstyle.apply()
    fpga = [r for f in sorted((R / "M2/fpga").glob("fpga_*.json")) for r in json.loads(f.read_text())["data"]]
    cyc = J("M2/hw_cycles.json")
    shell = {r["d"]: r for r in J("M2/shell_latency.json")}
    cpu = J("M1/latency.json")
    tog = {(r["d"], r["p"]): r for r in J("M2/toggle_proxy.json")}

    def cycrow(d, L, P, p=P_REF):
        for r in cyc:
            if r["d"] == d and r["lanes"] == L and r["pipe"] == P and abs(r["p"] - p) < 1e-9:
                return r
        return None

    def cycles(d, L, P, p=P_REF):
        r = cycrow(d, L, P, p)
        return r["cycles"] if r else None

    def cpu_lat(d, dec, p=P_REF):
        for r in cpu:
            if r["d"] == d and abs(r["p"] - p) < 1e-9 and r["decoder"] == dec:
                return r
        return None

    rows = []
    for f in fpga:
        if f.get("top") != "qsx_pnr_shell":
            continue
        d, L, P = f["d"], f["lanes"], int(f["params"].get("PIPE", 0))
        s = f.get("synth", {}).get("cells", {})
        row = {"tag": f["tag"], "d": d, "weights": f["weights"], "lanes": L, "pipe": P,
               "synth": {"stage": "synth", "LUT4": s.get("LUT4"), "FF": s.get("TRELLIS_FF"),
                         "CCU2C": s.get("CCU2C"), "DP16KD": s.get("DP16KD", 0), "MULT18X18D": s.get("MULT18X18D", 0)}}
        if "pnr" in f:
            u = f["pnr"]["utilization"]
            row["pnr"] = {"stage": "pnr", "fmax_mhz": f["pnr"]["fmax_mhz"],
                          "comb": u.get("TRELLIS_COMB", {}).get("used"), "comb_avail": u.get("TRELLIS_COMB", {})
                          .get("available"), "ff": u.get("TRELLIS_FF", {}).get("used"),
                          "dp16kd": u.get("DP16KD", {}).get("used", 0)}
        elif "pnr_error" in f:
            row["pnr_error"] = f["pnr_error"]
        c = cycles(d, L, P) if f["weights"] == "q5" else None
        if c:
            ov = shell.get(d, {}).get("overhead_cycles_mean", 0.0)
            row["core_cycles"] = {"stage": "sim (cycle-exact HwModel)", "p": P_REF, **c}
            row["shell_overhead_cycles"] = ov
            if "pnr" in row:
                fm = row["pnr"]["fmax_mhz"]
                row["latency_ns"] = {"stage": "sim cycles / pnr Fmax", "p": P_REF,
                                     "p50": (c["p50"] + ov) * 1e3 / fm, "p99": (c["p99"] + ov) * 1e3 / fm,
                                     "max": (c["max"] + ov) * 1e3 / fm}
                row["throughput_decodes_per_s"] = {"stage": "sim cycles / pnr Fmax", "value": fm * 1e6 / c["mean"]}
                # Guaranteed deadline via the verified watchdog (property C2): budget B such that shell + B cycles
                # fit in the d-round block time; frames needing more than B cycles return WATCHDOG -> software.
                hist = cycrow(d, L, P).get("hist")
                dl_ns = d * T_ROUND_NS
                budget = int(dl_ns * fm / 1e3) - int(round(ov))
                if hist and budget > 0:
                    n = sum(cn for _, cn in hist)
                    within = sum(cn for v, cn in hist if v <= budget) / n
                    row["deadline"] = {"stage": "sim cycles / pnr Fmax; bound by proof C2 (watchdog)",
                                       "deadline_ns": dl_ns, "t_round_ns_assumed": T_ROUND_NS,
                                       "watchdog_budget_cycles": budget, "hw_fraction_within": within,
                                       "fallback_fraction": 1 - within}
        t = tog.get((d, P_REF))
        if t and L == 8 and P == 0:
            row["toggles_per_decode"] = {"stage": t["stage"], "value": t["toggles_per_decode"]}
        rows.append(row)

    comp = []
    for d in sorted({r["d"] for r in rows}):
        best = [r for r in rows if r["d"] == d and "latency_ns" in r]
        if not best:
            continue
        b = min(best, key=lambda r: r["latency_ns"]["p99"])
        e = {"d": d, "p": P_REF, "hw_best_tag": b["tag"], "hw_p99_ns": b["latency_ns"]["p99"],
             "hw_max_ns": b["latency_ns"]["max"], "hw_stage": b["latency_ns"]["stage"],
             "hw_deadline": b.get("deadline")}
        for dec, k in (("pymatching", "cpu_pm"), ("qsxuf-q5", "cpu_uf")):
            c = cpu_lat(d, dec)
            if c:
                e[f"{k}_p99_ns"] = c["lat_ns_p99"]
                e[f"{k}_p999_ns"] = c["lat_ns_p999"]
                e[f"{k}_max_ns"] = c["lat_ns_max"]
                if "over_budget_fraction" in c:  # blocks slower than the same d * T_round deadline
                    e[f"{k}_over_deadline"] = c["over_budget_fraction"]
                e[f"{k}_stage"] = "CPU measurement (1 thread)"
        if "cpu_pm_p99_ns" in e:
            e["speedup_vs_pm_p99"] = e["cpu_pm_p99_ns"] / e["hw_p99_ns"]
        comp.append(e)

    figs = R / "M2/figs"
    figs.mkdir(parents=True, exist_ok=True)
    # Pareto: LUT4 (synth) vs p99 latency (sim/pnr), one series per distance
    fig, ax = plt.subplots(figsize=(5.2, 3.8))
    for i, d in enumerate(sorted({r["d"] for r in rows if "latency_ns" in r})):
        pts = sorted([(r["synth"]["LUT4"], r["latency_ns"]["p99"], r["lanes"], r["pipe"]) for r in rows
                      if r["d"] == d and "latency_ns" in r and r["weights"] == "q5"])
        st = plotstyle.style(i)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], color=st["color"], marker=st["marker"], s=28,
                   label=f"d={d}", zorder=3, edgecolors=plotstyle.SURFACE, linewidths=1.0)
        front, best = [], float("inf")
        for p in pts:
            if p[1] < best:
                front.append(p)
                best = p[1]
        ax.plot([p[0] for p in front], [p[1] for p in front], color=st["color"], lw=1.0, alpha=0.7)
        for p in pts:
            ax.annotate(f"L{p[2]}" + ("p" if p[3] else ""), (p[0], p[1]), fontsize=6, color=plotstyle.INK2,
                        xytext=(3, 3), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("LUT4 (Yosys synth, ECP5)")
    ax.set_ylabel(f"p99 decode latency, ns (sim cycles / PnR Fmax, p={P_REF})")
    ax.legend(title="distance", title_fontsize=7)
    plotstyle.save(fig, figs / "pareto.png")

    # HW vs CPU p99, grouped bars per distance
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    series = [("hw_p99_ns", "QSX-UF RTL (sim / PnR)"), ("cpu_uf_p99_ns", "QSX-UF C++ (CPU)"),
              ("cpu_pm_p99_ns", "PyMatching (CPU)")]
    w = 0.26
    for i, (k, lab) in enumerate(series):
        xs = [j + (i - 1) * w for j, e in enumerate(comp) if k in e]
        ys = [e[k] for e in comp if k in e]
        ax.bar(xs, ys, width=w - 0.03, color=plotstyle.SERIES[i], label=lab, zorder=3)
    # Real-time reference: a d-round block arrives every d * T_round; T_round = 1 us is an assumed, typical
    # superconducting syndrome-cycle time (a plot parameter, not a measurement).
    for j, e in enumerate(comp):
        ax.hlines(e["d"] * 1000.0, j - 0.42, j + 0.42, colors=plotstyle.INK2, linestyles="dashed", lw=1.0, zorder=4)
    ax.plot([], [], color=plotstyle.INK2, ls="--", lw=1.0, label="block budget d x 1 us (assumed round time)")
    ax.set_xticks(range(len(comp)), [f"d={e['d']}" for e in comp])
    ax.set_yscale("log")
    ax.set_ylabel(f"p99 latency per d-round block, ns (p={P_REF})")
    ax.legend()
    plotstyle.save(fig, figs / "hw_vs_cpu.png")

    # Cycles vs lanes (sim only), per distance
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for i, d in enumerate(sorted({r["d"] for r in cyc})):
        rr = sorted([r for r in cyc if r["d"] == d and r["pipe"] == 0 and abs(r["p"] - P_REF) < 1e-9],
                    key=lambda r: r["lanes"])
        ax.plot([r["lanes"] for r in rr], [r["cycles"]["p99"] for r in rr], label=f"d={d}", **plotstyle.style(i))
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("LANES (vertices per scan cycle)")
    ax.set_ylabel(f"p99 core cycles (cycle-exact model, p={P_REF})")
    ax.legend()
    plotstyle.save(fig, figs / "lanes.png")

    write_result(R / "M2/report.json", {"configs": rows, "hw_vs_cpu": comp},
                 {"p_ref": P_REF, "sources": ["results/M2/fpga/fpga_*.json", "results/M2/hw_cycles.json",
                                              "results/M2/shell_latency.json", "results/M1/latency.json"]}, None)
    for e in comp:
        print(json.dumps(e))


if __name__ == "__main__":
    main()
