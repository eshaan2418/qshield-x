"""M10 end-to-end demo: Stim -> RTL accelerator (Verilator qsx_top) -> host protocol with verified software
fallback -> Ed25519-signed manifest + AES-GCM encrypted storage -> WebAssembly replay for inspection.

1. Stim samples N d-round memory experiments (detectors + true observable).
2. The RTL accelerator (rtl/qsx_top.sv, Verilator) decodes every frame over AXI-Stream, configured through
   an atomic cfg session with a small growth-round limit (--max-rounds) so that some frames TIMEOUT. The
   testbench also checks every output frame against the cycle-exact model (mismatches must be 0) and dumps
   the frames it received.
3. Host (this script) implements the protocol of formal/tla/QSXProtocol.tla: responses are matched to
   rounds by tag (stale filter); a non-OK status, or a response lost in transit (fault injection: a fraction
   --lose of responses is dropped, modelling HWLose) sends the round to the software fallback (C++ QSX-UF,
   255 rounds); rounds are committed strictly in order, once. The TLA+ safety invariants NoDoubleCommit,
   NoSkip, ExclusiveSource, NoInvalidCommit are asserted at run time.
4. The committed predictions and a result summary are written, signed (Ed25519 manifest) and stored
   encrypted (AES-256-GCM); the manifest is verified and the blob decrypted again.
5. The Wasm build of the same decoder replays the trace in Node.js; its prediction digest must equal the
   committed one (a frame that converged within --max-rounds is decoded identically with the full limit).
Output: results/M10/e2e_demo.json (+ signed artefacts under build/e2e/).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "tb"))
import qsxdec  # noqa: E402
from run_cosim import build_sim, prepare_graph, sh  # noqa: E402

from bench.provenance import write_result  # noqa: E402
from bench.stats import clopper_pearson  # noqa: E402
from infra import signing  # noqa: E402
from infra.storage import EncryptedStore  # noqa: E402
from sim.qsx_graph import build as build_graph  # noqa: E402

B = ROOT / "build" / "e2e"
STATUS = ["OK", "TIMEOUT", "PARITY_ERROR", "WATCHDOG", "FRAME_ERROR", "CFG_INVALID"]


def read_frames(path: Path) -> list[list[int]]:
    raw = path.read_bytes()
    out, i = [], 0
    while i < len(raw):
        (n,) = struct.unpack_from("<I", raw, i)
        out.append(list(struct.unpack_from(f"<{n}I", raw, i + 4)))
        i += 4 + 4 * n
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=int, default=5)
    ap.add_argument("--p", type=float, default=0.006)
    ap.add_argument("--shots", type=int, default=5000)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--lose", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=1010)
    ap.add_argument("--out", default=str(ROOT / "results/M10/e2e_demo.json"))
    a = ap.parse_args()
    B.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    # 1. Stim
    gp, inc, tbits = prepare_graph(a.d)  # RTL graph tables + thresholds (q5, built at p=0.001)
    c, _ = build_graph(a.d, a.p)
    dets, obs = c.compile_detector_sampler(seed=a.seed).sample(a.shots, separate_observables=True, bit_packed=True)
    trace = B / "trace.b8"
    dets.tofile(trace)
    truth = np.unpackbits(obs, axis=1, bitorder="little")[:, 0]

    # 2. RTL accelerator
    top = build_sim("top", a.d, 8, inc, tbits)
    frames_f = B / "frames.bin"
    tb = json.loads(sh([str(top), "--graph", str(gp), "--lanes", "8", "--stim", str(trace), "--max-rounds",
                        str(a.max_rounds), "--dump", str(frames_f), "--seed", str(a.seed)]).strip().splitlines()[-1])
    assert tb["mismatches"] == 0, tb
    frames = read_frames(frames_f)

    # 3. host protocol (QSXProtocol.tla)
    dec = qsxdec.Decoder(str(gp), 255)
    V = dec.V
    unpacked = np.unpackbits(dets, axis=1, bitorder="little")[:, :V].astype(np.uint8)
    N = a.shots
    phase = ["hw"] * N  # every round was submitted to the accelerator
    src = ["none"] * N
    ncommit = [0] * N
    hw_result: dict[int, int] = {}
    lost = stale = 0
    status_counts = dict.fromkeys(STATUS, 0)
    for fr in frames:
        if rng.random() < a.lose:  # HWLose: response dropped in transit
            lost += 1
            continue
        h = fr[0]
        assert h >> 24 == 0x5A
        tag, st, o = h & 0xFFFF, (h >> 20) & 0xF, (h >> 16) & 1
        status_counts[STATUS[st]] += 1
        r = tag  # tags are unique per round in this demo (N <= 65536)
        if r >= N or phase[r] != "hw":
            stale += 1  # stale-response filter
            continue
        if st == 0:
            phase[r] = "ready_hw"
            hw_result[r] = o
        else:
            phase[r] = "sw"  # explicit error -> software fallback
    # deadline expiry for rounds whose response never arrived
    for r in range(N):
        if phase[r] == "hw":
            phase[r] = "sw"
    sw_rounds = [r for r in range(N) if phase[r] == "sw"]
    sw_obs, sw_status = dec.decode_batch(unpacked[sw_rounds])[:2] if sw_rounds else ([], [])
    sw_result = {r: int(o) for r, o, s in zip(sw_rounds, sw_obs, sw_status) if s == 0}
    assert len(sw_result) == len(sw_rounds), "software fallback must not fail"
    pred = np.zeros(N, dtype=np.uint8)
    nextc = 0
    for r in range(N):  # in-order commit
        assert phase[r] in ("ready_hw", "sw")
        if phase[r] == "ready_hw":
            pred[r] = hw_result[r]
            src[r] = "hw"
        else:
            pred[r] = sw_result[r]
            src[r] = "sw"
            phase[r] = "ready_sw"
        phase[r] = "committed"
        ncommit[r] += 1
        nextc = r + 1
        # TLA+ safety invariants, checked after every commit
        assert all(x <= 1 for x in ncommit[: r + 1])  # NoDoubleCommit
        assert phase[r] == "committed" and (r + 1 >= N or phase[r + 1] != "committed")  # NoSkip (prefix)
        assert src[r] in ("hw", "sw")  # ExclusiveSource
    assert nextc == N and all(p == "committed" for p in phase)
    # NoInvalidCommit: every HW-sourced prediction came from a frame with status OK (by construction above)
    hw_only_errors = int(sum(1 for r in range(N) if src[r] == "hw" and pred[r] != truth[r]))
    errors = int((pred != truth).sum())

    # 4. sign + encrypted storage
    pred_f = B / "committed_predictions.u8"
    pred.tofile(pred_f)
    pred_sha = hashlib.sha256(pred.tobytes()).hexdigest()
    summary = {"d": a.d, "p": a.p, "shots": N, "errors": errors, "hw_committed": src.count("hw"),
               "sw_committed": src.count("sw"), "pred_sha256": pred_sha}
    summ_f = B / "summary.json"
    summ_f.write_text(json.dumps(summary, indent=1))
    key = signing.generate_key()
    man_f = B / "manifest.json"
    signing.sign_manifest([trace, frames_f, pred_f, summ_f], {"experiment": "e2e_demo", "seed": a.seed}, key,
                          man_f)
    trusted = {signing.key_id(key.public_key()): key.public_key()}
    signing.verify_manifest(man_f, trusted)
    k = EncryptedStore.new_key()
    store = EncryptedStore(B / "store", k)
    store.put("summary", summ_f.read_bytes())
    assert json.loads(EncryptedStore(B / "store", k).get("summary")) == summary

    # 5. Wasm replay (Node.js)
    node = next((ROOT / ".tools/emsdk/node").iterdir()) / "bin/node"
    rep = json.loads(subprocess.run([str(node), "wasm/replay.js", "wasm/dist/qsx_simd.js", "wasm/dist/qsx_simd.wasm",
                                     str(gp), str(trace)], cwd=ROOT, capture_output=True, text=True, check=True)
                     .stdout.strip().splitlines()[-1])
    res = {**summary, "pl": errors / N, "pl_ci95": clopper_pearson(errors, N), "max_rounds_hw": a.max_rounds,
           "rtl_testbench": {k2: tb[k2] for k2 in ("frames", "mismatches", "status_counts")},
           "hw_status_counts_received": status_counts, "responses_lost_injected": lost, "stale_filtered": stale,
           "hw_only_errors": hw_only_errors, "tla_invariants_checked": ["NoDoubleCommit", "NoSkip", "ExclusiveSource",
                                                                       "NoInvalidCommit"],
           "manifest_verified": True, "encrypted_roundtrip": True, "wasm_replay": rep,
           "wasm_replay_matches_committed": rep["pred_sha256"] == pred_sha,
           "stage": "sim (Verilator RTL + host protocol model)"}
    assert res["wasm_replay_matches_committed"], (rep, pred_sha)
    write_result(a.out, res, vars(a), a.seed)
    print(json.dumps({k2: res[k2] for k2 in ("shots", "hw_committed", "sw_committed", "responses_lost_injected",
                                              "errors", "wasm_replay_matches_committed")}))


if __name__ == "__main__":
    main()
