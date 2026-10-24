# PROGRESS

Status legend: todo / in-progress / done / blocked-with-fallback

| M | Title | Status | Evidence |
|---|-------|--------|----------|
| M0 | Bootstrap | in-progress | ENVIRONMENT.md, Makefile, `.github/workflows/ci.yml`, `infra/docker/Dockerfile`; `make ci` local run pending |
| M1 | Software baselines | done | results/M1/ (pl sweep d=3..9, latency, summary.json, figs) |
| M2 | RTL decoder + FPGA flow | in-progress | cosim d=3,5 done (0 mismatches), d=7 running; FPGA matrix pending (was stopped: memory thrash) |
| M3 | Formal verification | in-progress | ingress prove PASS, top stub_prove PASS, core prove PASS (d=3), TLC main PASS + cex/mutations, Z3 d=3 PASS; `formal/run_formal.py` full run pending |
| M4 | Native + Wasm SIMD | in-progress | builds bit-exact (hash) across native/node/chrome; full timing run pending idle machine + d8 |
| M5 | V8 engine contribution | in-progress | V8 fetched (rev in build/v8_rev.txt), d8 building |
| M6 | Adaptive / learned decoding | in-progress | GNN d3/d5 trained+evaluated (results/M6/gnn_d*); adaptive d5 done (results/M6/adaptive_d5.json); figures + idle latency re-measure pending |
| M7 | Federated training | in-progress | federated/fed.py running → results/M7/federated_d3.json |
| M8 | Secure infra | done | infra/, tests/test_infra.py (7 pass), results/M8/overhead.json |
| M9 | Visualization (optional) | todo | |
| M10 | Integration + write-up | todo | |

## Key facts to remember (resumption)
* RTL edits after commit b95c6f9 are `ifdef FORMAL`-only (+ guard changes); co-sim executables for d=7 were built
  from b95c6f9 RTL. After the d=7 campaign: commit, then re-run `make cosim-quick` on the final RTL.
* Do not run >3 Yosys d≥7 jobs concurrently (each uses many GB; swap thrash observed).
* Timer resolution on host: 41.67 ns (steady_clock).
* Under heavy load, latency numbers are invalid: re-measure M1/M4/M6 latency with the machine idle.

## Next action
When V8 build finishes: run FPGA matrix (`python fpga/run_fpga.py --jobs 3`), then M5 codegen study.
