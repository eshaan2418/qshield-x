"""Provenance stamping for every result file (Non-negotiable rule 1)."""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=ROOT).stdout.strip()
    except Exception:
        return "unavailable"


@lru_cache(maxsize=1)
def tool_versions() -> dict:
    v: dict[str, str] = {}
    try:
        import stim

        v["stim"] = stim.__version__
    except Exception:
        pass
    try:
        import pymatching

        v["pymatching"] = pymatching.__version__
    except Exception:
        pass
    try:
        import numpy

        v["numpy"] = numpy.__version__
    except Exception:
        pass
    v["python"] = platform.python_version()
    v["cxx"] = _run(["clang++", "--version"]).splitlines()[0] if _run(["clang++", "--version"]) else "unavailable"
    return v


def git_state() -> dict:
    commit = _run(["git", "rev-parse", "HEAD"])
    dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"])
    return {"commit": commit or "uncommitted", "dirty": bool(dirty)}


def provenance(config: dict, seed: int | None, extra_tools: dict | None = None) -> dict:
    tv = dict(tool_versions())
    if extra_tools:
        tv.update(extra_tools)
    return {
        "git": git_state(),
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "host": {"machine": platform.machine(), "system": platform.system(), "release": platform.release(),
                 "cpu": _run(["sysctl", "-n", "machdep.cpu.brand_string"]), "ncpu": os.cpu_count()},
        "tools": tv,
        "seed": seed,
        "config": config,
    }


def write_result(path: str | Path, data, config: dict, seed: int | None, extra_tools: dict | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"provenance": provenance(config, seed, extra_tools), "data": data}
    path.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    return path
