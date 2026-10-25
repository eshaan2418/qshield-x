# PROGRESS

Status legend: todo / in-progress / done / blocked-with-fallback

| M | Title | Status | Evidence |
|---|-------|--------|----------|
| M0 | Bootstrap | done | ENVIRONMENT.md, Makefile, CI workflow, Dockerfile; local `make ci` green (results/ci/) |
| M1 | Software baselines | done (latency re-measure in `make timing`) | results/M1/ |
| M2 | RTL decoder + FPGA flow | in-progress (FPGA tail) | co-sim 3.84M + 1.04M syndromes, 0 mismatches; hw_cycles, cycle_breakdown, shell_latency, toggle_proxy; FPGA d=3/5 placed, d>=7 does not fit; d=9 synth + LANES=V batch running |
| M3 | Formal verification | in-progress | all SBY proofs PASS incl. real core d=3/5/7 k-induction; run_formal summary pending (Z3 d=5 running); then `run_formal --only core.sby:prove_d5,core.sby:prove_d7` merge |
| M4 | Native + Wasm SIMD | in-progress | bit-exact native/node/d8/chrome; timing in `make timing` |
| M5 | V8 engine contribution | done except perf A/B (`make timing`) | v8/patches/0001, results/M5/v8_tests.json (2,955 tests pass, mutation caught, applies cleanly) |
| M6 | Adaptive / learned | in-progress | results/M6; C++ policy statistics; re-measure in `make timing` |
| M7 | Federated training | done | results/M7 (+ dp_debug, plateau_check, lot-8192 sweeps); DECISIONS D9/D10 |
| M8 | Secure infra | done (overhead re-measure in `make timing`) | infra/, tests, results/M8 |
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
Wait for FPGA/formal; then timing pass; then finalize docs (see above).
