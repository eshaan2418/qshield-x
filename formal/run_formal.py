"""M3: run every formal job and write results/M3/formal_summary.json (proofs/bounds table).

Jobs: SymbiYosys (ingress k-induction; qsx_top with abstract core k-induction; qsx_top with real core BMC +
cover; real core k-induction + cover), TLC (main model at two bounds, mutations, pre-fix model), Z3 step
equivalence of the real core (d=3, d=5) + mutation sanity check.
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

OUT = ROOT / "results" / "M3"


def run(cmd: list[str], cwd: Path, log: Path, timeout: int) -> tuple[int, str, float]:
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out, rc = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), -9
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(out)
    return rc, out, time.time() - t0


def sby_job(sby: str, task: str, timeout: int) -> dict:
    cwd = ROOT / "formal" / "sva"
    rc, out, dt = run(["sby", "-f", sby, task], cwd, OUT / "sby" / f"{Path(sby).stem}_{task}.log", timeout)
    status = re.findall(r"DONE \((\w+), rc=", out)
    fails = re.findall(r"failed assertion (\S+) at (\S+)", out)
    cfg = (cwd / sby).read_text()
    depth = re.search(rf"{task}: depth (\d+)", cfg) or re.search(r"depth (\d+)", cfg)
    mode = re.search(rf"{task}: mode (\w+)", cfg) or re.search(r"mode (\w+)", cfg)
    return {"tool": "SymbiYosys/smtbmc-bitwuzla", "job": f"{sby}:{task}", "mode": mode.group(1) if mode else None,
            "depth": int(depth.group(1)) if depth else None, "status": status[-1] if status else f"rc={rc}",
            "failed": fails, "seconds": round(dt, 1)}


def tlc_job(cfg: str, timeout: int, n: int | None = None, k: int | None = None) -> dict:
    cwd = ROOT / "formal" / "tla"
    c = (cwd / cfg).read_text()
    if n is not None:
        c = re.sub(r"N = \d+", f"N = {n}", c)
        c = re.sub(r"K = \d+", f"K = {k}", c)
        cfg = cfg.replace(".cfg", f"_N{n}K{k}.cfg")
        (ROOT / "build" / "tlc").mkdir(parents=True, exist_ok=True)
        (cwd / cfg).write_text(c)
    rc, out, dt = run(["java", "-XX:+UseParallelGC", "-cp", str(ROOT / ".tools/tla2tools.jar"), "tlc2.TLC", "-workers",
                       "8", "-deadlock", "-metadir", str(ROOT / "build/tlc" / cfg), "-config", cfg, "QSXProtocol.tla"],
                      cwd, OUT / "tla" / f"{cfg}.log", timeout)
    states = re.findall(r"(\d+) distinct states found", out.replace(",", ""))
    depth = re.findall(r"depth of the complete state graph search is (\d+)", out)
    viol = re.findall(r"Error: (Invariant \w+ is violated|Temporal properties were violated)", out)
    return {"tool": "TLC 2.19", "job": cfg, "constants": c.splitlines()[0], "ok": "No error has been found" in out,
            "violations": viol, "distinct_states": int(states[-1]) if states else None,
            "depth": int(depth[-1]) if depth else None, "seconds": round(dt, 1)}


def z3_job(d: int, timeout: int, mutate: bool = False) -> dict:
    g = ROOT / "build" / "graphs" / f"d{d}_q5.qsxg"
    inc = ROOT / "build" / "rtl" / f"d{d}_q5"
    smt = ROOT / "build" / "z3" / f"core_d{d}.smt2"
    smt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "sim/qsx_graph.py", "--d", str(d), "--p", "0.001", "--weights", "q5",
                    "--out", str(g)],
                   cwd=ROOT, check=True, capture_output=True)
    subprocess.run([sys.executable, "rtl/gen_graph.py", "--graph", str(g), "--out", str(inc)], cwd=ROOT, check=True,
                   capture_output=True)
    subprocess.run(["yosys", "-q", "-p", f"read_verilog -sv -formal -I{inc} rtl/qsx_min_tree.sv rtl/qsx_uf_core.sv; "
                    "chparam -set LANES 8 qsx_uf_core; prep -top qsx_uf_core; flatten; opt_clean; async2sync; "
                    f"dffunmap; write_smt2 -wires {smt}"], cwd=ROOT, check=True)
    js = OUT / "z3" / f"core_d{d}{'_mutant' if mutate else ''}.json"
    js.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "formal/z3/check_core_steps.py", "--graph", str(g), "--smt2", str(smt), "--json", str(js)]
    if mutate:
        cmd += ["--steps", "peh", "--mutate"]
    rc, out, dt = run(cmd, ROOT, OUT / "z3" / f"core_d{d}{'_mutant' if mutate else ''}.log", timeout)
    res = json.loads(js.read_text()) if js.exists() else []
    return {"tool": "Z3 (z3-solver 5.1.0)", "job": f"core_d{d}_step_equivalence" + ("_mutant" if mutate else ""),
            "steps": res, "ok": rc == 0, "seconds": round(dt, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=6 * 3600)
    ap.add_argument("--z3-d", default="3,5")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    jobs = [
        lambda: sby_job("ingress.sby", "prove_w2_n4", a.timeout),
        lambda: sby_job("ingress.sby", "prove_w4_n2", a.timeout),
        lambda: sby_job("top.sby", "stub_prove", a.timeout),
        lambda: sby_job("top.sby", "real_bmc", a.timeout),
        lambda: sby_job("top.sby", "real_cover", a.timeout),
        lambda: sby_job("core.sby", "prove", a.timeout),
        lambda: sby_job("core.sby", "cover", a.timeout),
        lambda: tlc_job("MC_main.cfg", a.timeout),
        lambda: tlc_job("MC_main.cfg", a.timeout, 5, 3),
        lambda: tlc_job("MC_mut_stale.cfg", a.timeout),
        lambda: tlc_job("MC_mut_status.cfg", a.timeout),
        lambda: tlc_job("MC_v0_nobypass.cfg", a.timeout),
    ]
    jobs += [lambda d=d: z3_job(int(d), a.timeout) for d in a.z3_d.split(",")]
    jobs += [lambda: z3_job(3, a.timeout, mutate=True)]
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda f: f(), jobs))
    for r in res:
        print(json.dumps({k: r[k] for k in r if k not in ("steps",)}))
    write_result(OUT / "formal_summary.json", res, vars(a), None,
                 extra_tools={"sby": "OSS CAD Suite 2026-10-24", "tlc": "2.19"})


if __name__ == "__main__":
    main()
