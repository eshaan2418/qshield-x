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

# supplementary campaigns: PIPE=1 (d=3,5) and LANES=V (d=3: 24, d=5: 120; PIPE 0/1)
EXTRA = ["M2/cosim_pipe1", "M2/cosim_lanesV_d3_P0", "M2/cosim_lanesV_d3_P1", "M2/cosim_lanesV_d5_P0",
         "M2/cosim_lanesV_d5_P1"]


def _extra(fld):
    return sum(g[fld] for e in EXTRA for g in J(f"{e}/summary.json")["aggregate"])


claim("M2_cosim_extra_total", lambda: _extra("syndromes"), "{:,}", "sim (Verilator RTL vs C++ golden model)",
      "results/M2/cosim_pipe1/, results/M2/cosim_lanesV_*/")
claim("M2_cosim_extra_mm", lambda: _extra("mismatches"), "{}", "sim (Verilator RTL vs C++ golden model)",
      "results/M2/cosim_pipe1/, results/M2/cosim_lanesV_*/")


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


# ---------------------------------------------------------------- M6 learned / adaptive
for d in (3, 5):
    src = f"results/M6/gnn_d{d}/eval.json"
    for dec, tag in (("gnn", "GNN"), ("pymatching", "PM"), ("qsxuf-q5", "UF")):
        claim(f"M6_pl_d{d}_{tag}", lambda d=d, dec=dec: _find(J(f"M6/gnn_d{d}/eval.json"), p=0.003)[dec]["pl"],
              "{:.2e}", "sim (Monte Carlo, Stim)", src)
    claim(f"M6_gnn_ratio_d{d}", lambda d=d: _find(J(f"M6/gnn_d{d}/eval.json"), p=0.003)["gnn"]["pl"]
          / _find(J(f"M6/gnn_d{d}/eval.json"), p=0.003)["pymatching"]["pl"], "{:.2f}", "sim (Monte Carlo, Stim)", src)
    claim(f"M6_gnn_b1_p50_us_d{d}", lambda d=d: _find(J(f"M6/gnn_d{d}/eval.json"), p=0.003)["gnn_latency_batch1_us"]
          ["p50"], "{:.0f}", "CPU measurement (PyTorch, 1 thread)", src)
    claim(f"M6_gnn_batched_us_d{d}", lambda d=d: _find(J(f"M6/gnn_d{d}/eval.json"), p=0.003)["gnn_batched_us_per_shot"],
          "{:.1f}", "CPU measurement (PyTorch, 1 thread)", src)
AD = "results/M6/adaptive_d5.json"
for sc in ("step", "readout", "drift", "burst"):
    for st in ("fixed-UF", "fixed-PM", "adaptive-UF", "adaptive-hybrid", "oracle-UF", "oracle-PM"):
        tag = st.replace("-", "")
        claim(f"M6_{sc}_{tag}", lambda sc=sc, st=st: J("M6/adaptive_d5.json")["results"][sc]["strategies"][st]["pl"],
              "{:.2e}", "sim (Monte Carlo, Stim)", AD)
claim("M6_policy_ns", lambda: max(v["policy_ns_per_shot"] for v in J("M6/adaptive_d5.json")["results"].values()),
      "{:,.0f}", "CPU measurement (policy statistics + estimate, per shot)", AD)
claim("M6_recovery_shots", lambda: J("M6/adaptive_d5.json")["results"]["step"]["recovery"]["shots"], "{:,}",
      "sim (Monte Carlo, Stim)", AD)

# ---------------------------------------------------------------- M8 infra
M8 = "results/M8/overhead.json"
claim("M8_verify_mbps", lambda: _find(J("M8/overhead.json")["sign_verify"], mb=64)["verify_mb_per_s"], "{:,.0f}",
      "CPU measurement", M8)
claim("M8_aes_enc_mbps", lambda: _find(J("M8/overhead.json")["aes_gcm"], mb=64)["encrypt_mb_per_s"], "{:,.0f}",
      "CPU measurement", M8)
claim("M8_mtls_p50_ms", lambda: J("M8/overhead.json")["control_api"]["mtls"]["p50_ms"], "{:.2f}", "CPU measurement",
      M8)
claim("M8_plain_p50_ms", lambda: J("M8/overhead.json")["control_api"]["plain_http"]["p50_ms"], "{:.2f}",
      "CPU measurement", M8)


def _junit():
    import xml.etree.ElementTree as ET

    t = ET.parse(R / "M8/tests.xml").getroot()
    ts = t if t.tag == "testsuite" else t.find("testsuite")
    return int(ts.get("tests")), int(ts.get("failures")) + int(ts.get("errors"))


claim("M8_tests", lambda: _junit()[0], "{}", "pytest (results/M8/tests.xml)", "results/M8/tests.xml")
claim("M8_tests_failed", lambda: _junit()[1], "{}", "pytest (results/M8/tests.xml)", "results/M8/tests.xml")

# ---------------------------------------------------------------- M10 end-to-end demo
E2E = "results/M10/e2e_demo.json"
claim("E2E_shots", lambda: J("M10/e2e_demo.json")["shots"], "{:,}", "sim (Verilator RTL + host protocol)", E2E)
claim("E2E_hw", lambda: J("M10/e2e_demo.json")["hw_committed"], "{:,}", "sim (Verilator RTL + host protocol)", E2E)
claim("E2E_sw", lambda: J("M10/e2e_demo.json")["sw_committed"], "{:,}", "sim (Verilator RTL + host protocol)", E2E)
claim("E2E_lost", lambda: J("M10/e2e_demo.json")["responses_lost_injected"], "{:,}", "fault injection", E2E)
claim("E2E_timeouts", lambda: J("M10/e2e_demo.json")["hw_status_counts_received"]["TIMEOUT"], "{:,}",
      "sim (Verilator RTL)", E2E)
claim("E2E_replay", lambda: "yes" if J("M10/e2e_demo.json")["wasm_replay_matches_committed"] else "NO", "{}",
      "Wasm replay (Node.js)", E2E)
claim("E2E_mm", lambda: J("M10/e2e_demo.json")["rtl_testbench"]["mismatches"], "{}", "sim (Verilator RTL)", E2E)


# ---------------------------------------------------------------- M3 summary / M5 V8 / M4 Wasm
def _formal_ok(r) -> bool:
    if r["tool"].startswith("TLC"):  # mutations and the pre-fix model must FAIL; the main models must pass
        expect_fail = any(t in r["job"] for t in ("mut_", "v0_"))
        return (not r["ok"]) if expect_fail else r["ok"]
    if r["tool"].startswith("Z3"):
        return r["ok"]
    return r["status"] == "PASS"


if _exists("M3/formal_summary.json"):
    FS = "results/M3/formal_summary.json"
    claim("M3_n_jobs", lambda: len(J("M3/formal_summary.json")), "{}", "formal", FS)
    claim("M3_n_pass", lambda: sum(_formal_ok(r) for r in J("M3/formal_summary.json")), "{}", "formal", FS)

V8T = "results/M5/v8_tests.json"
claim("M5_tests_ran", lambda: sum(x["ran"] for x in J("M5/v8_tests.json")["suites"]), "{:,}",
      "V8 test runner (run-tests.py), patched d8", V8T)
claim("M5_tests_failed", lambda: sum(x["failed"] for x in J("M5/v8_tests.json")["suites"]), "{}",
      "V8 test runner (run-tests.py), patched d8", V8T)
claim("M5_sites_fused", lambda: J("M5/v8_tests.json")["codegen_qsx_simd"]["patched"]["fused_cbz_cbnz"], "{}",
      "V8 --print-wasm-code (arm64)", V8T)
claim("M5_sites_total", lambda: J("M5/v8_tests.json")["codegen_qsx_simd"]["base"]["any_true_sites"], "{}",
      "V8 --print-wasm-code (arm64)", V8T)
if _exists("M5/anytrue_fusion.json"):
    AF = "results/M5/anytrue_fusion.json"
    claim("M5_micro_ratio_0", lambda: _find(J("M5/anytrue_fusion.json"), workload="micro zero_block_scan",
                                            nonzero_block_fraction=0.0)["ratio"], "{:.2f}",
          "d8 measurement (interleaved A/B, median)", AF)
    claim("M5_unpack_ratio_d9", lambda: _find(J("M5/anytrue_fusion.json"), workload="qsx d=9 p=0.001",
                                              metric="unpack_simd_ns_per_shot")["ratio"], "{:.2f}",
          "d8 measurement (interleaved A/B, median)", AF)
if _exists("M4/runtime.json"):
    RT = "results/M4/runtime.json"

    def _rt(d, label, key="steady_ns_per_shot"):
        row = _find(J("M4/runtime.json"), d=d)
        return next(r for r in row["runs"] if r["label"] == label)[key]

    claim("M4_wasm_simd_over_native_d5", lambda: _rt(5, "d8-simd-default") / _rt(5, "native-O3-neon"), "{:.2f}",
          "CPU measurement (d8 vs native)", RT)
    claim("M4_bitexact", lambda: "all" if all(r["bit_exact"] for r in J("M4/runtime.json")) else "NOT all", "{}",
          "FNV-1a hash comparison", RT)


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
    for src, tag in (("M7/federated_d3_clip_ablation.json", "lot 512, 4000 steps"),
                     ("M7/federated_d3.json", "lot 512, 4000 steps"),
                     ("M7/federated_d3_dp_b8192.json", "lot 8192, 300 steps"),
                     ("M7/federated_d3_dp_b8192_long.json", "lot 8192, 900 steps")):
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


def _knee():
    """Smallest epsilon whose P_L is within 5% of the least-private DP point at every site (lot-8192 sweep)."""
    dat = J("M7/federated_d3_dp_b8192.json")
    pts = sorted(((dat[g]["dp"]["epsilon"], dat[g]["eval"]) for g in dat
                  if g.startswith("fedavg-dp") and dat[g]["dp"]["sigma"] > 0), key=lambda x: -x[0])
    ref = pts[0][1]
    knee, nxt = pts[0], None
    for k, (eps, ev) in enumerate(pts):
        if all(ev[s]["pl"] <= 1.05 * ref[s]["pl"] for s in ref):
            knee, nxt = (eps, ev), (pts[k + 1] if k + 1 < len(pts) else None)
    return knee, nxt, ref


if _exists("M7/federated_d3_dp_b8192.json"):
    K7 = "results/M7/federated_d3_dp_b8192.json"
    claim("M7_knee_eps", lambda: _knee()[0][0], "{:.2f}", "DP accounting (Opacus RDP) + Monte Carlo", K7)
    claim("M7_below_knee_eps", lambda: _knee()[1][0], "{:.2f}", "DP accounting (Opacus RDP)", K7)
    claim("M7_below_knee_factor", lambda: min(_knee()[1][1][s]["pl"] / _knee()[0][1][s]["pl"] for s in _knee()[2]),
          "{:.1f}", "sim (Monte Carlo, Stim)", K7)
    claim("M7_max_eps", lambda: max(J("M7/federated_d3_dp_b8192.json")[g]["dp"]["epsilon"]
                                    for g in J("M7/federated_d3_dp_b8192.json") if g.startswith("fedavg-dp")
                                    and J("M7/federated_d3_dp_b8192.json")[g]["dp"]["sigma"] > 0), "{:.1f}",
          "DP accounting (Opacus RDP)", K7)


def _cfg(path: str) -> dict:
    import json as _json

    return _json.loads((R / path).read_text())["provenance"]["config"]


claim("M7_lot_small", lambda: _cfg("M7/federated_d3.json").get("dp_batch", _cfg("M7/federated_d3.json")["batch"]),
      "{}", "config (result provenance)", "results/M7/federated_d3.json")
claim("M7_lot_large", lambda: _cfg("M7/federated_d3_dp_b8192.json")["dp_batch"], "{}", "config (result provenance)",
      "results/M7/federated_d3_dp_b8192.json")


if _exists("M7/federated_d3_dp_b8192_long.json"):
    claim("M7_long_eps_s2", lambda: J("M7/federated_d3_dp_b8192_long.json")["fedavg-dp-sigma2.0"]["dp"]["epsilon"],
          "{:.2f}", "DP accounting (Opacus RDP)", "results/M7/federated_d3_dp_b8192_long.json")


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


# ---------------------------------------------------------------- M2 report (synth / pnr / latency / deadline)
if _exists("M2/report.json"):
    REP = "results/M2/report.json"
    _rep = J("M2/report.json")
    for r in _rep["configs"]:
        t = r["tag"].replace("_", "")
        claim(f"M2_lut_{t}", lambda r=r: r["synth"]["LUT4"], "{:,}", "synth (Yosys synth_ecp5)", REP)
        claim(f"M2_ff_{t}", lambda r=r: r["synth"]["FF"], "{:,}", "synth (Yosys synth_ecp5)", REP)
        if "pnr" in r:
            claim(f"M2_fmax_{t}", lambda r=r: r["pnr"]["fmax_mhz"], "{:.1f}", "pnr (nextpnr-ecp5, LFE5U-85F)", REP)
            claim(f"M2_util_{t}", lambda r=r: 100 * r["pnr"]["comb"] / r["pnr"]["comb_avail"], "{:.0f}",
                  "pnr (nextpnr-ecp5, LFE5U-85F)", REP)
        if "latency_ns" in r:
            for q in ("p50", "p99", "max"):
                claim(f"M2_{q}ns_{t}", lambda r=r, q=q: r["latency_ns"][q], "{:,.0f}", "sim cycles / pnr Fmax", REP)
        if "deadline" in r:
            claim(f"M2_fallback_{t}", lambda r=r: 100 * r["deadline"]["fallback_fraction"], "{:.2f}",
                  "sim cycles / pnr Fmax; bound by proof C2", REP)
            claim(f"M2_budget_{t}", lambda r=r: r["deadline"]["watchdog_budget_cycles"], "{:,}",
                  "sim cycles / pnr Fmax; bound by proof C2", REP)
    for e in _rep["hw_vs_cpu"]:
        d = e["d"]
        claim(f"M2_hw_p99_ns_d{d}", lambda e=e: e["hw_p99_ns"], "{:,.0f}", "sim cycles / pnr Fmax", REP)
        claim(f"M2_hw_max_ns_d{d}", lambda e=e: e["hw_max_ns"], "{:,.0f}", "sim cycles / pnr Fmax", REP)
        claim(f"M2_hw_best_d{d}", lambda e=e: _tex(e["hw_best_tag"]), "{}", "config", REP)
        for k in ("cpu_pm", "cpu_uf"):
            for q in ("p99", "p999", "max"):
                if f"{k}_{q}_ns" in e:
                    claim(f"M2_{k}_{q}_us_d{d}", lambda e=e, k=k, q=q: e[f"{k}_{q}_ns"] / 1000, "{:.2f}",
                          "CPU measurement (1 thread)", REP)
        if "cpu_pm_p99_ns" in e:
            claim(f"M2_ratio_p99_d{d}", lambda e=e: e["hw_p99_ns"] / e["cpu_pm_p99_ns"], "{:.2f}",
                  "sim cycles / pnr Fmax vs CPU measurement", REP)
            claim(f"M2_ratio_max_d{d}", lambda e=e: e["cpu_pm_max_ns"] / e["hw_max_ns"], "{:.1f}",
                  "sim cycles / pnr Fmax vs CPU measurement", REP)
        if e.get("hw_deadline"):
            claim(f"M2_hw_within_d{d}", lambda e=e: 100 * e["hw_deadline"]["hw_fraction_within"], "{:.1f}",
                  "sim cycles / pnr Fmax; bound by proof C2", REP)
            claim(f"M2_hw_fallback_d{d}", lambda e=e: 100 * e["hw_deadline"]["fallback_fraction"], "{:.2f}",
                  "sim cycles / pnr Fmax; bound by proof C2", REP)

    def _pipe_gain(d=3, L=32):
        f = {r["pipe"]: r["pnr"]["fmax_mhz"] for r in _rep["configs"]
             if r["d"] == d and r["lanes"] == L and r["weights"] == "q5" and "pnr" in r}
        return 100 * (f[1] / f[0] - 1)

    claim("M2_pipe_gain_pct_d3", _pipe_gain, "{:.0f}", "pnr (nextpnr-ecp5)", REP)
    def _min_lut(d):
        return min(r["synth"]["LUT4"] for r in _rep["configs"] if r["d"] == d and r["synth"]["LUT4"])

    claim("M2_min_lut_d7", lambda: _min_lut(7), "{:,}", "synth (Yosys synth_ecp5)", REP)
    claim("M2_d7_over_device", lambda: _min_lut(7) / 83640, "{:.1f}", "synth (Yosys) vs LFE5U-85F capacity", REP)

    def _fit_rows():
        rows = []
        for r in _rep["configs"]:
            t = r["tag"].replace("_", "")
            fit = "pnr" in r
            reason = "" if fit else _tex(r.get("pnr_error", "synth only")[:60])
            rows.append((r, t, fit, reason))
        return rows

    _FT = []
    for i, (r, t, fit, reason) in enumerate(_fit_rows()):
        claim(f"M2_ft_{i}_cfg", lambda r=r: f"$d={r['d']}$, {r['weights']}, L{r['lanes']}, P{r['pipe']}", "{}",
              "config", REP)
        claim(f"M2_ft_{i}_why", lambda reason=reason: reason, "{}", "pnr (nextpnr-ecp5)", REP)
        cells = [f"\\claim{{M2_ft_{i}_cfg}}", f"\\claim{{M2_lut_{t}}}", f"\\claim{{M2_ff_{t}}}"]
        if fit:
            cells += [f"\\claim{{M2_util_{t}}}", f"\\claim{{M2_fmax_{t}}}"]
            cells += ([f"\\claim{{M2_p99ns_{t}}}", f"\\claim{{M2_maxns_{t}}}"] if "latency_ns" in r else ["--", "--"])
            cells += [f"\\claim{{M2_fallback_{t}}}"] if "deadline" in r else ["--"]
        else:
            cells += [f"\\multicolumn{{5}}{{l}}{{\\claim{{M2_ft_{i}_why}}}}"]
        _FT.append(" & ".join(cells) + r" \\")

    @table("gen_fpga.tex")
    def _t_fpga():
        return "\n".join([
            r"\begin{table*}[t]\centering\small",
            r"\caption{FPGA implementation on the Lattice LFE5U-85F (open flow). LUT4/FF after Yosys synthesis"
            r" \stage{synth}; logic utilisation and Fmax after nextpnr place-and-route \stage{PnR}; latency per"
            r" $d$-round block at $p=0.003$ including the shell, cycles from the cycle-exact model divided by Fmax"
            r" \stage{sim/PnR}; fallback = share of frames that would exceed the $d\times 1\,\mu$s"
            r" block deadline and be answered WATCHDOG (then decoded in software).}",
            r"\label{tab:fpga}",
            r"\begin{tabular}{lrrrrrrr}\toprule configuration & LUT4 & FF & util.\,\% & Fmax MHz & p99 ns &"
            r" max ns & fallback \% \\ \midrule",
            *_FT, r"\bottomrule\end{tabular}\end{table*}"])


def tables() -> list[str]:
    written = []
    for name, fn in TABLES.items():
        (ROOT / "paper" / name).write_text("% AUTO-GENERATED by bench/claims_ext.py -- do not edit\n" + fn() + "\n")
        written.append(name)
    return written
