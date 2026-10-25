"""M7: privacy-preserving federated training of the GNN decoder (simulation of collaborative research).

Sites hold syndrome data from devices with different noise (non-IID). Compared regimes:
  local-only, centralized (pooled data), FedAvg, FedAvg + DP-SGD (per-example clipping + Gaussian noise,
  epsilon from Opacus' RDP accountant, delta = 1e-5), each with simulated secure aggregation:
  pairwise masks (X25519 key agreement -> HKDF-SHA256 -> AES-256-CTR keystream, all from `cryptography`)
  added to fixed-point (2^-16, mod 2^32) model updates; the server only sees masked updates whose sum
  equals the sum of the true updates. An IID split (same total data, homogeneous noise per site) measures the
  effect of heterogeneity.
This is a simulation: all parties run in one process; no network.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from opacus.accountants import RDPAccountant
from torch.func import functional_call, grad, vmap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from bench.stats import clopper_pearson  # noqa: E402
from learned.gnn import GNN, graph_tensors  # noqa: E402
from sim.qsx_graph import make_circuit  # noqa: E402

SITES = {  # name: (p, meas_factor)
    "site-A": (0.002, 1.0),
    "site-B": (0.005, 1.0),
    "site-C": (0.003, 5.0),
}
SCALE = 1 << 16


# ------------------------------------------------------------------ secure aggregation (simulation)
class SecAgg:
    def __init__(self, names: list[str]):
        self.names = names
        self.keys = {n: X25519PrivateKey.generate() for n in names}
        self.pub = {n: self.keys[n].public_key() for n in names}
        raw = self.pub[names[0]].public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.pub_bytes = len(raw)
        self.shared = {}
        for i in names:
            for j in names:
                if i < j:
                    s = self.keys[i].exchange(self.pub[j])
                    assert s == self.keys[j].exchange(self.pub[i])
                    self.shared[(i, j)] = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                                               info=b"qsx-secagg").derive(s)

    @staticmethod
    def _stream(key: bytes, rnd: int, n: int) -> np.ndarray:
        nonce = rnd.to_bytes(16, "little")
        ks = Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor().update(b"\0" * (4 * n))
        return np.frombuffer(ks, dtype=np.uint32)

    def mask(self, name: str, vec: np.ndarray, rnd: int) -> np.ndarray:
        q = np.round(vec * SCALE).astype(np.int64).astype(np.uint32)
        for (i, j), key in self.shared.items():
            if name not in (i, j):
                continue
            m = self._stream(key, rnd, len(vec))
            q = q + m if name == i else q - m  # uint32 wraparound arithmetic
        return q

    @staticmethod
    def unmask_sum(masked: list[np.ndarray]) -> np.ndarray:
        s = np.zeros_like(masked[0])
        for m in masked:
            s = s + m
        return s.astype(np.int32).astype(np.float64) / SCALE


def flat(model: nn.Module) -> np.ndarray:
    return torch.cat([p.detach().flatten() for p in model.parameters()]).double().numpy()


def load_flat(model: nn.Module, v: np.ndarray) -> None:
    i = 0
    with torch.no_grad():
        for p in model.parameters():
            n = p.numel()
            p.copy_(torch.tensor(v[i:i + n], dtype=p.dtype).view_as(p))
            i += n


# ------------------------------------------------------------------ training
def site_data(d: int, p: float, m: float, n: int, seed: int):
    x, y = make_circuit(d, p, meas_factor=m).compile_detector_sampler(seed=seed).sample(n, separate_observables=True)
    return torch.tensor(x.astype(np.float32)), torch.tensor(y[:, 0].astype(np.float32))


def local_train(model, X, Y, steps, batch, lr, dp: dict | None, gen):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.BCEWithLogitsLoss()
    params = {k: v for k, v in model.named_parameters()}
    buffers = {k: v for k, v in model.named_buffers()}

    def loss_one(prm, x, y):
        out = functional_call(model, (prm, buffers), (x[None],))
        return lossf(out, y[None])

    per_ex = vmap(grad(loss_one), in_dims=(None, 0, 0))
    for _ in range(steps):
        if dp:  # Poisson sampling as assumed by the RDP accountant
            idx = torch.nonzero(torch.rand(len(X), generator=gen) < dp["q"]).flatten()
            if len(idx) == 0:
                continue
        else:
            idx = torch.randint(0, len(X), (batch,), generator=gen)
        x, y = X[idx], Y[idx]
        if dp:
            g = per_ex({k: v.detach() for k, v in params.items()}, x, y)
            norms = torch.sqrt(sum((gi.flatten(1) ** 2).sum(1) for gi in g.values()))
            scale = torch.clamp(dp["clip"] / (norms + 1e-12), max=1.0)
            for k, p in params.items():
                s = (g[k] * scale.view(-1, *[1] * (g[k].dim() - 1))).sum(0)
                s = s + torch.randn(s.shape, generator=gen) * dp["sigma"] * dp["clip"]
                p.grad = s / dp["expected_batch"]
        else:
            opt.zero_grad()
            lossf(model(x), y).backward()
        opt.step()
    return model


def evaluate(model, tests: dict) -> dict:
    out = {}
    model.eval()
    with torch.no_grad():
        for name, (X, Y) in tests.items():
            pred = torch.cat([model(X[i:i + 8192]) for i in range(0, len(X), 8192)]) > 0
            e = int((pred != Y.bool()).sum())
            out[name] = {"errors": e, "shots": len(Y), "pl": e / len(Y), "ci95": clopper_pearson(e, len(Y))}
    model.train()
    return out


def run(a) -> None:
    torch.manual_seed(a.seed)
    gen = torch.Generator().manual_seed(a.seed)
    A, st, V = graph_tensors(a.d)
    names = list(SITES)
    train = {}
    tests = {}
    for i, n in enumerate(names):
        p, m = SITES[n]
        train[n] = site_data(a.d, p, m, a.n_site, a.seed + 10 * i)
        tests[n] = site_data(a.d, p, m, a.n_test, a.seed + 10 * i + 5)
    # IID split: every site gets an equal share of the pooled distribution
    Xall = torch.cat([train[n][0] for n in names])
    Yall = torch.cat([train[n][1] for n in names])
    perm = torch.randperm(len(Xall), generator=gen)
    iid = {n: (Xall[perm[i::len(names)]], Yall[perm[i::len(names)]]) for i, n in enumerate(names)}
    # PyMatching reference on each site's test set (decoder with the site's true noise model)
    import pymatching

    ref = {}
    for n in names:
        p, m = SITES[n]
        c = make_circuit(a.d, p, meas_factor=m)
        mt = pymatching.Matching.from_detector_error_model(c.detector_error_model(decompose_errors=True))
        X, Y = tests[n]
        pred = mt.decode_batch(X.numpy().astype(np.uint8))[:, 0]
        e = int((pred != Y.numpy()).sum())
        ref[n] = {"errors": e, "shots": len(Y), "pl": e / len(Y)}
    new = lambda: GNN(A, st, a.hidden, a.layers)  # noqa: E731
    results = {"pymatching_reference": ref}
    total_steps = a.rounds * a.local_steps

    if not a.only_dp:
        # local only
        loc = {}
        for n in names:
            m = local_train(new(), *train[n], total_steps, a.batch, a.lr, None, gen)
            loc[n] = evaluate(m, {n: tests[n]})[n]
        results["local-only"] = loc
        # centralized
        m = local_train(new(), Xall, Yall, total_steps, a.batch, a.lr, None, gen)
        results["centralized"] = evaluate(m, tests)

    def fedavg(split: dict, dp: dict | None, tag: str):
        rounds = a.dp_rounds if dp else a.rounds
        lsteps = a.dp_local_steps if dp else a.local_steps
        batch = dp["expected_batch"] if dp else a.batch
        lr = a.dp_lr if dp else a.lr
        glob = new()
        agg = SecAgg(names)
        nparam = len(flat(glob))
        bytes_up = 0
        t0 = time.time()
        for r in range(rounds):
            masked = []
            g0 = flat(glob)
            for n in names:
                loc_m = copy.deepcopy(glob)
                local_train(loc_m, *split[n], lsteps, batch, lr, dp, gen)
                delta = (flat(loc_m) - g0) * (1.0 / len(names))  # equal weights (equal site sizes)
                masked.append(agg.mask(n, delta, r))
                bytes_up += masked[-1].nbytes
            s = agg.unmask_sum(masked)
            load_flat(glob, g0 + s)
        ev = evaluate(glob, tests)
        info = {"eval": ev, "rounds": rounds, "local_steps": lsteps, "batch": batch, "lr": lr, "params": nparam,
                "bytes_up_per_site_per_round": nparam * 4, "bytes_up_total": bytes_up,
                "keyexchange_bytes_per_site": agg.pub_bytes * (len(names) - 1), "wall_s": time.time() - t0}
        if dp:
            eps = float("inf")
            if dp["sigma"] > 0:  # sigma = 0: clipping-only ablation, no privacy guarantee
                acc = RDPAccountant()
                acc.history = [(dp["sigma"], dp["q"], rounds * lsteps)]
                eps = acc.get_epsilon(delta=a.delta)
            info["dp"] = {"sigma": dp["sigma"], "clip": dp["clip"], "q": dp["q"], "steps": rounds * lsteps,
                          "delta": a.delta, "epsilon": eps, "accountant": "opacus RDP"}
        results[tag] = info
        print(tag, json.dumps({k: round(v["pl"], 5) for k, v in ev.items()}), info.get("dp", {}).get("epsilon"),
              flush=True)

    # secure-aggregation correctness check: masked sum == plain sum (fixed-point)
    agg = SecAgg(names)
    vs = [np.random.default_rng(i).normal(size=1000) * 0.01 for i in range(len(names))]
    ms = [agg.mask(n, v, 0) for n, v in zip(names, vs)]
    results["secagg_check"] = {"max_abs_err": float(np.abs(agg.unmask_sum(ms) - sum(vs)).max()),
                               "quantum": 1 / SCALE,
                               "masked_corr_with_plain": float(np.corrcoef(ms[0].astype(np.float64), vs[0])[0, 1])}
    if not a.only_dp:
        fedavg(train, None, "fedavg")
        fedavg(iid, None, "fedavg-iid")
    for sigma in [float(s) for s in a.sigmas.split(",")]:
        dp = {"sigma": sigma, "clip": a.clip, "q": a.dp_batch / a.n_site, "expected_batch": a.dp_batch}
        fedavg(train, dp, f"fedavg-dp-sigma{sigma}")
    write_result(Path(a.out), results, vars(a), a.seed, extra_tools={"torch": torch.__version__,
                                                                     "opacus": __import__("opacus").__version__})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=int, default=3)
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--n-site", type=int, default=200_000)
    ap.add_argument("--n-test", type=int, default=200_000)
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--local-steps", type=int, default=50)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--clip", type=float, default=1.0)
    ap.add_argument("--sigmas", default="0.6,1.0,2.0")
    ap.add_argument("--delta", type=float, default=1e-5)
    ap.add_argument("--seed", type=int, default=77)
    # DP-SGD needs large batches for a usable signal-to-noise ratio (DECISIONS D9); defaults = original config
    ap.add_argument("--dp-batch", type=int, default=512)
    ap.add_argument("--dp-rounds", type=int, default=None)
    ap.add_argument("--dp-local-steps", type=int, default=None)
    ap.add_argument("--dp-lr", type=float, default=None)
    ap.add_argument("--only-dp", action="store_true", help="run only the FedAvg+DP regimes (ablations)")
    ap.add_argument("--out", default=str(ROOT / "results/M7/federated_d3.json"))
    a = ap.parse_args()
    a.dp_rounds = a.dp_rounds or a.rounds
    a.dp_local_steps = a.dp_local_steps or a.local_steps
    a.dp_lr = a.dp_lr or a.lr
    run(a)


if __name__ == "__main__":
    main()
