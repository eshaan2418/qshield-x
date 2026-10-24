"""M5 before/after measurement of the arm64 v128.any_true branch fusion (v8/patches/).

Two d8 binaries built from the same V8 revision (build/v8_rev.txt) with identical args.gn:
  base    = build/v8_base/d8            (unpatched)
  patched = v8/src/v8/out/rel/d8        (with v8/patches/0001-*.patch)
Workloads (runs alternate base/patched; each trial is a fresh d8 process):
  micro : v8/reduced/zero_block_scan.js -- the zero-block skip loop from qsx::unpack_simd over 64 KiB
  qsx   : wasm/harness.js with the Emscripten SIMD build of the QSX-UF decoder (unpack kernel + full decode)
Reported: per-trial values, medians, and a bootstrap 95% CI of median(patched)/median(base).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build  # noqa: E402

V8 = ROOT / "v8/src/v8"
D8 = {"base": ROOT / "build/v8_base/d8", "patched": V8 / "out/rel/d8"}


def run(d8: Path, args: list[str]) -> dict:
    r = subprocess.run([str(d8), *args], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:] + r.stdout[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def ratio_ci(base: list[float], new: list[float], seed: int = 0, n: int = 4000) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    b, x = np.asarray(base), np.asarray(new)
    boots = [np.median(rng.choice(x, len(x))) / np.median(rng.choice(b, len(b))) for _ in range(n)]
    return float(np.median(x) / np.median(b)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=11)
    ap.add_argument("--densities", default="0,0.05,0.25")
    ap.add_argument("--qsx", default="5:0.001,7:0.001,9:0.001,9:0.003")
    ap.add_argument("--shots", type=int, default=50_000)
    ap.add_argument("--seed", type=int, default=55)
    ap.add_argument("--out", default=str(ROOT / "results/M5/anytrue_fusion.json"))
    a = ap.parse_args()
    rows = []
    for dens in map(float, a.densities.split(",")):
        vals: dict = {"base": [], "patched": []}
        for t in range(a.trials):
            for k in ("base", "patched") if t % 2 == 0 else ("patched", "base"):
                r = run(D8[k], ["v8/reduced/zero_block_scan.js", "--", str(dens), str(a.seed + t)])
                vals[k].append(r["ns_per_block"])
        rr = ratio_ci(vals["base"], vals["patched"], a.seed)
        rows.append({"workload": "micro zero_block_scan", "nonzero_block_fraction": dens, "metric": "ns_per_block",
                     "base": vals["base"], "patched": vals["patched"], "median_base": float(np.median(vals["base"])),
                     "median_patched": float(np.median(vals["patched"])), "ratio": rr[0], "ratio_ci95": rr[1:]})
        print(json.dumps({k: rows[-1][k] for k in ("workload", "nonzero_block_fraction", "median_base",
                                                     "median_patched", "ratio", "ratio_ci95")}), flush=True)
    data = ROOT / "build/m5"
    data.mkdir(parents=True, exist_ok=True)
    for spec in a.qsx.split(","):
        d, p = int(spec.split(":")[0]), float(spec.split(":")[1])
        c, g = build(d, p, weights="q5")
        gp, dp = data / f"d{d}_p{p:g}.qsxg", data / f"d{d}_p{p:g}.b8"
        g.write(str(gp))
        c.compile_detector_sampler(seed=a.seed + d).sample(a.shots, bit_packed=True).tofile(dp)
        vals = {k: {"unpack_simd": [], "steady": [], "hash": set()} for k in D8}
        for t in range(a.trials):
            for k in ("base", "patched") if t % 2 == 0 else ("patched", "base"):
                r = run(D8[k], ["wasm/harness.js", "--", "wasm/dist/qsx_simd.js", "wasm/dist/qsx_simd.wasm",
                                str(gp), str(dp), "-", f"d8-{k}", "2"])
                vals[k]["unpack_simd"].append(r["unpack_ns_per_shot"]["simd"])
                vals[k]["steady"].append(r["steady_ns_per_shot"])
                vals[k]["hash"].add(r["hash"])
        for metric in ("unpack_simd", "steady"):
            rr = ratio_ci(vals["base"][metric], vals["patched"][metric], a.seed)
            rows.append({"workload": f"qsx d={d} p={p:g}", "d": d, "p": p, "metric": f"{metric}_ns_per_shot",
                         "base": vals["base"][metric], "patched": vals["patched"][metric],
                         "median_base": float(np.median(vals["base"][metric])),
                         "median_patched": float(np.median(vals["patched"][metric])),
                         "ratio": rr[0], "ratio_ci95": rr[1:],
                         "bit_exact": len(vals["base"]["hash"] | vals["patched"]["hash"]) == 1})
            print(json.dumps({k: rows[-1][k] for k in ("workload", "metric", "median_base", "median_patched",
                                                         "ratio", "ratio_ci95", "bit_exact")}), flush=True)
    rev = (ROOT / "build/v8_rev.txt").read_text().strip()
    write_result(a.out, rows, vars(a), a.seed, extra_tools={"v8_rev": rev, "d8_args_gn":
                                                             (V8 / "out/rel/args.gn").read_text()})


if __name__ == "__main__":
    main()
