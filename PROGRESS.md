# PROGRESS

Status legend: todo / in-progress / done / blocked-with-fallback

| M | Title | Status | Evidence |
|---|-------|--------|----------|
| M0 | Bootstrap | done | ENVIRONMENT.md, Makefile, CI workflow, Dockerfile; local `make ci` green (results/ci/) |
| M1 | Software baselines | done | results/M1/ |
| M2 | RTL decoder + FPGA flow | in-progress (FPGA tail) | co-sim 3.84M + 1.04M syndromes, 0 mismatches; hw_cycles, cycle_breakdown, shell_latency, toggle_proxy; FPGA d=3/5 placed, d>=7 does not fit; d=9 synth + LANES=V batch running |
| M3 | Formal verification | done | results/M3/formal_summary.json: 17/17 jobs as expected (k-induction shell + real core d=3/5/7, BMC/cover, TLC main + mutants + pre-fix cex, Z3 d=3/5 + mutant); overhead in results/M3/overhead.json |
| M4 | Native + Wasm SIMD | done | results/M4 (bit-exact; Liftoff vs Turboshaft fixed, B8) |
| M5 | V8 engine contribution | done | v8/patches/0001, results/M5/v8_tests.json (2,955 tests pass, mutation caught, applies cleanly) |
| M6 | Adaptive / learned | done | results/M6; C++ policy statistics; re-measure in `make timing` |
| M7 | Federated training | done | results/M7 (+ dp_debug, plateau_check, lot-8192 sweeps); DECISIONS D9/D10 |
| M8 | Secure infra | done | infra/, tests, results/M8 |
| M9 | Visualization | done | viz/ (make viz / make viz-test) |
| M10 | Integration + write-up | in-progress | e2e demo, objective, claims/tables, paper (Wasm section pending), README/FINAL_REVIEW/RESUME templates; clean-clone reproduce-quick running |

## Key facts to remember (resumption)
* `build/start_timing.sh` auto-starts `make timing` when both FPGA batches + run_formal have exited
  (build/timing.start, build/timing.done, results/timing_run.log).
* Final RTL = c079471 (unchanged since). Commit signing uses 1Password SSH; if commits fail, ask the user to unlock.
* Shared machine (another project's VM + cargo builds): timing results record loadavg.
* After timing: make figures, check-numbers, paper, viz-test, clean-clone reproduce-quick (build/clean_clone with
  .tools/.venv symlinks), FINAL_REVIEW verdict text (HW_VERDICT_TEXT, M2_d7_fit_text claims), Wasm section.

## Next action
`build/finalize.sh` (running): waits for the FPGA matrix (capped 03:30, D11) -> collect -> critpath -> M3 overhead
d=3,5,7 -> report -> viz data -> figures -> check-numbers -> paper -> viz-test -> commit -> clean-clone
reproduce-quick. Log: build/finalize.log. After it passes: mark M2/M3/M10 done and write the final summary.
