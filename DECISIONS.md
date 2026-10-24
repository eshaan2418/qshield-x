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
