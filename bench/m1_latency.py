"""M1: single-thread CPU latency/throughput of PyMatching (C++) and QSX-UF (C++, fast impl).

Runs sequentially (no other benchmark load) on identical Stim shots. Latency is per decoding block
(d rounds of syndrome extraction); per-round figures divide by d (amortised, labelled as such).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build  # noqa: E402

B = ROOT / "build"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5,7,9")
    ap.add_argument("--ps", default="0.001,0.003,0.005")
    ap.add_argument("--shots", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "results/M1/latency.json"))
    a = ap.parse_args()
    rows = []
    for d in map(int, a.distances.split(",")):
        for p in map(float, a.ps.split(",")):
            c, _ = build(d, p)
            tmp = Path(tempfile.mkdtemp(dir=B / "tmp"))
            (tmp / "c.dem").write_text(str(c.detector_error_model(decompose_errors=True)))
            dets, obs = c.compile_detector_sampler(seed=a.seed).sample(a.shots, separate_observables=True,
                                                                      bit_packed=True)
            dets.tofile(tmp / "d.b8")
            obs.tofile(tmp / "o.b8")
            res = {}
            r = subprocess.run([str(B / "pm_bench"), "--dem", str(tmp / "c.dem"), "--dets", str(tmp / "d.b8"),
                                "--obs", str(tmp / "o.b8")], capture_output=True, text=True, check=True)
            res["pymatching"] = json.loads(r.stdout)
            for w in ["unweighted", "q5"]:
                _, g = build(d, p, weights=w)
                g.write(str(tmp / "g.qsxg"))
                r = subprocess.run([str(B / "qsx_decode"), "--graph", str(tmp / "g.qsxg"), "--dets",
                                    str(tmp / "d.b8"), "--obs", str(tmp / "o.b8")],
                                   capture_output=True, text=True, check=True)
                res[f"qsxuf-{w}"] = json.loads(r.stdout)
            for k, v in res.items():
                v["throughput_shots_per_s"] = v["shots"] / v["wall_s"]
                v["lat_ns_p99_per_round_amortised"] = v["lat_ns_p99"] / d
                rows.append({"d": d, "p": p, "decoder": k, **v})
                print(f"d={d} p={p} {k:18s} p50={v['lat_ns_p50']:8.0f}ns p99={v['lat_ns_p99']:8.0f}ns "
                      f"thr={v['throughput_shots_per_s']:10.0f}/s err={v['errors']}")
            for f in tmp.iterdir():
                f.unlink()
            tmp.rmdir()
    write_result(a.out, rows, vars(a), a.seed,
                 extra_tools={"timer": "std::chrono::steady_clock, single thread"})


if __name__ == "__main__":
    main()
