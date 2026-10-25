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


def tables() -> list[str]:
    written = []
    for name, fn in TABLES.items():
        (ROOT / "paper" / name).write_text("% AUTO-GENERATED by bench/claims_ext.py -- do not edit\n" + fn() + "\n")
        written.append(name)
    return written
