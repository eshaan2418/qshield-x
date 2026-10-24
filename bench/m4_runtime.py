"""M4: native vs Wasm-scalar vs Wasm-SIMD runtime study (identical decoder source, identical shots).

Runtimes: native clang -O3 (no auto-vectorisation / NEON), Node.js (V8), d8 built from source (default tiering,
--liftoff-only, --no-liftoff), headless Chrome (COOP/COEP isolated). Bit-exactness: FNV-1a hash over all
statuses, observables and correction edge lists must be identical across all runs.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from sim.qsx_graph import build  # noqa: E402

D8 = ROOT / "v8/src/v8/out/rel/d8"
NODE = None


class Iso(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(" ".join(map(str, cmd)) + "\n" + r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5,7")
    ap.add_argument("--p", type=float, default=0.003)
    ap.add_argument("--shots", type=int, default=100_000)
    ap.add_argument("--seed", type=int, default=44)
    ap.add_argument("--chrome", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "results/M4/runtime.json"))
    a = ap.parse_args()
    data = ROOT / "build" / "m4"
    data.mkdir(parents=True, exist_ok=True)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Iso, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    rows = []
    for d in map(int, a.distances.split(",")):
        c, g = build(d, a.p, weights="q5")
        gp, dp, op = data / f"rt_d{d}.qsxg", data / f"rt_d{d}.b8", data / f"rt_d{d}_obs.b8"
        g.write(str(gp))
        x, y = c.compile_detector_sampler(seed=a.seed + d).sample(a.shots, separate_observables=True, bit_packed=True)
        x.tofile(dp)
        y.tofile(op)
        runs = []
        for exe, v, lab in [("qsx_native_novec", 0, "native-novec-naive"), ("qsx_native_novec", 1, "native-novec-word"),
                            ("qsx_native_simd", 1, "native-O3-word"), ("qsx_native_simd", 2, "native-O3-neon")]:
            runs.append(sh([ROOT / "build" / exe, "--graph", gp, "--dets", dp, "--obs", op, "--variant", str(v),
                            "--label", lab]))
        node = str(ROOT / ".tools/emsdk/node") + "/" + next((ROOT / ".tools/emsdk/node").iterdir()).name + "/bin/node"
        for var in ("scalar", "simd"):
            r = sh([node, "wasm/harness.js", f"wasm/dist/qsx_{var}.js", f"wasm/dist/qsx_{var}.wasm", gp, dp, op,
                    f"node-{var}", "2" if var == "simd" else "1"])
            runs.append(r)
            if D8.exists():
                for flags, tag in [([], "default"), (["--liftoff", "--no-wasm-tier-up"], "liftoff-only"),
                                   (["--no-liftoff"], "turbofan-only")]:
                    r = sh([D8, *flags, "wasm/harness.js", "--", f"wasm/dist/qsx_{var}.js", f"wasm/dist/qsx_{var}.wasm",
                            gp, dp, op, f"d8-{var}-{tag}", "2" if var == "simd" else "1"])
                    r["d8_flags"] = flags
                    runs.append(r)
            if a.chrome:
                for jf, tag in [("", "default"), ("--liftoff --no-wasm-tier-up", "liftoff-only")]:
                    rel = lambda p: "/" + str(Path(p).relative_to(ROOT))  # noqa: E731
                    r = sh(["node", "bench/m4_chrome.mjs", str(port), var, rel(gp), rel(dp), rel(op), jf]
                           if False else [node, "bench/m4_chrome.mjs", str(port), var, rel(gp), rel(dp), rel(op), jf])
                    r["label"] = f"chrome-{var}-{tag}"
                    runs.append(r)
        hashes = {r["label"]: r["hash"] for r in runs}
        for r in runs:
            r["d"] = d
            print(f"d={d} {r['label']:28s} hash={r['hash']} steady={r['steady_ns_per_shot']:9.1f} ns/shot "
                  f"compile={r.get('compile_ms', 0):6.2f} ms", flush=True)
        rows.append({"d": d, "runs": runs, "bit_exact": len(set(hashes.values())) == 1})
    srv.shutdown()
    v8rev = (ROOT / "build/v8_rev.txt").read_text().strip() if (ROOT / "build/v8_rev.txt").exists() else None
    write_result(a.out, rows, vars(a), a.seed, extra_tools={
        "emcc": subprocess.run([str(ROOT / ".tools/emsdk/upstream/emscripten/emcc"), "--version"], capture_output=True,
                               text=True).stdout.splitlines()[0], "v8_rev": v8rev,
        "chrome": subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
                                 capture_output=True, text=True).stdout.strip()})
    print("bit-exact:", [r["bit_exact"] for r in rows])


if __name__ == "__main__":
    main()
