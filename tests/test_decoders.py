"""Python-level tests: graph extraction invariants, binding == CLI, HwModel == fast decoder."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
import qsxdec  # noqa: E402

from sim.qsx_graph import Graph, add_regional_burst, build, quantize_thresholds  # noqa: E402


@pytest.mark.parametrize("d", [3, 5])
def test_graph_canonical(tmp_path, d):
    c, g = build(d, 0.003, weights="q5")
    assert g.V == c.num_detectors and g.O == 1
    keys = list(zip(g.eu, g.ev))
    assert keys == sorted(set(keys)), "edges must be sorted and unique"
    assert all(0 <= u < v <= g.V for u, v in keys)
    assert all(1 <= t <= 7 for t in g.thr)
    assert "obs_conflicts=0" in g.meta
    g.write(str(tmp_path / "g.qsxg"))
    h = Graph.read(str(tmp_path / "g.qsxg"))
    assert h.eu == g.eu and h.thr == g.thr and h.obs == g.obs


def test_quantize_modes():
    probs = [1e-3, 2e-3, 5e-3]
    assert quantize_thresholds(probs, "unweighted") == [2, 2, 2]
    q = quantize_thresholds(probs, "q5")
    assert q[0] >= q[1] >= q[2] and all(1 <= x <= 7 for x in q)


def test_binding_matches_cli_and_hwmodel(tmp_path):
    c, g = build(5, 0.004, weights="q5")
    g.write(str(tmp_path / "g.qsxg"))
    x, y = c.compile_detector_sampler(seed=3).sample(3000, separate_observables=True)
    dec = qsxdec.Decoder(str(tmp_path / "g.qsxg"))
    obs, st, rounds, _ = dec.decode_batch(x.astype(np.uint8))
    hobs, hst, cyc = dec.decode_batch_hw(x.astype(np.uint8), 8)
    assert (obs == hobs).all() and (st == hst).all() and (cyc > 0).all()
    packed = np.packbits(x, axis=1, bitorder="little")
    packed.tofile(tmp_path / "d.b8")
    np.packbits(y, axis=1, bitorder="little").tofile(tmp_path / "o.b8")
    out = subprocess.run([str(ROOT / "build/qsx_decode"), "--graph", str(tmp_path / "g.qsxg"), "--dets",
                          str(tmp_path / "d.b8"), "--obs", str(tmp_path / "o.b8"), "--out", str(tmp_path / "p.b8")],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    pred = np.fromfile(tmp_path / "p.b8", dtype=np.uint8)
    assert (pred == (obs & 0xff)).all()
    assert r["errors"] == int(((obs & 1) != y[:, 0]).sum())


def test_burst_circuit_increases_detection_rate():
    c, _ = build(5, 0.003)
    b = add_regional_burst(c, (5, 5), 2.0, 0.03)
    base = c.compile_detector_sampler(seed=1).sample(4000).mean()
    hot = b.compile_detector_sampler(seed=1).sample(4000).mean()
    assert hot > 1.2 * base
