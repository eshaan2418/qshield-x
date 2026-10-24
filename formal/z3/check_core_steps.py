"""Z3 bounded-equivalence check: one clock step of the *real* RTL core (exported by Yosys as an SMT-LIB
transition relation) equals a reference function built independently from the .qsxg graph file
(DECISIONS.md D1), for ALL register/input values (not just reachable ones).

Checked steps (state encodings from rtl/qsx_uf_core.sv):
  LABEL (1): label' = min(label[v], label[w] for grown non-boundary edges (v,w)); next state PAR iff no change
  GROW  (5): support'[e] = min(thr[e], support[e] + active[u] + active[v])        (active[B] = 0)
  DIST  (7): dst'[v] = min(dst[v], dst[w]+1 for grown edges, INF absorbing)
  PEH   (8): peh'[v] = one-hot lowest edge-index grown slot with dst[w] == dst[v]-1, gated by
             dst[v] not in {0, INF} and no grown boundary edge; peh_b'[v] = bgrown[v] and dst[v] != 0
Run:  python formal/z3/check_core_steps.py --graph G.qsxg --smt2 core.smt2 [--steps label,grow,dist,peh]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import z3

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sim.qsx_graph import Graph  # noqa: E402


def clog2(x: int) -> int:
    return max(1, math.ceil(math.log2(x))) if x > 1 else 1


def bv(n: int, w: int) -> str:
    return f"(_ bv{n} {w})"


def ext(expr: str, lo: int, w: int) -> str:
    return f"((_ extract {lo + w - 1} {lo}) {expr})"


def smin(a: str, b: str) -> str:
    return f"(ite (bvult {a} {b}) {a} {b})"


def build_query(g: Graph, smt: str, step: str, tb: int, mutate: bool = False) -> str:
    V = g.V
    vb, db = clog2(V + 1), clog2(V + 2)
    n = lambda name, s: f"(|qsx_uf_core_n {name}| {s})"  # noqa: E731
    lab = lambda v, s: ext(n("label", s), v * vb, vb)  # noqa: E731
    dst = lambda v, s: ext(n("dst", s), v * db, db)  # noqa: E731
    sup = lambda e, s: ext(n("support", s), e * tb, tb)  # noqa: E731
    thr = lambda e: ext(n("thr_in", "s0"), e * tb, tb)  # noqa: E731
    act = lambda v: ext(n("active", "s0"), v, 1)  # noqa: E731
    grown = lambda e: f"(= {sup(e, 's0')} {thr(e)})"  # noqa: E731
    inc = {v: [] for v in range(V)}
    bedge = {}
    for e, (u, w) in enumerate(zip(g.eu, g.ev)):
        if w == V:
            bedge[u] = e
        else:
            inc[u].append((e, w))
            inc[w].append((e, u))
    state_code = {"label": 1, "grow": 5, "dist": 7, "peh": 8}[step]
    pre = [
        "(declare-fun s0 () |qsx_uf_core_s|)",
        "(declare-fun s1 () |qsx_uf_core_s|)",
        "(assert (|qsx_uf_core_t| s0 s1))",
        f"(assert {n('rst_n', 's0')})",
        f"(assert (= {n('cycle_budget', 's0')} {bv(0, 20)}))",  # watchdog off
        f"(assert (= {n('state', 's0')} {bv(state_code, 4)}))",
    ]
    goals = []
    INF = bv((1 << db) - 1, db)
    if step == "label":
        same = []
        for v in range(V):
            r = lab(v, "s0")
            for e, w in inc[v]:
                r = smin(r, f"(ite {grown(e)} {lab(w, 's0')} {bv((1 << vb) - 1, vb)})")
            goals.append(f"(= {lab(v, 's1')} {r})")
            same.append(f"(= {r} {lab(v, 's0')})")
        nxt = f"(ite (and {' '.join(same)}) {bv(2, 4)} {bv(1, 4)})"
        goals.append(f"(= {n('state', 's1')} {nxt})")
    elif step == "grow":
        for e, (u, w) in enumerate(zip(g.eu, g.ev)):
            s = f"(concat #b0 {sup(e, 's0')})"
            a = f"(concat {bv(0, tb)} {act(u)})"
            b = f"(concat {bv(0, tb)} {act(w)})" if w < V else bv(0, tb + 1)
            tot = f"(bvadd {s} (bvadd {a} {b}))"
            t = f"(concat #b0 {thr(e)})"
            goals.append(f"(= {sup(e, 's1')} (ite (bvuge {tot} {t}) {thr(e)} ((_ extract {tb - 1} 0) {tot})))")
    elif step == "dist":
        for v in range(V):
            r = dst(v, "s0")
            for e, w in inc[v]:
                dw = dst(w, "s0")
                r = smin(r, f"(ite (and {grown(e)} (not (= {dw} {INF}))) (bvadd {dw} {bv(1, db)}) {INF})")
            goals.append(f"(= {dst(v, 's1')} {r})")
    elif step == "peh":
        md = max(len(inc[v]) for v in range(V))
        for v in range(V):
            dv = dst(v, "s0")
            bg = grown(bedge[v]) if v in bedge else "false"
            ok = f"(and (not (= {dv} {bv(0, db)})) (not (= {dv} {INF})) (not {bg}))"
            # reference: slots in increasing edge index; one-hot of the first satisfying slot
            onehot = bv(0, md)
            for k in (range(len(inc[v])) if mutate else reversed(range(len(inc[v])))):
                e, w = inc[v][k]
                cond = f"(and {ok} {grown(e)} (= {dst(w, 's0')} (bvsub {dv} {bv(1, db)})))"
                onehot = f"(ite {cond} {bv(1 << k, md)} {onehot})"
            goals.append(f"(= {ext(n('peh', 's1'), v * md, md)} {onehot})")
            goals.append(f"(= {ext(n('peh_b', 's1'), v, 1)} (ite (and {bg} (not (= {dv} {bv(0, db)}))) #b1 #b0))")
    q = smt + "\n" + "\n".join(pre) + f"\n(assert (not (and {' '.join(goals)})))\n"
    return q


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--smt2", required=True)
    ap.add_argument("--steps", default="label,grow,dist,peh")
    ap.add_argument("--tb", type=int, default=3)
    ap.add_argument("--json", default=None)
    ap.add_argument("--mutate", action="store_true", help="PEH reference picks the highest index (must be sat)")
    a = ap.parse_args()
    g = Graph.read(a.graph)
    smt = Path(a.smt2).read_text()
    out = []
    for st in a.steps.split(","):
        t0 = time.time()
        s = z3.Solver()
        s.add(z3.parse_smt2_string(build_query(g, smt, st, a.tb, a.mutate)))
        r = s.check()
        res = {"step": st, "result": str(r), "equivalent": r == z3.unsat, "seconds": round(time.time() - t0, 2),
               "V": g.V, "E": g.E}
        print(json.dumps(res))
        out.append(res)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    ok = all(r["equivalent"] for r in out)
    sys.exit(0 if ok != a.mutate else 1)


if __name__ == "__main__":
    main()
