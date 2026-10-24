"""M2 co-simulation campaign (Verilator RTL vs qsx::HwModel).

Per distance d:
  * core-level: --random N random syndromes (densities 0..0.9) + --stim M Stim-sampled syndromes
    (equal shares at p in STIM_PS), LANES=8, split into parallel chunks with distinct seeds;
  * core-level lanes sweep (smaller): LANES in --lanes-sweep;
  * top-level (AXI-Stream, FIFO, config): random + Stim frames with gaps/backpressure/malformed frames
    and reconfiguration sessions.
Every chunk must report mismatches == 0. Results: results/M2/cosim/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build as build_graph  # noqa: E402

B = ROOT / "build"
RTL = ["rtl/qsx_min_tree.sv", "rtl/qsx_uf_core.sv", "rtl/qsx_ingress.sv", "rtl/qsx_cfg.sv", "rtl/qsx_top.sv"]
STIM_PS = [0.001, 0.003, 0.006, 0.01]


def sh(cmd: list[str], **kw) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return r.stdout


def prepare_graph(d: int, weights: str = "q5") -> tuple[Path, Path, int]:
    gp = B / "graphs" / f"d{d}_{weights}.qsxg"
    gp.parent.mkdir(parents=True, exist_ok=True)
    _, g = build_graph(d, 0.001, weights=weights)
    g.write(str(gp))
    inc = B / "rtl" / f"d{d}_{weights}"
    out = sh([sys.executable, "rtl/gen_graph.py", "--graph", str(gp), "--out", str(inc)])
    tb = int(out.split("'TB': ")[1].split(",")[0])
    return gp, inc, tb


def build_sim(kind: str, d: int, lanes: int, inc: Path, tbits: int) -> Path:
    mdir = B / "sim" / f"{kind}_d{d}_L{lanes}"
    exe = mdir / f"{kind}_tb"
    srcs = RTL if kind == "top" else RTL[:2]
    stamp = max(os.path.getmtime(ROOT / s) for s in srcs + [f"tb/{kind}_tb.cpp", "decoders/src/decoder.cpp"])
    if exe.exists() and os.path.getmtime(exe) > max(stamp, os.path.getmtime(inc / "qsx_graph_tables.svh")):
        return exe
    sh(["verilator", "--cc", "--exe", "--build", "-j", "8", "-O3", "--x-assign", "fast", "--x-initial", "fast",
        f"-I{inc}", "--Mdir", str(mdir), f"-GLANES={lanes}", *srcs, "--top-module", f"qsx_{'top' if kind == 'top' else 'uf_core'}",
        f"tb/{kind}_tb.cpp", str(ROOT / "decoders/src/decoder.cpp"),
        "-CFLAGS", f"-std=c++17 -O2 -I{ROOT}/decoders/include -DQSX_TB={tbits}", "-o", f"{kind}_tb"])
    return exe


def stim_file(d: int, n: int, seed: int, tag: str) -> Path:
    import numpy as np

    path = B / "tmp" / f"stim_d{d}_{tag}_{n}_{seed}.b8"
    if path.exists():
        return path
    chunks = []
    per = n // len(STIM_PS)
    for i, p in enumerate(STIM_PS):
        c, _ = build_graph(d, p)
        dets = c.compile_detector_sampler(seed=seed + i).sample(per if i < len(STIM_PS) - 1 else n - per * i,
                                                                bit_packed=True)
        chunks.append(dets)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.concatenate(chunks).tofile(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5,7")
    ap.add_argument("--random", type=int, default=1_000_000)
    ap.add_argument("--stim", type=int, default=100_000)
    ap.add_argument("--chunks", type=int, default=16)
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--lanes-sweep", default="1,4,16,32")
    ap.add_argument("--sweep-random", type=int, default=20_000)
    ap.add_argument("--top-random", type=int, default=50_000)
    ap.add_argument("--top-stim", type=int, default=50_000)
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--seed", type=int, default=424242)
    ap.add_argument("--out", default=str(ROOT / "results/M2/cosim"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for d in map(int, a.distances.split(",")):
        gp, inc, tbits = prepare_graph(d)
        core = build_sim("core", d, a.lanes, inc, tbits)
        top = build_sim("top", d, a.lanes, inc, tbits)
        sweep_exes = {L: build_sim("core", d, L, inc, tbits) for L in map(int, a.lanes_sweep.split(",")) if L}
        tasks = []
        per = a.random // a.chunks
        for c in range(a.chunks):
            tasks.append(("core-random", [str(core), "--graph", str(gp), "--lanes", str(a.lanes),
                                          "--random", str(per if c < a.chunks - 1 else a.random - per * c),
                                          "--seed", str(a.seed + 100 * d + c)]))
        sper = a.stim // a.chunks
        for c in range(a.chunks):
            n = sper if c < a.chunks - 1 else a.stim - sper * c
            f = stim_file(d, n, a.seed + 7000 + 100 * d + 10 * c, f"core{c}")
            tasks.append(("core-stim", [str(core), "--graph", str(gp), "--lanes", str(a.lanes), "--stim", str(f)]))
        for L, exe in sweep_exes.items():
            tasks.append((f"core-random-L{L}", [str(exe), "--graph", str(gp), "--lanes", str(L), "--random",
                                                str(a.sweep_random), "--seed", str(a.seed + 31 * L + d)]))
        tchunks = max(1, a.chunks // 4)
        for c in range(tchunks):
            tasks.append(("top-random-stress", [str(top), "--graph", str(gp), "--lanes", str(a.lanes), "--random",
                                                str(a.top_random // tchunks), "--seed", str(a.seed + 9000 + c),
                                                "--gap", "0.2", "--bp", "0.3", "--malformed", "0.02",
                                                "--reconfig", "1"]))
            f = stim_file(d, a.top_stim // tchunks, a.seed + 11000 + 100 * d + c, f"top{c}")
            tasks.append(("top-stim-stress", [str(top), "--graph", str(gp), "--lanes", str(a.lanes), "--stim", str(f),
                                              "--gap", "0.1", "--bp", "0.2", "--seed", str(a.seed + 12000 + c)]))

        def run(t):
            kind, cmd = t
            r = json.loads(sh(cmd).strip().splitlines()[-1])
            r["kind"] = kind
            return r

        with ThreadPoolExecutor(a.jobs) as ex:
            rs = list(ex.map(run, tasks))
        agg: dict = {}
        for r in rs:
            k = r["kind"]
            g = agg.setdefault(k, {"d": d, "kind": k, "syndromes": 0, "mismatches": 0, "chunks": 0})
            g["syndromes"] += r.get("random", 0) + r.get("stim", 0)
            g["mismatches"] += r["mismatches"]
            g["chunks"] += 1
            for key in ("ok", "timeout", "watchdog", "parity", "malformed", "cfg_invalid", "reconf_frames"):
                if key in r:
                    g[key] = g.get(key, 0) + r[key]
            if "max_cycles" in r:
                g["max_cycles"] = max(g.get("max_cycles", 0), r["max_cycles"])
        for g in agg.values():
            print(json.dumps(g))
            summary.append(g)
        write_result(out / f"cosim_d{d}.json", {"chunks": rs, "aggregate": list(agg.values())},
                     {**vars(a), "d": d, "graph": str(gp.relative_to(ROOT))}, a.seed,
                     extra_tools={"verilator": sh(["verilator", "--version"]).strip()})
    total_mm = sum(g["mismatches"] for g in summary)
    write_result(out / "summary.json", {"aggregate": summary, "total_mismatches": total_mm}, vars(a), a.seed,
                 extra_tools={"verilator": sh(["verilator", "--version"]).strip()})
    print("TOTAL MISMATCHES", total_mm)
    sys.exit(1 if total_mm else 0)


if __name__ == "__main__":
    main()
