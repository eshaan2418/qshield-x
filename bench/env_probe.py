"""Host facts used in the paper: CPU, cores, RAM, OS, load average, timer resolution (results/ENV/host.json).

Timer resolution = smallest non-zero difference of consecutive time.perf_counter_ns() reads (on macOS this is
mach_absolute_time, the same timebase as std::chrono::steady_clock used by the C++ latency harnesses).
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402


def main() -> None:
    best = None
    for _ in range(200_000):
        a = time.perf_counter_ns()
        b = time.perf_counter_ns()
        while b == a:
            b = time.perf_counter_ns()
        best = b - a if best is None else min(best, b - a)
    mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout or 0)
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    data = {"cpu": cpu or platform.processor(), "ncpu": os.cpu_count(), "ram_gb": mem / 2**30,
            "os": f"{platform.system()} {platform.release()}", "loadavg": os.getloadavg(),
            "timer_resolution_ns": best}
    write_result(ROOT / "results/ENV/host.json", data, {}, None)
    print(data)


if __name__ == "__main__":
    main()
