"""M7 diagnostic (DECISIONS D9): why the batch-512 FedAvg+DP results do not depend on sigma.

Re-runs the original batch-512 DP configuration (40 rounds x 100 local steps, Adam lr 2e-3, clip 1, 3 sites) for two
noise multipliers with independent noise streams and records, every 10 rounds: per-site test P_L, the number of
positive predictions, the per-site base rate (P_L of the always-0 predictor), and a fingerprint of the global
parameters. Also measures the per-coordinate signal-to-noise ratio of one DP step.
Output: results/M7/dp_debug.json
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from torch.func import functional_call, grad, vmap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from federated.fed import SITES, SecAgg, evaluate, flat, load_flat, local_train, site_data  # noqa: E402
from learned.gnn import GNN, graph_tensors  # noqa: E402


def snr(model, X, Y, batch, sigma, clip, gen) -> dict:
    """Per-coordinate |mean clipped gradient| vs noise std for one DP lot of size `batch`."""
    lossf = torch.nn.BCEWithLogitsLoss()
    params = {k: v.detach() for k, v in model.named_parameters()}
    bufs = dict(model.named_buffers())
    loss1 = lambda p, x, y: lossf(functional_call(model, (p, bufs), (x[None],)), y[None])  # noqa: E731
    per = vmap(grad(loss1), in_dims=(None, 0, 0))
    idx = torch.randint(0, len(X), (batch,), generator=gen)
    g = per(params, X[idx], Y[idx])
    norms = torch.sqrt(sum((gi.flatten(1) ** 2).sum(1) for gi in g.values()))
    scale = torch.clamp(clip / (norms + 1e-12), max=1.0)
    s = torch.cat([(g[k] * scale.view(-1, *[1] * (g[k].dim() - 1))).sum(0).flatten() for k in g]) / batch
    return {"batch": batch, "sigma": sigma, "median_abs_signal": float(s.abs().median()),
            "noise_std": sigma * clip / batch, "median_grad_norm": float(norms.median()),
            "fraction_clipped": float((norms > clip).float().mean())}


def main() -> None:
    seed = 77
    torch.manual_seed(seed)
    A, st, V = graph_tensors(3)
    names = list(SITES)
    train = {n: site_data(3, *SITES[n], 200_000, seed + 10 * i) for i, n in enumerate(names)}
    tests = {n: site_data(3, *SITES[n], 50_000, seed + 10 * i + 5) for i, n in enumerate(names)}
    base = {n: float(tests[n][1].mean()) for n in names}
    m0 = GNN(A, st, 32, 4)
    out = {"base_rate": base, "trajectories": [], "snr": []}
    for batch in (512, 8192):
        for sigma in (0.6, 2.0):
            out["snr"].append(snr(m0, *train["site-B"], batch, sigma, 1.0, torch.Generator().manual_seed(3)))
    for sigma in (0.6, 2.0):
        glob = copy.deepcopy(m0)
        agg = SecAgg(names)
        g = torch.Generator().manual_seed(1000 + int(sigma * 10))
        for r in range(40):
            g0 = flat(glob)
            masked = []
            for n in names:
                lm = copy.deepcopy(glob)
                local_train(lm, *train[n], 100, 512, 2e-3,
                            {"sigma": sigma, "clip": 1.0, "q": 512 / 200_000, "expected_batch": 512}, g)
                masked.append(agg.mask(n, (flat(lm) - g0) / len(names), r))
            load_flat(glob, g0 + agg.unmask_sum(masked))
            if r % 10 == 9:
                ev = evaluate(glob, tests)
                with torch.no_grad():
                    pos = {n: int((glob(tests[n][0]) > 0).sum()) for n in names}
                row = {"sigma": sigma, "round": r + 1, "pl": {k: v["pl"] for k, v in ev.items()},
                       "positive_predictions": pos,
                       "param_sha256": hashlib.sha256(flat(glob).tobytes()).hexdigest()[:16]}
                out["trajectories"].append(row)
                print(json.dumps(row), flush=True)
    write_result(ROOT / "results/M7/dp_debug.json", out, {"seed": seed, "config": "batch 512, 40x100, Adam 2e-3"}, seed,
                 extra_tools={"torch": torch.__version__, "numpy": np.__version__})


if __name__ == "__main__":
    main()
