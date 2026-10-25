# BLOCKERS

| ID | Date | Blocker | Fallback used | Impact on claims |
|----|------|---------|---------------|------------------|
| B1 | 2026-10-24 | No git remote / hosted CI configured; pushing is outward-facing and not done autonomously. | `.github/workflows/ci.yml` defined; identical steps executed locally by `make ci`, logs in `results/ci/`. | Resolved 2026-10-25: published to GitHub; CI installs the pinned toolchain on a hosted runner (`ci/setup_tools.sh`). |
| B2 | 2026-10-24 | No FPGA board; no Vivado/Quartus licence. | Yosys + nextpnr-ecp5 (LFE5U-85F); Verilator cycle counts for latency. | No on-board measurements. All hardware numbers are labelled sim/synth/pnr. |
| B3 | 2026-10-24 | No vendor power estimator for ECP5 in the open flow. | Toggle-count activity proxy from Verilator simulation. | Energy numbers are relative estimates only, not Watts. |
| B4 | 2026-10-24 | V8 build interrupted by a host restart (2360/2514 steps); co-sim d=7 and M7 runs were lost. | Rebuilt incrementally; campaigns re-run on the final RTL. | None (all reported runs post-date the restart). |
| B5 | 2026-10-24 | `wasm/harness.js` d8 path never executed (IIFE shadowed d8's global `arguments`; no TextEncoder in d8). | Fixed; d8 numbers only from after the fix. | M4 smoke results before the fix contain no d8 rows. |
| B6 | 2026-10-24 | Machine shared with an unrelated workload (docker); load average up to ~60 during campaigns. | Timing experiments run last, with load average recorded; A/B runs interleaved base/patched. | Absolute latencies may be pessimistic; A/B ratios are paired. |
| B7 | 2026-10-24 | Headless Chrome `performance.now()` resolution 5 µs (COOP/COEP isolated). | Chrome reported by steady-state throughput only. | No per-shot Chrome latency percentiles. |
| B8 | 2026-10-25 | `--liftoff --no-wasm-tier-up` no longer prevents tier-up in V8 15.8 (dynamic tiering), so the first M4 "liftoff-only" rows were TurboFan. | Switched to `--liftoff-only` (d8 and Chrome `--js-flags`) and re-ran M4. | Only the re-run is reported. |
