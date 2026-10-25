"""Claims for ENV and M2-M10 (imported by bench/claims.py), plus generated paper tables.

Each claim: id -> (extractor over a results/ JSON file, format, evidence stage, source path). Tables for the paper
are written by `tables()` as LaTeX that contains only \\claim{...} references (so bench/check_numbers.py can
verify that every number in the paper is backed).
"""

from __future__ import annotations

from pathlib import Path

from bench.claims import CLAIMS, J, claim

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"


def _find(rows, **kw):
    for r in rows:
        if all((abs(r.get(k) - v) < 1e-9 if isinstance(v, float) else r.get(k) == v) for k, v in kw.items()):
            return r
    raise KeyError(kw)


def _exists(p: str) -> bool:
    return (R / p).exists()


# ---------------------------------------------------------------- ENV
claim("ENV_host", lambda: "{cpu}, {ncpu} cores, {ram_gb:.0f} GB RAM, {os}".format(**J("ENV/host.json")), "{}",
      "host probe", "results/ENV/host.json")
claim("ENV_timer_ns", lambda: J("ENV/host.json")["timer_resolution_ns"], "{}", "host probe", "results/ENV/host.json")

# ---------------------------------------------------------------- M1 derived
for d in (5, 7, 9):
    claim(f"M1_ratio_d{d}_p003",
          lambda d=d: CLAIMS[f"M1_PL_d{d}_p003_UF"]["fn"]() / CLAIMS[f"M1_PL_d{d}_p003_PM"]["fn"](), "{:.2f}",
          "sim (Monte Carlo, Stim)", f"results/M1/pl/pl_d{d}_p0.003.json")


# ---------------------------------------------------------------- M2 co-simulation
def _cosim(ds=(3, 5, 7)):
    tot = mm = 0
    for d in ds:
        for g in J(f"M2/cosim/cosim_d{d}.json")["aggregate"]:
            tot += g["syndromes"]
            mm += g["mismatches"]
    return tot, mm


COSIM_SRC = "results/M2/cosim/cosim_d{3,5,7}.json"
claim("M2_cosim_total", lambda: _cosim()[0], "{:,}", "sim (Verilator RTL vs C++ golden model)", COSIM_SRC)
claim("M2_cosim_mm", lambda: _cosim()[1], "{}", "sim (Verilator RTL vs C++ golden model)", COSIM_SRC)
def _agg(d):
    return J(f"M2/cosim/cosim_d{d}.json")["aggregate"]


def _sweep(d, fld):
    return sum(g[fld] for g in _agg(d) if g["kind"].startswith("core-random-L"))


for d in (3, 5, 7):
    src = f"results/M2/cosim/cosim_d{d}.json"
    for kind, tag in (("core-random", "rand"), ("core-stim", "stim"), ("top-random-stress", "toprand"),
                      ("top-stim-stress", "topstim")):
        for fld, ftag in (("syndromes", "n"), ("mismatches", "mm")):
            claim(f"M2_cosim_d{d}_{tag}_{ftag}", lambda d=d, kind=kind, fld=fld: _find(_agg(d), kind=kind)[fld],
                  "{:,}", "sim (Verilator)", src)
    claim(f"M2_cosim_d{d}_sweep_n", lambda d=d: _sweep(d, "syndromes"), "{:,}", "sim (Verilator)", src)
    claim(f"M2_cosim_d{d}_sweep_mm", lambda d=d: _sweep(d, "mismatches"), "{}", "sim (Verilator)", src)
    for fld in ("malformed", "cfg_invalid"):
        claim(f"M2_cosim_d{d}_{fld}", lambda d=d, fld=fld: _find(_agg(d), kind="top-random-stress")[fld], "{:,}",
              "sim (Verilator)", src)

# ---------------------------------------------------------------- M2 cycles (cycle-exact model)
CYC = "results/M2/hw_cycles.json"
for d in (3, 5, 7, 9):
    for L in (1, 8, 32):
        for q in ("p50", "p99", "max"):
            claim(f"M2_cyc_{q}_d{d}_L{L}", lambda d=d, L=L, q=q: _find(J("M2/hw_cycles.json"), d=d, lanes=L, pipe=0,
                                                                       p=0.003)["cycles"][q],
                  "{:.0f}", "sim (cycle-exact HwModel)", CYC)

# ---------------------------------------------------------------- M2 shell latency / M3 overhead
for d in (3, 5, 7):
    claim(f"M2_shell_ov_d{d}", lambda d=d: _find(J("M2/shell_latency.json"), d=d)["overhead_cycles_mean"], "{:.1f}",
          "sim (Verilator qsx_top)", "results/M2/shell_latency.json")
    claim(f"M2_shell_e2e_p99_d{d}", lambda d=d: _find(J("M2/shell_latency.json"), d=d)["e2e_cycles"]["p99"], "{:.0f}",
          "sim (Verilator qsx_top)", "results/M2/shell_latency.json")


# ---------------------------------------------------------------- M3 overhead (synth, -noflatten) + toggle proxy
OV = "results/M3/overhead.json"
for d in (3, 5, 7):
    for part in ("core", "shell"):
        for cell, tag in (("LUT4", "lut"), ("TRELLIS_FF", "ff"), ("DP16KD", "bram")):
            claim(f"M3_{part}_{tag}_d{d}",
                  lambda d=d, part=part, cell=cell: _find(J("M3/overhead.json"), d=d)[part][cell], "{:,}",
                  "synth (Yosys synth_ecp5 -noflatten)", OV)
    claim(f"M3_shell_lut_pct_d{d}", lambda d=d: 100 * _find(J("M3/overhead.json"), d=d)["shell_lut_fraction"], "{:.1f}",
          "synth (Yosys synth_ecp5 -noflatten)", OV)
    claim(f"M3_shell_ff_pct_d{d}", lambda d=d: 100 * _find(J("M3/overhead.json"), d=d)["shell_ff_fraction"], "{:.1f}",
          "synth (Yosys synth_ecp5 -noflatten)", OV)
    claim(f"M3_shell_cycles_d{d}", lambda d=d: _find(J("M2/shell_latency.json"), d=d)["overhead_cycles_mean"], "{:.1f}",
          "sim (Verilator qsx_top)", "results/M2/shell_latency.json")
    claim(f"M3_shell_cyc_pct_d{d}", lambda d=d: 100 * _find(J("M2/shell_latency.json"), d=d)["overhead_cycles_mean"]
          / _find(J("M2/shell_latency.json"), d=d)["e2e_cycles"]["mean"], "{:.1f}", "sim (Verilator qsx_top)",
          "results/M2/shell_latency.json")
    for p in (0.001, 0.003, 0.006):
        claim(f"M2_toggles_d{d}_p{int(p * 1000)}", lambda d=d, p=p: _find(J("M2/toggle_proxy.json"), d=d, p=p)
              ["toggles_per_decode"], "{:,.0f}", "estimate (Verilator toggle-count proxy, not Watts)",
              "results/M2/toggle_proxy.json")


# ---------------------------------------------------------------- M2 cycle breakdown
BD = "results/M2/cycle_breakdown.json"
for d in (3, 5, 7, 9):
    for ls in ("8", "32", "V"):
        claim(f"M2_scan_share_d{d}_L{ls}", lambda d=d, ls=ls: 100 * _find(J("M2/cycle_breakdown.json"), d=d,
              lanes_label=ls, pipe=0)["share"]["scans"], "{:.0f}", "sim (cycle-exact HwModel)", BD)
        claim(f"M2_mean_cyc_d{d}_L{ls}", lambda d=d, ls=ls: _find(J("M2/cycle_breakdown.json"), d=d, lanes_label=ls,
              pipe=0)["mean_cycles"], "{:.0f}", "sim (cycle-exact HwModel)", BD)


# ---------------------------------------------------------------- generated paper tables
def _tex(s) -> str:
    return str(s).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")


TABLES: dict[str, callable] = {}


def table(name):
    def deco(fn):
        TABLES[name] = fn
        return fn
    return deco


def _rowclaims(prefix: str, src: str, stage: str, rows: list[dict], cols: list[tuple[str, callable, str]]) -> list:
    """Register one claim per (row, column) and return LaTeX rows made of \\claim references."""
    out = []
    for i in range(len(rows)):
        cells = []
        for key, fn, fmt in cols:
            cid = f"{prefix}_{i}_{key}"
            claim(cid, lambda i=i, fn=fn: fn(rows[i]), fmt, stage, src)
            cells.append(f"\\claim{{{cid}}}")
        out.append(" & ".join(cells) + r" \\")
    return out


def _formal_rows():
    rows = J("M3/formal_summary.json")
    def bound(r):
        if r["tool"].startswith("TLC"):
            return _tex(f"{r['distinct_states']:,} states, depth {r['depth']}" if r["distinct_states"] else "-")
        if r["tool"].startswith("Z3"):
            return _tex(f"{len(r['steps'])} steps, 1 transition")
        return _tex(f"{r['mode']} depth {r['depth']}")
    def status(r):
        if r["tool"].startswith("TLC"):
            s = "no error" if r["ok"] else ", ".join(r["violations"]) or "error"
        elif r["tool"].startswith("Z3"):
            s = "all UNSAT" if r["ok"] and "mutant" not in r["job"] else ("mutant SAT (expected)" if r["ok"] else
                                                                         "FAIL")
        else:
            s = r["status"]
        return _tex(s)
    return rows, [("job", lambda r: "\\texttt{" + _tex(r["job"]) + "}", "{}"),
                  ("tool", lambda r: _tex(r["tool"].split("/")[0]), "{}"),
                  ("bound", bound, "{}"), ("status", status, "{}"), ("sec", lambda r: r["seconds"], "{:.0f}")]


if _exists("M3/formal_summary.json"):
    _fr, _fc = _formal_rows()
    _FORMAL_TEX = _rowclaims("M3F", "results/M3/formal_summary.json", "formal (SymbiYosys / TLC / Z3)", _fr, _fc)

    @table("gen_formal.tex")
    def _t_formal():
        return "\n".join([
            r"\begin{table}[t]\centering\small",
            r"\caption{Formal verification jobs (\texttt{make formal}). ``prove'' = k-induction (unbounded); ``bmc'' ="
            r" bounded to the stated depth; TLC explores the full state space of the stated model constants.}",
            r"\label{tab:formal}",
            r"\begin{tabular}{llllr}\toprule job & tool & bound & result & s \\ \midrule",
            *_FORMAL_TEX, r"\bottomrule\end{tabular}\end{table}"])


_COSIM_KINDS = [("core-random", "core, random syndromes"), ("core-stim", "core, Stim syndromes"),
                ("sweep", "core, LANES sweep 1/4/16/32"), ("top-random-stress", "shell, random + gaps/backpressure/"
                                                                              "malformed/reconfig"),
                ("top-stim-stress", "shell, Stim + gaps/backpressure")]


def _cosim_cell(d, kind, fld):
    if kind == "sweep":
        return _sweep(d, fld)
    return _find(_agg(d), kind=kind)[fld]


if all(_exists(f"M2/cosim/cosim_d{d}.json") for d in (3, 5, 7)):
    _CT = []
    for kind, lab in _COSIM_KINDS:
        claim(f"M2_ct_{kind.replace('-', '')}_lab", lambda lab=lab: _tex(lab), "{}", "config",
              "tb/run_cosim.py (campaign definition)")
        cells = [f"\\claim{{M2_ct_{kind.replace('-', '')}_lab}}"]
        for d in (3, 5, 7):
            for fld, f in (("syndromes", "{:,}"), ("mismatches", "{}")):
                cid = f"M2_ct_{kind.replace('-', '')}_d{d}_{fld[:2]}"
                claim(cid, lambda d=d, kind=kind, fld=fld: _cosim_cell(d, kind, fld), f, "sim (Verilator)",
                      f"results/M2/cosim/cosim_d{d}.json")
                cells.append(f"\\claim{{{cid}}}")
        _CT.append(" & ".join(cells) + r" \\")

    @table("gen_cosim.tex")
    def _t_cosim():
        return "\n".join([
            r"\begin{table}[t]\centering\small",
            r"\caption{Co-simulation of the final RTL against the C++ golden model (status, rounds, observable, full"
            r" correction bitmap and cycle count compared per syndrome). Columns: syndromes / mismatches.}",
            r"\label{tab:cosim}",
            r"\begin{tabular}{lrrrrrr}\toprule & \multicolumn{2}{c}{$d=3$} & \multicolumn{2}{c}{$d=5$} &"
            r" \multicolumn{2}{c}{$d=7$} \\ \midrule",
            *_CT, r"\bottomrule\end{tabular}\end{table}"])


if _exists("M3/overhead.json"):
    _OV_ROWS = []
    for r in J("M3/overhead.json"):
        d = r["d"]
        cells = [f"$d={d}$"]
        for part in ("core", "shell"):
            for tag in ("lut", "ff", "bram"):
                cells.append(f"\\claim{{M3_{part}_{tag}_d{d}}}")
        cells += [f"\\claim{{M3_shell_lut_pct_d{d}}}\\%", f"\\claim{{M3_shell_cycles_d{d}}}"]
        _OV_ROWS.append(" & ".join(cells) + r" \\")

    @table("gen_overhead.tex")
    def _t_overhead():
        return "\n".join([
            r"\begin{table}[t]\centering\small",
            r"\caption{Core vs.\ verified shell (Yosys \texttt{synth\_ecp5 -noflatten}, LANES=8) and the shell's"
            r" framing/handshake cycles per frame (Verilator, one frame in flight).}",
            r"\label{tab:overhead}",
            r"\begin{tabular}{lrrrrrrrr}\toprule & \multicolumn{3}{c}{core} & \multicolumn{3}{c}{shell} & & \\"
            r" & LUT4 & FF & BRAM & LUT4 & FF & BRAM & shell LUT & cycles \\ \midrule",
            *_OV_ROWS, r"\bottomrule\end{tabular}\end{table}"])


# ---------------------------------------------------------------- M7 federated
def _m7_rows():
    rows = []
    fed = J("M7/federated_d3.json")
    rows.append(("PyMatching (true noise model)", "--", fed["pymatching_reference"], None, "M7/federated_d3.json"))
    rows.append(("local only (no sharing)", "--", fed["local-only"], None, "M7/federated_d3.json"))
    rows.append(("centralized (pooled data)", "--", fed["centralized"], None, "M7/federated_d3.json"))
    for k, lab in (("fedavg", "FedAvg + SecAgg, non-IID"), ("fedavg-iid", "FedAvg + SecAgg, IID split")):
        rows.append((lab, "--", fed[k]["eval"], fed[k], "M7/federated_d3.json"))
    for src, tag in (("M7/federated_d3_clip_ablation.json", "lot 512"), ("M7/federated_d3.json", "lot 512"),
                     ("M7/federated_d3_dp_b8192.json", "lot 8192")):
        if not _exists(src):
            continue
        dat = J(src)
        for k in sorted(x for x in dat if x.startswith("fedavg-dp")):
            if src.endswith("federated_d3.json") and k == "fedavg-dp-sigma0.6" and _exists(
                    "M7/federated_d3_clip_ablation.json"):
                continue  # the ablation file re-runs sigma 0.6 paired with sigma 0
            sig = dat[k]["dp"]["sigma"]
            rows.append((f"FedAvg + DP-SGD, {tag}, $\\sigma={sig:g}$", "eps", dat[k]["eval"], dat[k], src))
    return rows


if _exists("M7/federated_d3.json"):
    _M7 = []
    for i, (lab, _kind, ev, info, src) in enumerate(_m7_rows()):
        claim(f"M7_r{i}_lab", lambda lab=lab: lab, "{}", "config", f"results/{src}")
        cells = [f"\\claim{{M7_r{i}_lab}}"]
        if info and "dp" in info:
            claim(f"M7_r{i}_eps", lambda info=info: info["dp"]["epsilon"], "{:.2f}", "DP accounting (Opacus RDP)",
                  f"results/{src}")
            cells.append(f"\\claim{{M7_r{i}_eps}}" if info["dp"]["epsilon"] != float("inf") else "$\\infty$")
        else:
            cells.append("--")
        for site in ("site-A", "site-B", "site-C"):
            claim(f"M7_r{i}_{site[-1]}", lambda ev=ev, site=site: 100 * ev[site]["pl"], "{:.2f}",
                  "sim (Monte Carlo, Stim)", f"results/{src}")
            cells.append(f"\\claim{{M7_r{i}_{site[-1]}}}")
        if info:
            claim(f"M7_r{i}_mb", lambda info=info: info["bytes_up_total"] / 1e6, "{:.1f}", "measured (bytes)",
                  f"results/{src}")
            cells.append(f"\\claim{{M7_r{i}_mb}}")
        else:
            cells.append("--")
        _M7.append(" & ".join(cells) + r" \\")

    @table("gen_m7.tex")
    def _t_m7():
        return "\n".join([
            r"\begin{table}[t]\centering\small",
            r"\caption{Federated GNN decoder training, $d=3$, three sites with different noise. P\textsubscript{L} in"
            r" \%, per site's own test set; $\varepsilon$ per site at $\delta=10^{-5}$ (record level); upload = total"
            r" masked-update bytes from all sites.}",
            r"\label{tab:m7}",
            r"\begin{tabular}{lrrrrr}\toprule regime & $\varepsilon$ & A & B & C & upload MB \\ \midrule",
            *_M7, r"\bottomrule\end{tabular}\end{table}"])


def tables() -> list[str]:
    written = []
    for name, fn in TABLES.items():
        (ROOT / "paper" / name).write_text("% AUTO-GENERATED by bench/claims_ext.py -- do not edit\n" + fn() + "\n")
        written.append(name)
    return written
