"""M2 hardware latency + activity measurements (evidence stage: sim).

  cycles : core busy-cycle distributions from qsx::HwModel, which is cycle-exact with rtl/qsx_uf_core.sv
           (verified per syndrome in co-simulation, results/M2/cosim/). d x p x LANES x PIPE grid,
           Stim-sampled syndromes, decoder graph built for the same p (q5 thresholds, as in M1).
  shell  : end-to-end cycles of rtl/qsx_top.sv in Verilator (first input beat accepted -> output header
           accepted; one frame in flight, no gaps / backpressure). Difference to the core cycles = framing
           and handshake overhead of the shell (M3 overhead table).
  toggle : Verilator --coverage-toggle bit-toggle counts per decode (switching-activity proxy for dynamic
           energy, BLOCKERS B3). Relative estimate only; not Watts.

Outputs: results/M2/hw_cycles.json, results/M2/shell_latency.json, results/M2/toggle_proxy.json.
Converting cycles to ns needs an Fmax, which comes from place-and-route (results/M2/fpga/); see bench/m2_report.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "tb"))
from bench.provenance import write_result  # noqa: E402
from run_cosim import RTL, build_sim, prepare_graph, sh  # noqa: E402
from sim.qsx_graph import build as build_graph  # noqa: E402

B = ROOT / "build"
OUT = ROOT / "results" / "M2"


def sample(d: int, p: float, n: int, seed: int) -> tuple[Path, np.ndarray]:
    c, g = build_graph(d, p, weights="q5")
    gp = B / "m2hw" / f"d{d}_p{p:g}_q5.qsxg"
    gp.parent.mkdir(parents=True, exist_ok=True)
    g.write(str(gp))
    dets = c.compile_detector_sampler(seed=seed).sample(n, bit_packed=False).astype(np.uint8)
    return gp, dets


def pct(x: np.ndarray) -> dict:
    return {"mean": float(x.mean()), "p50": float(np.percentile(x, 50)), "p99": float(np.percentile(x, 99)),
            "p999": float(np.percentile(x, 99.9)), "max": int(x.max())}


def cycles_grid(a) -> list[dict]:
    import qsxdec

    rows = []
    for d in map(int, a.distances.split(",")):
        for p in map(float, a.ps.split(",")):
            gp, dets = sample(d, p, a.shots, a.seed + d * 1000 + int(p * 1e5))
            dec = qsxdec.Decoder(str(gp))

            def one(lp, dec=dec, dets=dets):
                L, P = lp
                _, status, cyc = dec.decode_batch_hw(dets, lanes=L, pipe=P)
                return L, P, status, cyc

            lanes = [dec.V if x == "V" else int(x) for x in a.lanes.split(",")]  # "V": one lane per vertex
            lps = [(L, P) for L in lanes for P in (0, 1)]
            with ThreadPoolExecutor(a.jobs) as ex:
                for L, P, status, cyc in ex.map(one, lps):
                    vals, cnts = np.unique(cyc, return_counts=True)
                    rows.append({"d": d, "p": p, "lanes": L, "pipe": P, "shots": int(len(cyc)),
                                 "non_ok": int((status != 0).sum()), "cycles": pct(cyc.astype(np.float64)),
                                 "hist": [[int(v), int(c)] for v, c in zip(vals, cnts)],
                                 "stage": "sim (cycle-exact HwModel, co-sim verified)"})
                    print(f"cycles d={d} p={p} L={L} P={P} p50={rows[-1]['cycles']['p50']:.0f} "
                          f"p99={rows[-1]['cycles']['p99']:.0f}", flush=True)
    return rows


def shell_latency(a) -> list[dict]:
    import qsxdec

    rows = []
    for d in map(int, a.shell_distances.split(",")):
        gp, inc, tbits = prepare_graph(d)
        top = build_sim("top", d, 8, inc, tbits)
        c, _ = build_graph(d, a.shell_p)
        dets = c.compile_detector_sampler(seed=a.seed + 77 + d).sample(a.shell_shots, bit_packed=True)
        f = B / "m2hw" / f"shell_d{d}.b8"
        dets.tofile(f)
        r = json.loads(sh([str(top), "--graph", str(gp), "--lanes", "8", "--stim", str(f), "--latency", "1",
                           "--seed", str(a.seed)]).strip().splitlines()[-1])
        unpacked = np.unpackbits(dets, axis=1, bitorder="little")[:, : qsxdec.Decoder(str(gp)).V].astype(np.uint8)
        _, _, cyc = qsxdec.Decoder(str(gp)).decode_batch_hw(unpacked, lanes=8)
        rows.append({"d": d, "p": a.shell_p, "lanes": 8, "shots": a.shell_shots, "mismatches": r["mismatches"],
                     "e2e_cycles": r["latency_cycles"], "core_cycles": pct(cyc.astype(np.float64)),
                     "overhead_cycles_mean": r["latency_cycles"]["mean"] - float(cyc.mean()),
                     "stage": "sim (Verilator, qsx_top)"})
        print(f"shell d={d} e2e mean={r['latency_cycles']['mean']:.1f} core mean={cyc.mean():.1f}", flush=True)
    return rows


def toggle_proxy(a) -> list[dict]:
    rows = []
    for d in map(int, a.toggle_distances.split(",")):
        gp, inc, tbits = prepare_graph(d)
        mdir = B / "sim" / f"toggle_d{d}_L8"
        exe = mdir / "toggle_tb"
        if not exe.exists() or exe.stat().st_mtime < max((ROOT / s).stat().st_mtime for s in RTL[:2]
                                                         + ["tb/toggle_tb.cpp"]):
            mdir.mkdir(parents=True, exist_ok=True)
            # --output-split: the coverage-instrumented model is huge; sharding it keeps C++ compile times sane
            sh(["verilator", "--cc", "--exe", "--build", "-j", "8", "-O3", "--coverage-toggle", "--output-split",
                "20000", "--coverage-max-width", "1000000", "--x-assign", "fast", "--x-initial", "fast", f"-I{inc}",
                "--Mdir", str(mdir), "-GLANES=8", "-GPIPE=0", *RTL[:2], "--top-module", "qsx_uf_core",
                "tb/toggle_tb.cpp", str(ROOT / "decoders/src/decoder.cpp"),
                "-CFLAGS", f"-std=c++17 -O1 -I{ROOT}/decoders/include -DQSX_TB={tbits}", "-o", "toggle_tb"])
        for p in map(float, a.ps.split(",")):
            c, _ = build_graph(d, p)
            f = B / "m2hw" / f"toggle_d{d}_p{p:g}.b8"
            c.compile_detector_sampler(seed=a.seed + 5 + d).sample(a.toggle_shots, bit_packed=True).tofile(f)
            cov = B / "m2hw" / f"toggle_d{d}_p{p:g}.dat"
            r = json.loads(sh([str(exe), "--graph", str(gp), "--stim", str(f), "--cov", str(cov)]).strip()
                           .splitlines()[-1])
            total = 0
            points = 0
            for line in cov.read_text(errors="replace").splitlines():
                if line.startswith("C ") and "toggle" in line:
                    total += int(line.rsplit(" ", 1)[1])
                    points += 1
            rows.append({"d": d, "p": p, "lanes": 8, "shots": r["shots"], "cycles": r["cycles"],
                         "busy_cycles": r["busy_cycles"], "toggle_points": points, "toggles": total,
                         "toggles_per_decode": total / r["shots"], "toggles_per_cycle": total / r["cycles"],
                         "stage": "estimate (Verilator toggle-count activity proxy, not Watts)"})
            print(f"toggle d={d} p={p} toggles/decode={total / r['shots']:.0f} points={points}", flush=True)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", default="cycles,shell,toggle")
    ap.add_argument("--distances", default="3,5,7,9")
    ap.add_argument("--ps", default="0.001,0.003,0.006")
    ap.add_argument("--lanes", default="1,4,8,16,32,V")
    ap.add_argument("--shots", type=int, default=100_000)
    ap.add_argument("--shell-distances", default="3,5,7")
    ap.add_argument("--shell-p", type=float, default=0.003)
    ap.add_argument("--shell-shots", type=int, default=20_000)
    ap.add_argument("--toggle-distances", default="3,5,7")
    ap.add_argument("--toggle-shots", type=int, default=5_000)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=2002)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out)
    vl = {"verilator": sh(["verilator", "--version"]).strip()}
    what = a.what.split(",")
    if "cycles" in what:
        write_result(out / "hw_cycles.json", cycles_grid(a), vars(a), a.seed)
    if "shell" in what:
        write_result(out / "shell_latency.json", shell_latency(a), vars(a), a.seed, extra_tools=vl)
    if "toggle" in what:
        write_result(out / "toggle_proxy.json", toggle_proxy(a), vars(a), a.seed, extra_tools=vl)


if __name__ == "__main__":
    main()
