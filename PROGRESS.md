# PROGRESS

Status legend: todo / in-progress / done / blocked-with-fallback

| M | Title | Status | Evidence |
|---|-------|--------|----------|
| M0 | Bootstrap | done | ENVIRONMENT.md, Makefile, `.github/workflows/ci.yml`, `infra/docker/Dockerfile`; local `make ci` green: results/ci/ |
| M1 | Software baselines | done (latency re-measure idle pending) | results/M1/ |
| M2 | RTL decoder + FPGA flow | in-progress | cosim d=3,5 final RTL 0 mismatches (results/M2/cosim), d=7 running; bench/m2_hw.py running; FPGA matrix running (results/M2/fpga_run.log); bench/m2_report.py written |
| M3 | Formal verification | in-progress | quick jobs PASS in CI; `formal/run_formal.py` full run pending; bench/m3_overhead.py written (needs shell_latency.json) |
| M4 | Native + Wasm SIMD | in-progress | harness d8 path fixed (was silently not running); full timing run pending idle machine |
| M5 | V8 engine contribution | in-progress | v8/patches/0001 (arm64 any_true->cbz/cbnz), unittests+mjsunit test, results/M5/v8_tests.json (all suites pass, mutation caught); perf A/B (v8/bench_anytrue.py) pending idle machine |
| M6 | Adaptive / learned decoding | in-progress | results/M6/*; figures in bench/make_figures.py; GNN latency re-measure idle pending |
| M7 | Federated training | in-progress | federated/fed.py running -> results/M7/federated_d3.json |
| M8 | Secure infra | done | infra/, tests/test_infra.py, results/M8/overhead.json |
| M9 | Visualization (optional) | todo (skip unless time) | |
| M10 | Integration + write-up | in-progress | bench/e2e_demo.py + wasm/replay.js (smoke OK); make_figures.py; paper/docs/claims_ext pending |

## Key facts to remember (resumption)
* Final RTL = commit c079471 (co-sim campaign re-run on it). tb/top_tb.cpp gained --dump/--max-rounds after that.
* Do not run >3 Yosys d>=7 jobs concurrently (swap thrash observed).
* Timer resolution: host steady_clock 41.67 ns; headless Chrome performance.now 5 us (per-shot Chrome latency
  percentiles are meaningless; use steady-state throughput).
* Latency/perf numbers must be (re)measured with the machine idle: M1 latency, M4 runtime, M5 A/B, M6 GNN latency.
  Another user project (docker aegis-lab) also loads this machine; record load average in provenance.
* V8: base d8 saved in build/v8_base/; patched d8 at v8/src/v8/out/rel/d8 (branch qsx-anytrue-branch-fusion).

## Next action
When background jobs finish: m3_overhead, run_formal, PIPE=1 co-sim, then idle-machine timing (M1, M4, M5, M6),
claims_ext + docs + paper.
