"""M2 FPGA flow: Yosys synth_ecp5 + nextpnr-ecp5 (LFE5U-85F, CABGA381, speed 8) per configuration.

Evidence stages written per configuration:
  synth: Yosys cell counts (LUT4, FF, CCU2C, DP16KD, MULT18X18D, ...)
  pnr:   nextpnr utilisation (TRELLIS_COMB/FF/RAMW/DP16KD/IO) and achieved Fmax (timing-driven, seed fixed)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build as build_graph  # noqa: E402

B = ROOT / "build"
DEVICE_LUTS = 83640  # LFE5U-85F TRELLIS_COMB capacity reported by nextpnr-ecp5
RTL = ["rtl/qsx_min_tree.sv", "rtl/qsx_uf_core.sv", "rtl/qsx_ingress.sv", "rtl/qsx_cfg.sv", "rtl/qsx_top.sv",
       "fpga/qsx_pnr_shell.sv"]


def tool_version(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = (r.stdout + r.stderr).strip().splitlines()  # nextpnr prints its version on stderr
    return lines[0] if lines else "unknown"


def prepare(d: int, weights: str) -> Path:
    gp = B / "graphs" / f"d{d}_{weights}.qsxg"
    _, g = build_graph(d, 0.001, weights=weights)
    g.write(str(gp))
    inc = B / "rtl" / f"d{d}_{weights}"
    subprocess.run([sys.executable, "rtl/gen_graph.py", "--graph", str(gp), "--out", str(inc)], cwd=ROOT,
                   check=True, capture_output=True)
    return inc


def run_cfg(d: int, weights: str, lanes: int, params: dict, pnr: bool, freq: float, seed: int,
            top_mod: str = "qsx_pnr_shell", timeout: int = 4 * 3600) -> dict:
    tag = (f"d{d}_{weights}_L{lanes}" + "".join(f"_{k}{v}" for k, v in sorted(params.items()))
           + ("" if top_mod == "qsx_pnr_shell" else f"_{top_mod}"))
    wd = B / "fpga" / tag
    wd.mkdir(parents=True, exist_ok=True)
    inc = B / "rtl" / f"d{d}_{weights}"
    chp = " ".join(f"-set {k} {v}" for k, v in {"LANES": lanes, **params}.items())
    srcs = " ".join(str(ROOT / s) for s in RTL)
    ys = (f"read_verilog -sv -I{inc} {srcs}; chparam {chp} {top_mod}; "
          f"synth_ecp5 -top {top_mod} -json {wd}/synth.json; tee -q -o {wd}/stat.json stat -json; "
          f"tee -q -o {wd}/stat.txt stat")
    res: dict = {"d": d, "weights": weights, "lanes": lanes, "params": params, "tag": tag, "top": top_mod}
    t0 = time.time()
    try:
        r = subprocess.run(["yosys", "-q", "-l", str(wd / "yosys.log"), "-p", ys], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        res["synth_error"] = f"synthesis timeout after {timeout} s"
        (wd / "result.json").write_text(json.dumps(res, indent=1))
        return res
    res["synth_s"] = round(time.time() - t0, 1)
    if r.returncode != 0:
        res["synth_error"] = (r.stderr or r.stdout)[-2000:]
        return res
    st = json.loads((wd / "stat.json").read_text())
    top = st["design"] if "design" in st else st["modules"][f"\\{top_mod}"]
    cells = top["num_cells_by_type"]
    res["synth"] = {"stage": "synth", "cells": {k: v for k, v in cells.items() if not k.startswith("$scope")}}
    if pnr and cells.get("LUT4", 0) > DEVICE_LUTS:
        res["pnr_error"] = f"does not fit: {cells['LUT4']} LUT4 after synthesis > {DEVICE_LUTS} on LFE5U-85F"
        res["fits"] = False
    elif pnr:
        t0 = time.time()
        r = subprocess.run(["nextpnr-ecp5", "--85k", "--package", "CABGA381", "--speed", "8", "--json",
                            str(wd / "synth.json"), "--freq", str(freq), "--timing-allow-fail", "--seed",
                            str(seed), "--report", str(wd / "report.json"), "-l", str(wd / "nextpnr.log"), "-q"],
                           capture_output=True, text=True, timeout=timeout)
        res["pnr_s"] = round(time.time() - t0, 1)
        if r.returncode != 0 or not (wd / "report.json").exists():
            log = (wd / "nextpnr.log").read_text() if (wd / "nextpnr.log").exists() else r.stderr
            m = re.findall(r"ERROR: .*", log)
            res["pnr_error"] = m[-1] if m else log[-1500:]
        else:
            rep = json.loads((wd / "report.json").read_text())
            fmax = min(v["achieved"] for v in rep["fmax"].values())
            res["pnr"] = {"stage": "pnr", "fmax_mhz": fmax, "target_mhz": freq,
                          "utilization": {k: v for k, v in rep["utilization"].items() if v["used"] > 0}}
    (wd / "result.json").write_text(json.dumps(res, indent=1))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    # spec: d:weights:lanes[:pipes]   (lists comma separated)
    ap.add_argument("--configs", default="3:q5:1,8,32:0,1;5:q5:1,4,8,16,32:0;5:q5:8,16:1;7:q5:4,8,16:0;7:q5:8,16:1;"
                                         "5:unweighted:8:0")
    ap.add_argument("--synth-only", default="9:q5:8:0,1")
    ap.add_argument("--core-only", default="3:q5:8:0;5:q5:8:0;7:q5:8:0",
                    help="synth of qsx_uf_core alone (M3 overhead)")
    ap.add_argument("--params", default="", help="extra chparams k=v,k=v applied to all configs")
    ap.add_argument("--freq", type=float, default=100.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=4 * 3600, help="per synthesis / PnR step, seconds")
    ap.add_argument("--collect", action="store_true",
                    help="do not run anything: assemble the result file from existing build/fpga/<tag>/result.json")
    ap.add_argument("--name", default=None, help="result file name (default: fpga_<params or base>.json)")
    ap.add_argument("--out", default=str(ROOT / "results/M2/fpga"))
    a = ap.parse_args()
    params = dict(kv.split("=") for kv in a.params.split(",") if kv)
    jobs = []
    prepared = set()
    for spec, pnr, top_mod in [(a.configs, True, "qsx_pnr_shell"), (a.synth_only, False, "qsx_pnr_shell"),
                               (a.core_only, False, "qsx_uf_core")]:
        for item in filter(None, spec.split(";")):
            parts = item.split(":")
            d, w, ls = parts[:3]
            pipes = parts[3] if len(parts) > 3 else "0"
            if (d, w) not in prepared and not a.collect:
                prepare(int(d), w)
                prepared.add((d, w))
            for L in map(int, ls.split(",")):
                for P in map(int, pipes.split(",")):
                    jobs.append((int(d), w, L, {**params, "PIPE": P}, pnr, top_mod))
    # smallest first: the configurations that fit the device produce results early
    jobs.sort(key=lambda j: (j[0], j[2]))

    def one(j):
        if a.collect:
            d, w, L, prm, _pnr, top_mod = j
            tag = (f"d{d}_{w}_L{L}" + "".join(f"_{k}{v}" for k, v in sorted(prm.items()))
                   + ("" if top_mod == "qsx_pnr_shell" else f"_{top_mod}"))
            f = B / "fpga" / tag / "result.json"
            return json.loads(f.read_text()) if f.exists() else {"d": d, "weights": w, "lanes": L, "params": prm,
                                                                   "top": top_mod, "tag": tag,
                                                                   "synth_error": "no result (not run)"}
        try:
            return run_cfg(*j[:5], a.freq, a.seed, j[5], a.timeout)
        except subprocess.TimeoutExpired:
            return {"d": j[0], "weights": j[1], "lanes": j[2], "params": j[3], "top": j[5],
                    "tag": f"d{j[0]}_{j[1]}_L{j[2]}", "pnr_error": f"PnR timeout after {a.timeout} s"}

    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, jobs))
    for r in sorted(res, key=lambda r: (r["d"], r["weights"], r["lanes"])):
        s = r.get("synth", {}).get("cells", {})
        p = r.get("pnr", {})
        print(f"{r['tag']:28s} LUT4={s.get('LUT4', '-'):>7} FF={s.get('TRELLIS_FF', '-'):>6} "
              f"fmax={p.get('fmax_mhz', float('nan')):.1f} {r.get('pnr_error', '')[:80]}")
    out = Path(a.out)
    tag = "_".join(f"{k}{v}" for k, v in params.items()) or "base"
    write_result(out / (a.name or f"fpga_{tag}.json"), res, vars(a), a.seed,
                 extra_tools={"yosys": tool_version(["yosys", "-V"]),
                              "nextpnr-ecp5": tool_version(["nextpnr-ecp5", "--version"]),
                              "device": "LFE5U-85F CABGA381 speed 8"})


if __name__ == "__main__":
    main()
