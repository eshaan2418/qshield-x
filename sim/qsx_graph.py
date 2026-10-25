"""Build the canonical QSX decoding graph from a Stim circuit (see DECISIONS.md D1, D2).

Graph text format (``.qsxg``)::

    qsxg 1
    V <num_detectors> E <num_edges> O <num_observables>
    meta <free text, single line>
    <u> <v> <thr> <obs_mask> <prob>      # E lines, v == V means boundary

Edges are sorted lexicographically by (u, v) with the boundary encoded as V.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass, field

import numpy as np
import stim


def make_circuit(d: int, p: float, rounds: int | None = None, basis: str = "z",
                 meas_factor: float = 1.0) -> stim.Circuit:
    """Uniform circuit-level depolarizing noise (DECISIONS D2); meas_factor scales the measurement
    flip probability only (readout-degradation scenario, M6)."""
    return stim.Circuit.generated(
        f"surface_code:rotated_memory_{basis}",
        distance=d,
        rounds=d if rounds is None else rounds,
        after_clifford_depolarization=p,
        before_round_data_depolarization=p,
        before_measure_flip_probability=min(0.5, p * meas_factor),
        after_reset_flip_probability=p,
    )


def add_regional_burst(c: stim.Circuit, center: tuple[float, float], radius: float, p_burst: float) -> stim.Circuit:
    """Correlated-burst scenario (M6): after every DEPOLARIZE1 layer, apply extra DEPOLARIZE1(p_burst) to the
    qubits within `radius` of `center` (lattice coordinates). Models a localised high-error event."""
    coords = c.get_final_qubit_coordinates()
    region = {q for q, xy in coords.items() if (xy[0] - center[0]) ** 2 + (xy[1] - center[1]) ** 2 <= radius ** 2}
    out = stim.Circuit()
    for inst in c.flattened():
        out.append(inst)
        if inst.name == "DEPOLARIZE1":
            tg = [t.value for t in inst.targets_copy() if t.value in region]
            if tg:
                out.append("DEPOLARIZE1", tg, p_burst)
    return out


@dataclass
class Graph:
    V: int
    O: int
    eu: list[int] = field(default_factory=list)
    ev: list[int] = field(default_factory=list)
    thr: list[int] = field(default_factory=list)
    obs: list[int] = field(default_factory=list)
    prob: list[float] = field(default_factory=list)
    meta: str = ""

    @property
    def E(self) -> int:
        return len(self.eu)

    def write(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write("qsxg 1\n")
            f.write(f"V {self.V} E {self.E} O {self.O}\n")
            f.write(f"meta {self.meta}\n")
            for u, v, t, o, p in zip(self.eu, self.ev, self.thr, self.obs, self.prob):
                f.write(f"{u} {v} {t} {o} {p:.9e}\n")

    @staticmethod
    def read(path: str) -> Graph:
        with open(path) as f:
            assert f.readline().split() == ["qsxg", "1"]
            hdr = f.readline().split()
            V, E, O = int(hdr[1]), int(hdr[3]), int(hdr[5])
            meta = f.readline()[5:].rstrip("\n")
            g = Graph(V=V, O=O, meta=meta)
            for _ in range(E):
                u, v, t, o, p = f.readline().split()
                g.eu.append(int(u))
                g.ev.append(int(v))
                g.thr.append(int(t))
                g.obs.append(int(o))
                g.prob.append(float(p))
        return g


def quantize_thresholds(probs: list[float], mode: str) -> list[int]:
    """mode 'unweighted' -> all 2; 'q<K>[m<M>]' -> thr = clamp(round(K * w / median(w)), 1, M),
    w = ln((1-p)/p), M defaults to 7 (3-bit counters); M <= 15."""
    if mode == "unweighted":
        return [2] * len(probs)
    if not mode.startswith("q"):
        raise ValueError(mode)
    body = mode[1:]
    tmax = 7
    if "m" in body:
        body, m = body.split("m")
        tmax = int(m)
    assert 1 <= tmax <= 15
    k = float(body)
    w = np.array([math.log((1 - p) / p) for p in probs])
    med = float(np.median(w))
    return [int(min(tmax, max(1, round(k * wi / med)))) for wi in w]


def graph_from_dem(dem: stim.DetectorErrorModel, weights: str = "unweighted", meta: str = "") -> Graph:
    V = dem.num_detectors
    O = dem.num_observables
    assert O <= 64
    edges: dict[tuple[int, int], tuple[float, int]] = {}
    conflicts = 0
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        p = inst.args_copy()[0]
        if p <= 0:
            continue
        # Split on separators into graphlike components.
        comps: list[tuple[list[int], int]] = [([], 0)]
        for t in inst.targets_copy():
            if t.is_separator():
                comps.append(([], 0))
            elif t.is_relative_detector_id():
                comps[-1][0].append(t.val)
            elif t.is_logical_observable_id():
                dets, m = comps[-1]
                comps[-1] = (dets, m ^ (1 << t.val))
        for dets, m in comps:
            if len(dets) == 0:
                continue
            if len(dets) > 2:
                raise ValueError("non-graphlike component after decomposition")
            key = (min(dets), max(dets)) if len(dets) == 2 else (dets[0], V)
            if key in edges:
                p0, m0 = edges[key]
                if m0 != m:
                    conflicts += 1
                    # keep the observable mask of the more probable mechanism
                    m = m0 if p0 >= p else m
                edges[key] = (p0 * (1 - p) + p * (1 - p0), m)
            else:
                edges[key] = (p, m)
    g = Graph(V=V, O=O, meta=meta + f" weights={weights} obs_conflicts={conflicts}")
    for (u, v) in sorted(edges):
        p, m = edges[(u, v)]
        g.eu.append(u)
        g.ev.append(v)
        g.obs.append(m)
        g.prob.append(min(p, 0.5 - 1e-12))
    g.thr = quantize_thresholds(g.prob, weights)
    return g


def build(d: int, p: float, weights: str = "unweighted", rounds: int | None = None,
          meas_factor: float = 1.0) -> tuple[stim.Circuit, Graph]:
    c = make_circuit(d, p, rounds, meas_factor=meas_factor)
    dem = c.detector_error_model(decompose_errors=True)
    meta = f"rotated_memory_z d={d} rounds={rounds or d} p={p} meas_factor={meas_factor}"
    g = graph_from_dem(dem, weights, meta=meta)
    return c, g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=int, required=True)
    ap.add_argument("--p", type=float, default=1e-3)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--weights", default="unweighted")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    _, g = build(a.d, a.p, a.weights, a.rounds)
    g.write(a.out)
    deg = np.bincount(np.array(g.eu + [v for v in g.ev if v < g.V]), minlength=g.V)
    print(f"{a.out}: V={g.V} E={g.E} O={g.O} max_deg={deg.max()} boundary_edges={sum(v == g.V for v in g.ev)}")


if __name__ == "__main__":
    main()
