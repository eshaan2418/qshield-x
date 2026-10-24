"""M3: cost of the mechanisms that the verified properties rely on.

Area (stage: synth). Yosys synth_ecp5 -noflatten of qsx_top (LANES=8) gives per-module cell counts:
  qsx_uf_core  -- the decoder itself (C1-C5 safety gating: status != OK => zero correction, watchdog)
  qsx_ingress  -- commit-on-last frame FIFO with backpressure (I1, P3)
  qsx_cfg      -- atomic BEGIN/WRITE/COMMIT session, written-word bitmap, threshold range check (P5, P6)
  qsx_top glue -- dispatcher, round-tag propagation, egress formatting, status gating (P1-P4)
Everything outside qsx_uf_core is counted as overhead of the verified shell. Formal-only logic is under
`ifdef FORMAL` and is not synthesised.
Latency (stage: sim). End-to-end cycles of qsx_top minus core busy cycles (results/M2/shell_latency.json).
Output: results/M3/overhead.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tb"))
from bench.provenance import write_result  # noqa: E402
from run_cosim import RTL, prepare_graph  # noqa: E402

B = ROOT / "build"
KEYS = ("LUT4", "TRELLIS_FF", "CCU2C", "DP16KD", "TRELLIS_DPR16X4", "PFUMX", "L6MUX21")


def synth_hier(d: int, lanes: int) -> dict:
    _, inc, _ = prepare_graph(d)
    wd = B / "m3_overhead" / f"d{d}_L{lanes}"
    wd.mkdir(parents=True, exist_ok=True)
    srcs = " ".join(str(ROOT / s) for s in RTL)
    ys = (f"read_verilog -sv -I{inc} {srcs}; chparam -set LANES {lanes} qsx_top; "
          f"synth_ecp5 -noflatten -top qsx_top; tee -q -o {wd}/stat.json stat -json")
    subprocess.run(["yosys", "-q", "-l", str(wd / "yosys.log"), "-p", ys], check=True, capture_output=True)
    st = json.loads((wd / "stat.json").read_text())
    mods = {}
    for name, m in st["modules"].items():
        cells = {k: v for k, v in m.get("num_cells_by_type", {}).items() if k in KEYS}
        mods[name.lstrip("\\")] = cells
    return mods


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5")
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "results/M3/overhead.json"))
    a = ap.parse_args()
    rows = []
    shell = {}
    sl = ROOT / "results/M2/shell_latency.json"
    if sl.exists():
        shell = {r["d"]: r for r in json.loads(sl.read_text())["data"]}
    for d in map(int, a.distances.split(",")):
        mods = synth_hier(d, a.lanes)
        core = next(v for k, v in mods.items() if "qsx_uf_core" in k)
        # qsx_min_tree instances are part of the core; everything else is shell
        core_tot = {k: sum(v.get(k, 0) for m, v in mods.items() if "qsx_uf_core" in m or "qsx_min_tree" in m)
                    for k in KEYS}
        shell_tot = {k: sum(v.get(k, 0) for m, v in mods.items()
                            if "qsx_uf_core" not in m and "qsx_min_tree" not in m) for k in KEYS}
        row = {"d": d, "lanes": a.lanes, "stage": "synth (Yosys synth_ecp5 -noflatten)", "modules": mods,
               "core": core_tot, "shell": shell_tot, "core_module_only": core,
               "shell_lut_fraction": shell_tot["LUT4"] / max(1, shell_tot["LUT4"] + core_tot["LUT4"]),
               "shell_ff_fraction": shell_tot["TRELLIS_FF"] / max(1, shell_tot["TRELLIS_FF"] + core_tot["TRELLIS_FF"])}
        if d in shell:
            s = shell[d]
            row["latency"] = {"stage": s["stage"], "e2e_mean": s["e2e_cycles"]["mean"],
                              "core_mean": s["core_cycles"]["mean"], "overhead_cycles_mean": s["overhead_cycles_mean"],
                              "overhead_fraction": s["overhead_cycles_mean"] / s["e2e_cycles"]["mean"]}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("d", "core", "shell", "shell_lut_fraction")}), flush=True)
    ver = subprocess.run(["yosys", "-V"], capture_output=True, text=True).stdout.strip()
    write_result(a.out, rows, vars(a), None, extra_tools={"yosys": ver})


if __name__ == "__main__":
    main()
