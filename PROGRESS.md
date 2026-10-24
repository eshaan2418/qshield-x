# PROGRESS

Status legend: todo / in-progress / done / blocked-with-fallback

| M | Title | Status | Evidence |
|---|-------|--------|----------|
| M0 | Bootstrap | in-progress | ENVIRONMENT.md, Makefile, `make test` (CI file pending) |
| M1 | Software baselines | done | results/M1/ (pl sweep, latency, summary) |
| M2 | RTL decoder + FPGA flow | in-progress | |
| M3 | Formal verification | todo | |
| M4 | Native + Wasm SIMD | todo | |
| M5 | V8 engine contribution | todo | |
| M6 | Adaptive / learned decoding | todo | |
| M7 | Federated training | todo | |
| M8 | Secure infra | todo | |
| M9 | Visualization (optional) | todo | |
| M10 | Integration + write-up | todo | |

## M2 plan
1. `rtl/gen_graph.py` emits graph tables (done).
2. `rtl/qsx_uf_core.sv`: FSM IDLE→LABEL→PAR→ACT→CHK→GROW…→DINIT→DIST→PEH→PEEL→DONE, LANES param.
   Accept: bit-exact + cycle-exact vs `qsx::HwModel` (decoders/) on random + Stim syndromes.
3. `rtl/qsx_top.sv`: AXIS ingress frame FIFO (BRAM), cfg block (atomic threshold load), egress formatter.
4. `tb/`: Verilator co-sim ≥1e6 random + ≥1e5 Stim per distance (3,5,7).
5. `fpga/`: yosys synth_ecp5 + nextpnr-ecp5 per (d, lanes); report table + Pareto.

## Next action
Write rtl/qsx_uf_core.sv and tb/core_tb.cpp (Verilator vs HwModel).
