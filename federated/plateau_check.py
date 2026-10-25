"""M7 diagnostic (DECISIONS D10): P_L of weight-truncated MWPM on the exact fed.py test sets.

pred = PyMatching(syndrome) if Hamming weight <= k else 0, for k = 1..4, per site. Locates the DP plateau (the
decoder DP-limited training converges to) between "learns weight <= k syndromes" levels.
Output: results/M7/plateau_check.json
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pymatching

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from federated.fed import SITES, site_data  # noqa: E402
from sim.qsx_graph import make_circuit  # noqa: E402


def main() -> None:
    seed, n = 77, 200_000  # fed.py defaults: test set i uses seed + 10*i + 5
    out = {}
    for i, (name, (p, m)) in enumerate(SITES.items()):
        X, Y = site_data(3, p, m, n, seed + 10 * i + 5)
        X, Y = X.numpy().astype(np.uint8), Y.numpy().astype(np.uint8)
        mt = pymatching.Matching.from_detector_error_model(
            make_circuit(3, p, meas_factor=m).detector_error_model(decompose_errors=True))
        pm = mt.decode_batch(X)[:, 0]
        w = X.sum(1)
        out[name] = {"pymatching": float(np.mean(pm != Y)), "base_rate": float(Y.mean()),
                     "truncated": {str(k): float(np.mean(np.where(w <= k, pm, 0) != Y)) for k in (1, 2, 3, 4)},
                     "weight_hist": {str(k): int((w == k).sum()) for k in range(0, 9)}}
        print(name, out[name]["pymatching"], out[name]["truncated"])
    write_result(ROOT / "results/M7/plateau_check.json", out, {"seed": seed, "n_test": n}, seed)


if __name__ == "__main__":
    main()
