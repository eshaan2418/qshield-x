"""M9: data for the browser view (viz/). Per (d, p): detector coordinates, decoding-graph file, Stim shots with true
observables, and the best measured PnR Fmax for that distance (results/M2/report.json, if present) so the page can
show the RTL decoder's estimated latency (sim cycles / PnR Fmax) next to the in-browser Wasm decode time.
Output: viz/data/index.json, viz/data/d{d}_p{p}.json, viz/data/d{d}_p{p}.qsxg
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.qsx_graph import build  # noqa: E402

OUT = ROOT / "viz" / "data"


def best_fmax() -> dict:
    rep = ROOT / "results/M2/report.json"
    if not rep.exists():
        return {}
    out: dict = {}
    for r in json.loads(rep.read_text())["data"]["configs"]:
        if "pnr" in r and r["weights"] == "q5":
            k = str(r["d"])
            if k not in out or r["pnr"]["fmax_mhz"] > out[k]["fmax_mhz"]:
                out[k] = {"fmax_mhz": r["pnr"]["fmax_mhz"], "lanes": r["lanes"], "pipe": r["pipe"], "tag": r["tag"],
                          "stage": "pnr (nextpnr-ecp5, LFE5U-85F)"}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distances", default="3,5,7")
    ap.add_argument("--ps", default="0.001,0.003,0.006")
    ap.add_argument("--shots", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=9009)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fm = best_fmax()
    index = {"sets": [], "fmax": fm}
    for d in map(int, a.distances.split(",")):
        for p in map(float, a.ps.split(",")):
            c, g = build(d, p, weights="q5")
            name = f"d{d}_p{p:g}"
            g.write(str(OUT / f"{name}.qsxg"))
            coords = c.get_detector_coordinates()
            dets, obs = c.compile_detector_sampler(seed=a.seed + d).sample(a.shots, separate_observables=True,
                                                                            bit_packed=True)
            doc = {"d": d, "p": p, "rounds": d, "V": c.num_detectors, "shots": a.shots,
                   "coords": [coords[i] for i in range(c.num_detectors)],
                   "dets_b64": base64.b64encode(dets.tobytes()).decode(),
                   "obs_b64": base64.b64encode(obs.tobytes()).decode(), "row_bytes": int(dets.shape[1]),
                   "graph": f"{name}.qsxg", "noise": "Stim rotated_memory_z, uniform circuit-level depolarizing"}
            (OUT / f"{name}.json").write_text(json.dumps(doc))
            index["sets"].append({"name": name, "d": d, "p": p})
            print(name, c.num_detectors, "detectors")
    (OUT / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()
