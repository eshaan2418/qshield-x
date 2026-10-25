"""M2: where the clock period goes. Extracts nextpnr-ecp5's final critical-path report for every placed-and-routed
configuration in results/M2/fpga/fpga_*.json (logs in build/fpga/<tag>/nextpnr.log) and classifies the
start/end points by RTL block. Output: results/M2/fpga/critical_paths.json (stage: pnr).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402

BLOCKS = [(r"u_lmin", "vertex min-label tree"), (r"g_edge\[", "edge fabric (support/grown)"),
          (r"g_vert\[", "vertex fabric"), (r"u_in\b|u_in\.", "ingress FIFO"), (r"u_cfg", "config"),
          (r"u_core\.", "core control/scans"), (r"u_top\.", "shell")]


def block(name: str) -> str:
    for pat, lab in BLOCKS:
        if re.search(pat, name):
            return lab
    return "other"


def main() -> None:
    fp = [r for f in sorted((ROOT / "results/M2/fpga").glob("fpga_*.json")) for r in json.loads(f.read_text())["data"]]
    rows = []
    for r in fp:
        log = ROOT / "build/fpga" / r["tag"] / "nextpnr.log"
        if "pnr" not in r or not log.exists():
            continue
        text = log.read_text().splitlines()
        starts = [i for i, ln in enumerate(text) if "Critical path report for clock" in ln]
        if not starts:
            continue
        seg = []
        for ln in text[starts[-1] + 1:]:
            if not ln.startswith("Info:") or "Critical path report" in ln:
                break
            seg.append(ln)
        nodes = [re.search(r"(?:Source|Sink) (\S+)", ln).group(1) for ln in seg if re.search(r"(?:Source|Sink) ", ln)]
        logic = [float(m.group(1)) for ln in seg if (m := re.match(r"Info:\s+logic\s+([\d.]+)", ln))]
        route = [float(m.group(1)) for ln in seg if (m := re.match(r"Info:\s+routing\s+([\d.]+)", ln))]
        rows.append({"tag": r["tag"], "fmax_mhz": r["pnr"]["fmax_mhz"], "start": nodes[0] if nodes else None,
                     "end": nodes[-1] if nodes else None, "start_block": block(nodes[0]) if nodes else None,
                     "end_block": block(nodes[-1]) if nodes else None, "logic_ns": sum(logic),
                     "routing_ns": sum(route), "levels": len(logic), "stage": "pnr (nextpnr-ecp5 timing report)"})
        print(f"{r['tag']:24s} {r['pnr']['fmax_mhz']:6.1f} MHz  {rows[-1]['start_block']} -> {rows[-1]['end_block']}"
              f"  logic {sum(logic):.1f} ns routing {sum(route):.1f} ns")
    write_result(ROOT / "results/M2/fpga/critical_paths.json", rows, {"source": "build/fpga/*/nextpnr.log"}, None)


if __name__ == "__main__":
    main()
