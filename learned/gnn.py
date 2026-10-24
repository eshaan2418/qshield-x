"""M6: small graph-neural-network decoder (PyTorch), trained on Stim samples.

Architecture (deliberately small; cf. Lange et al., "Data-driven decoding of quantum error correcting
codes using graph neural networks", 2023): nodes = all detectors of the d-round memory experiment,
node features = [defect, x, y, t (normalised), has-boundary-edge]; edges = non-boundary edges of the
QSX decoding graph (symmetric-normalised adjacency with self loops); L residual message-passing
layers; readout = [mean, max, defect-weighted sum] -> MLP -> logit for the single logical observable.

Usage: python learned/gnn.py train --d 5 --out results/M6/gnn_d5   (then `eval`)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build  # noqa: E402


def graph_tensors(d: int, p: float = 0.003):
    c, g = build(d, p)
    coords = c.get_detector_coordinates()
    xyz = np.array([coords[i][:3] for i in range(g.V)], dtype=np.float32)
    xyz = (xyz - xyz.mean(0)) / (xyz.std(0) + 1e-6)
    hasb = np.zeros(g.V, np.float32)
    A = np.eye(g.V, dtype=np.float32)
    for u, v in zip(g.eu, g.ev):
        if v == g.V:
            hasb[u] = 1
        else:
            A[u, v] = A[v, u] = 1
    dinv = 1 / np.sqrt(A.sum(1))
    A = A * dinv[:, None] * dinv[None, :]
    static = np.concatenate([xyz, hasb[:, None]], 1)
    return torch.tensor(A), torch.tensor(static), g.V


class GNN(nn.Module):
    def __init__(self, A: torch.Tensor, static: torch.Tensor, hidden: int = 64, layers: int = 6):
        super().__init__()
        self.register_buffer("A", A)
        self.register_buffer("static", static)
        self.inp = nn.Linear(1 + static.shape[1], hidden)
        self.msg = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(layers)])
        self.self_ = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(layers)])
        self.norm = nn.ModuleList([nn.LayerNorm(hidden) for _ in range(layers)])
        self.head = nn.Sequential(nn.Linear(3 * hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, det: torch.Tensor) -> torch.Tensor:  # det: [B, V] float
        B = det.shape[0]
        x = torch.cat([det[..., None], self.static.expand(B, -1, -1)], -1)
        h = torch.relu(self.inp(x))
        for m, s, n in zip(self.msg, self.self_, self.norm):
            agg = torch.einsum("uv,bvh->buh", self.A, m(h))
            h = h + torch.relu(n(agg + s(h)))
        w = det[..., None]
        ro = torch.cat([h.mean(1), h.max(1).values, (h * w).sum(1) / (w.sum(1) + 1)], -1)
        return self.head(ro).squeeze(-1)


def sampler(d: int, ps: list[float], seed: int):
    sams = [build(d, p)[0].compile_detector_sampler(seed=seed + i) for i, p in enumerate(ps)]

    def draw(n: int):
        k = n // len(sams)
        xs, ys = [], []
        for s in sams:
            x, y = s.sample(k, separate_observables=True)
            xs.append(x)
            ys.append(y[:, 0])
        return np.concatenate(xs).astype(np.float32), np.concatenate(ys).astype(np.float32)

    return draw


def train(a) -> None:
    torch.manual_seed(a.seed)
    A, st, V = graph_tensors(a.d)
    model = GNN(A, st, a.hidden, a.layers)
    dev = torch.device(a.device)
    model.to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, a.steps)
    draw = sampler(a.d, [float(p) for p in a.train_ps.split(",")], a.seed)
    lossf = nn.BCEWithLogitsLoss()
    log = []
    t0 = time.time()
    for step in range(1, a.steps + 1):
        x, y = draw(a.batch)
        x, y = torch.tensor(x, device=dev), torch.tensor(y, device=dev)
        loss = lossf(model(x), y)
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if step % 200 == 0:
            log.append({"step": step, "loss": float(loss), "elapsed_s": time.time() - t0})
            print(log[-1], flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "model.pt")
    write_result(out / "train.json", {"log": log, "params": sum(p.numel() for p in model.parameters()),
                                      "samples_seen": a.steps * a.batch}, vars(a), a.seed,
                 extra_tools={"torch": torch.__version__})


def evaluate(a) -> None:
    import pymatching

    sys.path.insert(0, str(ROOT / "build"))
    import qsxdec

    from bench.stats import clopper_pearson

    A, st, V = graph_tensors(a.d)
    model = GNN(A, st, a.hidden, a.layers)
    model.load_state_dict(torch.load(Path(a.out) / "model.pt"))
    model.eval()
    rows = []
    for i, p in enumerate(float(x) for x in a.eval_ps.split(",")):
        c, g = build(a.d, p, weights="q5")
        gp = ROOT / "build" / "tmp" / f"m6_d{a.d}_{p}.qsxg"
        gp.parent.mkdir(parents=True, exist_ok=True)
        g.write(str(gp))
        x, y = c.compile_detector_sampler(seed=a.seed + 100 + i).sample(a.eval_shots, separate_observables=True)
        y = y[:, 0]
        with torch.no_grad():
            logits = torch.cat([model(torch.tensor(x[j:j + 4096].astype(np.float32)))
                                for j in range(0, len(x), 4096)])
        pg = (logits > 0).numpy()
        m = pymatching.Matching.from_detector_error_model(c.detector_error_model(decompose_errors=True))
        pm = m.decode_batch(x)[:, 0].astype(bool)
        uf = qsxdec.Decoder(str(gp)).decode_batch(x.astype(np.uint8))[0].astype(bool) & True
        row = {"d": a.d, "p": p, "shots": int(len(y))}
        for k, pred in (("gnn", pg), ("pymatching", pm), ("qsxuf-q5", uf)):
            e = int((pred != y.astype(bool)).sum())
            row[k] = {"errors": e, "pl": e / len(y), "ci95": clopper_pearson(e, len(y))}
        # latency: single-shot CPU inference (batch 1) and batched throughput
        xb = torch.tensor(x[:1].astype(np.float32))
        with torch.no_grad():
            for _ in range(20):
                model(xb)
            ts = []
            for j in range(300):
                t0 = time.perf_counter()
                model(torch.tensor(x[j:j + 1].astype(np.float32)))
                ts.append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            model(torch.tensor(x[:4096].astype(np.float32)))
            tb = (time.perf_counter() - t0) / 4096
        ts.sort()
        row["gnn_latency_batch1_us"] = {"p50": 1e6 * ts[150], "p99": 1e6 * ts[296]}
        row["gnn_batched_us_per_shot"] = 1e6 * tb
        rows.append(row)
        print(json.dumps(row), flush=True)
    write_result(Path(a.out) / "eval.json", rows, vars(a), a.seed,
                 extra_tools={"torch": torch.__version__, "torch_threads": torch.get_num_threads()})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "eval"])
    ap.add_argument("--d", type=int, default=5)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=6)
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--train-ps", default="0.002,0.003,0.004,0.005,0.006")
    ap.add_argument("--eval-ps", default="0.002,0.003,0.005")
    ap.add_argument("--eval-shots", type=int, default=200_000)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    train(a) if a.cmd == "train" else evaluate(a)


if __name__ == "__main__":
    main()
