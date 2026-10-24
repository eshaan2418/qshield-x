"""M6: adaptive decoder/hardware-configuration policy under noise shifts.

Action set per window of W shots:
  * HW QSX-UF with thresholds (q5) for an assumed noise point (p, meas_factor)  -> reconfiguration of the
    accelerator's threshold table (atomic cfg session, M3 property P5/P6); results are computed with the
    bit-exact golden model and latency with the cycle-exact HwModel (both validated against RTL in M2).
  * SW PyMatching with the DEM for the assumed noise point (CPU latency).
Online statistics (per window): detection-event density and the fraction of adjacent defect pairs joined by
a time-like edge. A calibration grid maps (density, time-like fraction) -> (p_hat, m_hat).
Strategies: fixed-UF, fixed-PM (nominal p=0.003, m=1), adaptive-UF (re-weights), adaptive-hybrid (re-weights;
routes to PM when p_hat >= p_switch or a burst is flagged), oracle-UF / oracle-PM (true noise each segment).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from functools import cache
from pathlib import Path

import numpy as np
import pymatching

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
import qsxdec  # noqa: E402

from bench.provenance import write_result  # noqa: E402
from bench.stats import clopper_pearson  # noqa: E402
from sim.qsx_graph import add_regional_burst, build, make_circuit  # noqa: E402

P_GRID = [round(x, 4) for x in np.arange(0.001, 0.0101, 0.0005)]
M_GRID = [1.0, 2.0, 3.0, 5.0, 8.0]
TMP = ROOT / "build" / "tmp" / "m6"


def snap(p: float, m: float) -> tuple[float, float]:
    return min(P_GRID, key=lambda x: abs(np.log(x / p))), min(M_GRID, key=lambda x: abs(np.log(x / m)))


class Configs:
    def __init__(self, d: int):
        self.d = d
        TMP.mkdir(parents=True, exist_ok=True)

    @cache
    def uf(self, p: float, m: float):
        _, g = build(self.d, p, weights="q5", meas_factor=m)
        path = TMP / f"d{self.d}_p{p}_m{m}.qsxg"
        g.write(str(path))
        return qsxdec.Decoder(str(path))

    @cache
    def pm(self, p: float, m: float):
        c = make_circuit(self.d, p, meas_factor=m)
        return pymatching.Matching.from_detector_error_model(c.detector_error_model(decompose_errors=True))


def edge_classes(d: int):
    c, g = build(d, 0.003)
    co = c.get_detector_coordinates()
    eu, ev, tl = [], [], []
    for u, v in zip(g.eu, g.ev):
        if v == g.V:
            continue
        eu.append(u)
        ev.append(v)
        tl.append(co[u][0] == co[v][0] and co[u][1] == co[v][1])
    return np.array(eu), np.array(ev), np.array(tl)


def features(x: np.ndarray, ec) -> tuple[float, float]:
    eu, ev, tl = ec
    pairs = x[:, eu] & x[:, ev]
    n_all = pairs.sum()
    n_tl = pairs[:, tl].sum()
    return float(x.mean()), float(n_tl / max(1, n_all))


def calibrate(d: int, ec, shots: int, seed: int):
    grid = []
    for i, p in enumerate(P_GRID):
        for j, m in enumerate(M_GRID):
            x = make_circuit(d, p, meas_factor=m).compile_detector_sampler(seed=seed + 100 * i + j).sample(shots)
            dens, tlf = features(x, ec)
            grid.append((p, m, dens, tlf))
    return grid


def estimate(grid, dens: float, tlf: float) -> tuple[float, float]:
    arr = np.array([(g[2], g[3]) for g in grid])
    sc = arr.std(0) + 1e-12
    dd = (((arr - np.array([dens, tlf])) / sc) ** 2).sum(1)
    k = np.argsort(dd)[:3]
    w = 1 / (dd[k] + 1e-9)
    p = float(np.exp((np.log([grid[i][0] for i in k]) * w).sum() / w.sum()))
    m = float(np.exp((np.log([grid[i][1] for i in k]) * w).sum() / w.sum()))
    return p, m


def scenario_stream(name: str, d: int, total: int, seg: int):
    """Yield (n_shots, circuit, truth dict) segments."""
    nseg = total // seg
    for s in range(nseg):
        frac = s / max(1, nseg - 1)
        if name == "drift":
            p, m, burst = 0.002 + 0.004 * frac, 1.0, False
        elif name == "step":
            p, m, burst = (0.002 if s < nseg // 2 else 0.005), 1.0, False
        elif name == "readout":
            p, m, burst = 0.003, (1.0 if s < nseg // 2 else 5.0), False
        elif name == "burst":
            p, m = 0.003, 1.0
            burst = nseg // 2 <= s < nseg // 2 + max(1, nseg // 20)
        else:
            raise ValueError(name)
        c = make_circuit(d, p, meas_factor=m)
        if burst:
            c = add_regional_burst(c, (d, d), 2.0, 0.03)
        yield seg, c, {"p": p, "m": m, "burst": burst, "segment": s}


def run(a) -> None:
    d = a.d
    cfg = Configs(d)
    ec = edge_classes(d)
    t0 = time.time()
    grid = calibrate(d, ec, a.calib_shots, a.seed)
    calib_s = time.time() - t0
    nominal = (0.003, 1.0)
    results = {}
    for scen in a.scenarios.split(","):
        rng_seed = a.seed + hash(scen) % 1000
        strategies = ["fixed-UF", "fixed-PM", "adaptive-UF", "adaptive-hybrid", "oracle-UF", "oracle-PM"]
        st = {k: {"errors": 0, "shots": 0, "uf_shots": 0, "pm_shots": 0, "hw_cycles": [], "reconfigs": 0,
                  "win_err": []} for k in strategies}
        state = {k: {"cfg": nominal, "mode": "uf"} for k in strategies}
        est_trace = []
        base_dens = None
        policy_ns = 0.0
        shift_seg = None
        prev_truth = None
        for si, (n, c, truth) in enumerate(scenario_stream(scen, d, a.shots, a.seg)):
            x, y = c.compile_detector_sampler(seed=rng_seed + si).sample(n, separate_observables=True)
            y = y[:, 0]
            if prev_truth is not None and (truth["p"], truth["m"], truth["burst"]) != prev_truth and shift_seg is None:
                shift_seg = si
            prev_truth = (truth["p"], truth["m"], truth["burst"])
            for w0 in range(0, n, a.window):
                xw, yw = x[w0:w0 + a.window], y[w0:w0 + a.window]
                xu = xw.astype(np.uint8)
                for k in strategies:
                    if k.startswith("oracle"):
                        cf, mode = snap(truth["p"], truth["m"]), ("uf" if k == "oracle-UF" else "pm")
                        if truth["burst"] and k == "oracle-PM":
                            mode = "pm-burst"
                    elif k == "fixed-UF":
                        cf, mode = nominal, "uf"
                    elif k == "fixed-PM":
                        cf, mode = nominal, "pm"
                    else:
                        cf, mode = state[k]["cfg"], state[k]["mode"]
                    if mode == "uf":
                        dec = cfg.uf(*cf)
                        if a.hw_cycles:
                            o, s_, cyc = dec.decode_batch_hw(xu, a.lanes)
                        else:
                            o, s_, cyc = (*dec.decode_batch(xu)[:2], None)
                        pred = (o & 1).astype(bool) & (s_ == 0)
                        st[k]["uf_shots"] += len(yw)
                        if cyc is not None:
                            st[k]["hw_cycles"].append(cyc)
                    else:
                        if mode == "pm-burst":
                            dem = c.detector_error_model(decompose_errors=True)
                            m_ = pymatching.Matching.from_detector_error_model(dem)
                        else:
                            m_ = cfg.pm(*cf)
                        pred = m_.decode_batch(xw)[:, 0].astype(bool)
                        st[k]["pm_shots"] += len(yw)
                    e = int((pred != yw).sum())
                    st[k]["errors"] += e
                    st[k]["shots"] += len(yw)
                    st[k]["win_err"].append((si, e, len(yw)))
                # ---- policy update (uses only syndrome statistics of this window)
                tp = time.perf_counter()
                dens, tlf = features(xw, ec)
                p_hat, m_hat = estimate(grid, dens, tlf)
                if base_dens is None:
                    base_dens = dens
                burst_flag = dens > a.burst_ratio * base_dens
                if not burst_flag:
                    base_dens = 0.9 * base_dens + 0.1 * dens
                new_cfg = snap(p_hat, m_hat)
                for k in ("adaptive-UF", "adaptive-hybrid"):
                    if new_cfg != state[k]["cfg"]:
                        state[k]["reconfigs"] = state[k].get("reconfigs", 0) + 1
                        st[k]["reconfigs"] += 1
                    state[k]["cfg"] = new_cfg
                state["adaptive-hybrid"]["mode"] = "pm" if (p_hat >= a.p_switch or burst_flag) else "uf"
                policy_ns += (time.perf_counter() - tp) * 1e9
                est_trace.append({"segment": si, "p_true": truth["p"], "m_true": truth["m"], "burst": truth["burst"],
                                  "p_hat": p_hat, "m_hat": m_hat, "burst_flag": bool(burst_flag),
                                  "hybrid_mode": state["adaptive-hybrid"]["mode"]})
        summ = {}
        for k, v in st.items():
            lo, hi = clopper_pearson(v["errors"], v["shots"])
            cyc = np.concatenate(v["hw_cycles"]) if v["hw_cycles"] else np.array([])
            summ[k] = {"errors": v["errors"], "shots": v["shots"], "pl": v["errors"] / v["shots"], "ci95": [lo, hi],
                       "uf_shots": v["uf_shots"], "pm_shots": v["pm_shots"], "reconfigs": v["reconfigs"],
                       "hw_cycles_mean": float(cyc.mean()) if len(cyc) else None,
                       "hw_cycles_p99": float(np.percentile(cyc, 99)) if len(cyc) else None,
                       "post_shift_pl": None}
            if shift_seg is not None:
                e = sum(x[1] for x in v["win_err"] if x[0] >= shift_seg)
                n_ = sum(x[2] for x in v["win_err"] if x[0] >= shift_seg)
                summ[k]["post_shift_pl"] = e / max(1, n_)
                summ[k]["post_shift_ci95"] = list(clopper_pearson(e, n_))
        # recovery: windows after the shift until the estimator snaps to the true grid point
        rec = None
        if shift_seg is not None and scen in ("step", "readout"):
            post = [t for t in est_trace if t["segment"] >= shift_seg]
            for i, t in enumerate(post):
                if snap(t["p_hat"], t["m_hat"]) == snap(t["p_true"], t["m_true"]):
                    rec = {"windows": i + 1, "shots": (i + 1) * a.window}
                    break
        results[scen] = {"strategies": summ, "shift_segment": shift_seg, "recovery": rec,
                         "policy_ns_per_shot": policy_ns / max(1, st["fixed-UF"]["shots"]),
                         "estimates": est_trace[:: max(1, len(est_trace) // 400)]}
        print(scen, json.dumps({k: (round(v["pl"], 5), v["reconfigs"]) for k, v in summ.items()}),
              "recovery", rec, flush=True)
    write_result(Path(a.out), {"calibration_s": calib_s, "grid": grid, "results": results}, vars(a), a.seed,
                 extra_tools={"pymatching": pymatching.__version__})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=int, default=5)
    ap.add_argument("--scenarios", default="step,readout,drift,burst")
    ap.add_argument("--shots", type=int, default=400_000)
    ap.add_argument("--seg", type=int, default=10_000)
    ap.add_argument("--window", type=int, default=2_000)
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--hw-cycles", type=int, default=1)
    ap.add_argument("--p-switch", type=float, default=0.0045)
    ap.add_argument("--burst-ratio", type=float, default=1.25)
    ap.add_argument("--calib-shots", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=66)
    ap.add_argument("--out", default=str(ROOT / "results/M6/adaptive_d5.json"))
    run(ap.parse_args())


if __name__ == "__main__":
    main()
