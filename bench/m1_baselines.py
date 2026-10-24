"""M1: software baselines. P_L vs p for PyMatching (C++ sparse blossom) and QSX-UF.

Each (d, p) point: sample Stim detection events in chunks, decode the *same* shots with every
decoder (native C++ harnesses, single-threaded), stop at --target-errors for the best decoder
or --max-shots. Writes one provenance-stamped JSON per point plus a summary.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.provenance import write_result  # noqa: E402
from bench.stats import clopper_pearson, per_round  # noqa: E402
from sim.qsx_graph import build  # noqa: E402

BUILD = ROOT / "build"


def run_point(d: int, p: float, weights: list[str], max_shots: int, target_errors: int, chunk: int,
              seed: int, outdir: str) -> dict:
    circ, _ = build(d, p)
    dem = circ.detector_error_model(decompose_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"m1_d{d}_p{p}_", dir=os.environ.get("QSX_TMP")))
    (tmp / "c.dem").write_text(str(dem))
    graphs = {}
    for w in weights:
        _, g = build(d, p, weights=w)
        gp = tmp / f"g_{w}.qsxg"
        g.write(str(gp))
        graphs[w] = gp
    sampler = circ.compile_detector_sampler(seed=seed)
    decoders = ["pymatching"] + [f"qsxuf-{w}" for w in weights]
    tot = {k: {"errors": 0, "timeouts": 0, "parity_errors": 0, "rounds_sum": 0.0} for k in decoders}
    shots = 0
    while shots < max_shots:
        n = min(chunk, max_shots - shots)
        dets, obs = sampler.sample(n, separate_observables=True, bit_packed=True)
        dets.tofile(tmp / "dets.b8")
        obs.tofile(tmp / "obs.b8")
        out = subprocess.run([str(BUILD / "pm_bench"), "--dem", str(tmp / "c.dem"), "--dets", str(tmp / "dets.b8"),
                              "--obs", str(tmp / "obs.b8")], capture_output=True, text=True, check=True).stdout
        tot["pymatching"]["errors"] += json.loads(out)["errors"]
        for w in weights:
            out = subprocess.run([str(BUILD / "qsx_decode"), "--graph", str(graphs[w]), "--dets", str(tmp / "dets.b8"),
                                  "--obs", str(tmp / "obs.b8")], capture_output=True, text=True, check=True).stdout
            r = json.loads(out)
            t = tot[f"qsxuf-{w}"]
            t["errors"] += r["errors"]
            t["timeouts"] += r["timeouts"]
            t["parity_errors"] += r["parity_errors"]
            t["rounds_sum"] += r["mean_rounds"] * n
        shots += n
        if min(tot[k]["errors"] for k in decoders) >= target_errors:
            break
    res = {"d": d, "p": p, "rounds": d, "shots": shots, "decoders": {}}
    for k in decoders:
        e = tot[k]["errors"]
        lo, hi = clopper_pearson(e, shots)
        entry = {"errors": e, "pl": e / shots, "ci95": [lo, hi], "pl_per_round": per_round(e / shots, d),
                 "ci95_per_round": [per_round(lo, d), per_round(hi, d)]}
        if k != "pymatching":
            entry.update({"timeouts": tot[k]["timeouts"], "parity_errors": tot[k]["parity_errors"],
                          "mean_growth_rounds": tot[k]["rounds_sum"] / shots})
        res["decoders"][k] = entry
    cfg = {"d": d, "p": p, "weights": weights, "max_shots": max_shots, "target_errors": target_errors,
           "chunk": chunk, "noise": "stim rotated_memory_z uniform circuit-level depolarizing (DECISIONS D2)"}
    write_result(Path(outdir) / f"pl_d{d}_p{p:g}.json", res, cfg, seed)
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5,7,9")
    ap.add_argument("--ps", default="0.001,0.002,0.003,0.004,0.005,0.006,0.007,0.008,0.01")
    ap.add_argument("--weights", default="unweighted")
    ap.add_argument("--max-shots", type=int, default=2_000_000)
    ap.add_argument("--target-errors", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=100_000)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--out", default=str(ROOT / "results/M1"))
    a = ap.parse_args()
    ds = [int(x) for x in a.distances.split(",")]
    ps = [float(x) for x in a.ps.split(",")]
    ws = a.weights.split(",")
    jobs = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for d in ds:
            for i, p in enumerate(ps):
                seed = a.seed + 1000 * d + i
                jobs.append(ex.submit(run_point, d, p, ws, a.max_shots, a.target_errors, a.chunk, seed, a.out))
        results = [j.result() for j in jobs]
    for r in sorted(results, key=lambda r: (r["d"], r["p"])):
        line = f"d={r['d']} p={r['p']:<6g} shots={r['shots']:>8} " + " ".join(
            f"{k}={v['pl']:.3e}" for k, v in r["decoders"].items())
        print(line)


if __name__ == "__main__":
    main()
