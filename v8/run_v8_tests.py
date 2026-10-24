"""M5 evidence: V8 test results and codegen check for v8/patches/0001-*.patch.

  * applies cleanly to the recorded upstream revision (git apply --check in a scratch worktree)
  * run-tests.py suites on the patched build: arm64 instruction-selector/scheduler unittests, Wasm SIMD
    execution unittests, mjsunit/wasm/*, mjsunit/regress/wasm/*
  * the new mjsunit test on the unpatched (build/v8_base/d8) and patched d8, in 4 tiering configurations
  * codegen of the real QSX-UF Wasm SIMD module: number of v128.any_true reductions followed by cmp/cset
  * --mutation: rebuild d8 with a deliberately broken lowering (32-bit move of the reduction), require the new
    mjsunit test to FAIL, restore and rebuild (guards against a vacuous test)
Output: results/M5/v8_tests.json
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402

V8 = ROOT / "v8/src/v8"
ENV = {**os.environ, "PATH": f"{ROOT / 'v8/depot_tools'}:{os.environ['PATH']}"}
BASE_D8 = ROOT / "build/v8_base/d8"
NEW_TEST = "test/mjsunit/wasm/simd-any-true-branch.js"
CG = "src/compiler/backend/arm64/code-generator-arm64.cc"


def sh(cmd, cwd=V8, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(" ".join(map(str, cmd)) + "\n" + r.stdout[-2000:] + r.stderr[-2000:])
    return r


def suite(patterns: list[str]) -> dict:
    r = sh([sys.executable, "tools/run-tests.py", "--outdir=out/rel", "--progress=mono", "-j", "10", *patterns],
           check=False)
    out = r.stdout + r.stderr
    ran = re.findall(r">>> (\d+) tests ran", out)
    failed = re.findall(r">>> (\d+) tests failed", out)
    return {"patterns": patterns, "ran": int(ran[-1]) if ran else 0, "failed": int(failed[-1]) if failed else 0,
            "rc": r.returncode}


def new_test(d8: Path) -> dict:
    res = {}
    for flags in ([], ["--no-liftoff"], ["--liftoff-only"], ["--no-wasm-tier-up"]):
        r = sh([str(d8), "--allow-natives-syntax", *flags, "test/mjsunit/mjsunit.js", NEW_TEST], check=False)
        res[" ".join(flags) or "default"] = "PASS" if r.returncode == 0 else "FAIL"
    return res


def codegen(d8: Path) -> dict:
    r = sh([str(d8), "--no-liftoff", "--print-wasm-code", "wasm/harness.js", "--", "wasm/dist/qsx_simd.js",
            "wasm/dist/qsx_simd.wasm", "build/m4/rt_d3.qsxg", "build/m4/rt_d3.b8", "-", "codegen", "2"], cwd=ROOT)
    lines = r.stdout.splitlines()
    sites = [i for i, ln in enumerate(lines) if "umaxp" in ln]
    mat = sum(any("cset" in x for x in lines[i + 1:i + 4]) for i in sites)
    fused = sum(any(re.search(r"\bcbn?z\s+x", x) for x in lines[i + 1:i + 3]) for i in sites)
    return {"any_true_sites": len(sites), "materialized_cmp_cset": mat, "fused_cbz_cbnz": fused,
            "excerpt": [ln.split(None, 3)[-1] for i in sites[:1] for ln in lines[i:i + 3]]}


def build_d8():
    sh(["autoninja", "-C", "out/rel", "d8"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutation", action="store_true")
    ap.add_argument("--skip-suites", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results/M5/v8_tests.json"))
    a = ap.parse_args()
    base = (ROOT / "build/v8_rev.txt").read_text().split()[0]
    patch = sorted((ROOT / "v8/patches").glob("0001-*.patch"))[0]
    res: dict = {"upstream_rev": base, "patch": str(patch.relative_to(ROOT)),
                 "branch_head": sh(["git", "rev-parse", "HEAD"]).stdout.strip()}
    wt = ROOT / "build/v8_apply_check"
    if not wt.exists():
        sh(["git", "worktree", "add", "--detach", "--no-checkout", str(wt), base])
    sh(["git", "read-tree", base], cwd=wt)
    files = re.findall(r"^diff --git a/(\S+)", patch.read_text(), re.M)
    sh(["git", "checkout-index", "-f", "--", *[f for f in files if f != NEW_TEST]], cwd=wt)
    chk = sh(["git", "apply", "--check", str(patch)], cwd=wt, check=False)
    res["applies_cleanly_to_upstream_rev"] = chk.returncode == 0
    if not a.skip_suites:
        res["suites"] = [
            suite(["unittests/*InstructionSelector*", "unittests/*InstructionScheduler*"]),
            suite(["unittests/*RunWasmSimd*", "unittests/*WasmSimd*", "unittests/*RunWasmRelaxedSimd*"]),
            suite(["mjsunit/wasm/*", "mjsunit/regress/wasm/*"]),
        ]
    res["new_test"] = {"base": new_test(BASE_D8), "patched": new_test(V8 / "out/rel/d8")}
    res["codegen_qsx_simd"] = {"base": codegen(BASE_D8), "patched": codegen(V8 / "out/rel/d8")}
    if a.mutation:
        src = (V8 / CG).read_text()
        i = src.index("case kArm64V128AnyTrueRaw")
        good = "__ Fmov(i.OutputRegister64(), temp.D());"
        j = src.index(good, i)
        (V8 / CG).write_text(src[:j] + "__ Fmov(i.OutputRegister32(), temp.S());" + src[j + len(good):])
        try:
            build_d8()
            res["mutation"] = {"description": "move only the low 32 bits of the umaxp result",
                               "new_test": new_test(V8 / "out/rel/d8")}
        finally:
            (V8 / CG).write_text(src)
            build_d8()
        res["mutation"]["restored_new_test"] = new_test(V8 / "out/rel/d8")
    write_result(a.out, res, vars(a), None, extra_tools={"v8_rev": base})
    print({k: v for k, v in res.items() if k != "codegen_qsx_simd"})


if __name__ == "__main__":
    main()
