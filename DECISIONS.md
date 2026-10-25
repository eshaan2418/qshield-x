# DECISIONS

Dated, append-only. Each entry: decision, rationale, consequences.

## 2026-10-24 D1 — Decoder algorithm for hardware: "QSX-UF", a Jacobi-synchronous union-find with canonical BFS peeling

**Decision.** The hardware decoder and the C++ golden model implement the same *semantic*
algorithm, defined so that every intermediate result is independent of evaluation order
(which allows a fully parallel RTL and a sequential C++ model to be bit-exact):

1. Decoding graph `G=(V ∪ {B}, E)`, built from the Stim detector error model (DEM) with
   `decompose_errors=True`; each graphlike component becomes an edge; parallel edges are merged
   (XOR-combined probability `p1(1-p2)+p2(1-p1)`). `B` is a single virtual boundary vertex.
   Edges are indexed in lexicographic `(u, v)` order with `B = V` (largest index).
2. Each edge has an integer growth threshold `thr[e] ∈ [1, 15]` (unweighted: all 2).
   `support[e] ∈ [0, thr[e]]`; edge is *grown* iff `support[e] == thr[e]`.
3. Clusters = connected components of `V` over grown non-boundary edges (order-independent).
   `parity(C)` = XOR of defects in C; `bnd(C)` = C contains a vertex whose boundary edge is grown.
   Vertex `v` is *active* iff `parity(C(v)) ∧ ¬bnd(C(v))`.
4. Growth round (synchronous / Jacobi): for every edge `e=(u,v)`:
   `support[e] ← min(thr[e], support[e] + active[u] + active[v])` (`active[B]=0`), using
   activity computed *before* the round. Then clusters are recomputed. Repeat while any vertex is
   active, up to `max_rounds` (timeout → status `TIMEOUT`, never a valid correction).
5. Canonical spanning forest: for each cluster, root = virtual boundary if `bnd(C)`, else the
   minimum-index vertex. `dist` = BFS distance (boundary-adjacent vertices with a grown boundary
   edge have `dist=1`, non-boundary roots `dist=0`). Parent edge of `v`: its grown boundary edge if
   any; otherwise the *lowest-index* grown incident edge whose other endpoint has `dist[v]-1`.
6. Peeling: in decreasing `dist`, `acc[v] = defect[v] ⊕ (⊕ acc[children])`, `corr[pe(v)] = acc[v]`.
   A non-boundary root with `acc=1` → status `PARITY_ERROR` (must never occur; checked).
7. Output: observable prediction = XOR of `obs[e]` over corrected edges, plus the correction bitmap.

**Rationale.** Union-find (Delfosse & Nickerson, Quantum 2021) has near-linear complexity, small
integer state, and only local operations, which is why it is the basis of published FPGA decoders
(e.g. Helios, Liyanage et al. 2023; AFS, Das et al. 2022). Matching (PyMatching / sparse blossom)
needs priority queues and dynamic alternating trees, which are hard to bound in hardware. The Jacobi
growth rule and the canonical forest remove all order dependence, so the parallel RTL can be compared
*bit-exactly* (correction bitmap, not only the logical prediction) against the C++ model.

**Consequences.** P_L of QSX-UF is expected to be worse than PyMatching (UF is an approximation
to MWPM); this is measured, not assumed. Weighted thresholds are a configuration, not a separate
algorithm.

## 2026-10-24 D2 — Noise model and experiment family
Stim `surface_code:rotated_memory_z`, `rounds = d`, uniform circuit-level depolarizing noise with
the same `p` for `after_clifford_depolarization`, `before_round_data_depolarization`,
`before_measure_flip_probability`, `after_reset_flip_probability`. The decoder graph is built from the DEM of
the same circuit (the decoder knows `p`) unless an experiment states otherwise (M6 noise-shift).

## 2026-10-24 D3 — FPGA flow and target
No FPGA board, no Vivado/Quartus. Fallback rung: Yosys + nextpnr-ecp5 targeting Lattice ECP5
LFE5U-85F (CABGA381, speed 8), the largest ECP5 device supported by the open flow. Hardware numbers
are labelled `sim` (Verilator cycle counts), `synth` (Yosys), or `pnr` (nextpnr timing/utilisation).
Power is a toggle-count proxy from simulation, labelled `estimate`.

## 2026-10-24 D4 — CI
There is no git remote. CI is defined (`.github/workflows/ci.yml`, `infra/docker/Dockerfile`) and executed locally via
`make ci` (the same commands the workflow runs). Pushing to a hosted remote is an outward-facing action
not taken autonomously; see BLOCKERS.md B1.

## 2026-10-24 D5 — Default edge-weight quantisation: `q5` (3-bit thresholds)
Pilot (`results/M1/pilot_weights/`, d∈{5,7}, p∈{0.003,0.006}) compared unweighted, q1–q6 (max 7) and
q5/q6/q8 with 4-bit thresholds (max 15). q5 was best or tied-best among 3-bit options at all four points; 4-bit q8m15 was
only marginally better at high p. Choice: `q5` (thr = clamp(round(5·w/median(w)),1,7), 3-bit counters) is the
default "weighted QSX-UF" configuration for RTL; `unweighted` (thr=2, 2-bit counters) is the minimal-area configuration.
Both are reported.

## 2026-10-24 D6 — M5 engine contribution: arm64 `v128.any_true` → `cbz/cbnz` fusion (V8 path)
`--print-wasm-code` on the decoder's SIMD unpack loop (zero-block skip, `qsx::unpack_simd`) showed that
Turboshaft/arm64 lowers `br_if(v128.any_true(x))` to `umaxp; fmov; cmp; cset; cbnz` — the boolean is
materialised and then tested again. The patch (v8/patches/0001-*.patch) matches a covered
`Simd128TestOp::kV128AnyTrue` in `VisitWordCompareZero` and emits a new `kArm64V128AnyTrueRaw`
(`umaxp; fmov`) followed by `cbz/cbnz` (or `tst` + flags for select/set). Chosen because it is (a) present in
the project's own hot loop (3 sites in the real module), (b) small, local and testable with the existing
instruction-selector unittest infrastructure, and (c) not already upstream at the recorded revision (code
inspection; x64 has the same pattern with `ptest/setcc/test/jcc`, left as follow-up). Blink path not taken.

## 2026-10-24 D7 — Hardware latency methodology
Hardware latency = cycles × (1/Fmax). Cycles come from the cycle-exact `qsx::HwModel` (bit- and
cycle-exact with the RTL core, checked per syndrome in co-simulation) plus the shell's measured framing
overhead (Verilator `qsx_top`, one frame in flight); Fmax comes from nextpnr-ecp5 (timing-driven, seed 1).
Every derived latency is labelled "sim cycles / pnr Fmax". It excludes host↔FPGA transport (PCIe/USB),
which a board measurement would include; the CPU baselines likewise exclude syndrome acquisition.

## 2026-10-24 D8 — End-to-end demo
The M10 demo drives the real RTL (Verilator `qsx_top`) rather than the model, configures it through an
atomic cfg session with a small growth-round limit so that hardware TIMEOUTs occur, injects lost responses,
and implements the host side of `QSXProtocol.tla` in Python with the spec's safety invariants asserted at
run time. Inspection replay uses the Wasm build in Node.js (same code path as the browser).

## 2026-10-24 D9 — DP-SGD configuration for M7 (found by debugging, tuned on validation data only)
The first FedAvg+DP runs (batch 512, 40x100 steps, Adam lr 2e-3, clip 1) produced P_L that was identical across
sigma = 0.6, 1.0, 2.0. Investigation: at batch 512 the clipped per-coordinate signal from the ~4-10% positive
examples (~4e-4) is below the per-coordinate noise (sigma*clip/batch ~ 1e-3 to 4e-3). Adam normalises the
noise-dominated updates, and the local models drift to the majority-class predictor. Following Abadi et al. (large
lots), DP regimes use batch 8192 (q = 0.041), 20 rounds x 15 local steps, lr 3e-3. These settings were checked on
validation data drawn with seeds disjoint from fed.py's train/test seeds. On validation, sigma = 0.6 learns (P_L 2.7%,
base rate 10.3%) and sigma = 2.0 collapses, i.e. noise now visibly trades utility for privacy. The batch-512 results
stay in results/M7/federated_d3.json and are reported as the failed configuration. Their sigma-independence is
explained in results/M7/dp_debug.json.

## 2026-10-24 D10 — M7 DP plateau (supersedes the clipping / signal-to-noise explanation in D9)
Ablations refute D9's hypotheses. With lot 512, clip-only (sigma = 0) learns a better decoder (results/M7/
federated_d3_clip_ablation.json), so clipping is not the cause. With lot 8192 and 300 steps, even sigma = 0 lands on
the same P_L as every sigma > 0 (results/M7/federated_d3_dp_b8192.json). Explanation: a training-budget plateau.
DP-limited training reaches a decoder that classifies the frequent low-weight syndromes like any reasonable decoder
(P_L between "PyMatching on syndromes of weight <= 3, else 0" and "<= 4", computed on the fed.py test sets). Models
on the plateau agree on almost every test syndrome, so their error counts differ by a few in 200k. Prediction: more
DP steps escape the plateau at higher epsilon (results/M7/federated_d3_dp_b8192_long.json). Reported as: within the
tested step budget, privacy from epsilon ~ 17.6 down to ~ 0.33 costs no additional utility beyond the plateau.
