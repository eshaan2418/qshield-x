# Formal verification (M3)

All jobs: `make formal` (`formal/run_formal.py`) → `results/M3/formal_summary.json` + logs.
Quick subset for CI: `make formal-quick`.

What these proofs do **not** establish: they say nothing about the logical error rate (that is measured by
Monte Carlo in M1/M6 with confidence intervals), and they are about the RTL / protocol models stated below,
for the bounds stated below.

## SVA + SymbiYosys (RTL)

Engine: `smtbmc bitwuzla`. "prove" = k-induction (base case + inductive step, unbounded result);
"bmc" = bounded model check to the stated depth; "cover" = reachability witnesses.
Environment assumptions (all harnesses): reset asserted in cycle 0; AXI-Stream / cfg masters hold
`valid`/payload stable until accepted.

| ID | Property | Where | Mode |
|----|----------|-------|------|
| P1 | AXI-Stream master compliance: `tvalid && !tready` ⇒ next cycle `tvalid` and `tdata`/`tlast` unchanged; `tlast ⇒ tvalid` | `top_formal.sv` | prove (abstract core), bmc (real core) |
| P2 | Every response carries the round tag of its request, in order (tracked-frame oracle with location invariant over FIFO slots, dispatcher and egress) | `top_formal.sv` | prove / bmc |
| P3 | No loss, duplication or spurious response: `received headers − emitted headers == frames inside` (ingress partial + FIFO + dispatcher + egress) | `top_formal.sv` + `qsx_top.sv` | prove / bmc |
| P4 | Invalid / timeout / error responses are never presented as valid: status ≠ OK ⇒ obs = 0 and all correction beats = 0; header well-formed, status ∈ {0..5} | `top_formal.sv` + `qsx_top.sv` | prove / bmc |
| P5 | Atomic reconfiguration: `cfg_ok`/`cfg_open` equal a reference model (COMMIT valid only if every threshold word was written in the session) | `top_formal.sv` | prove / bmc |
| P6 | The core starts only with `cfg_ok && !cfg_open`, no configuration write is accepted while the core is busy or starting, and thresholds are constant during a decode (asserted inside the abstract core) | `qsx_top.sv`, `core_stub.sv` | prove |
| I1 | Ingress: never writes a beat while all slots are full (no silent overwrite); occupancy = pointer distance; framing counters bounded | `qsx_ingress.sv` | prove (W=2,NBUF=4 and W=4,NBUF=2) |
| C1 | Core: status ≠ OK ⇒ correction = 0 and obs = 0 | `core_formal.sv` | prove (d=3, 5, 7) |
| C2 | Core: with watchdog enabled, work cycles ≤ `cycle_budget` (bounded latency by construction) | `core_formal.sv` | prove (d=3, 5, 7) |
| C3 | Core: status codes ∈ {0..3} | `core_formal.sv` | prove (d=3, 5, 7) |
| C4 | Core: busy span ≤ budget + 1 | `core_formal.sv` | prove (d=3, 5, 7) |
| C5 | Core: `done` is a one-cycle pulse followed by idle | `core_formal.sv` | prove (d=3, 5, 7) |

**Abstraction argument.** `stub_prove` replaces `qsx_uf_core` by `core_stub.sv`, which allows *any*
latency, status and correction, constrained only by the core's interface guarantees (busy/done protocol,
outputs stable while idle, status ≠ OK ⇒ zero correction). Those guarantees are themselves proven on the real
core (C1, C5) for d=3. The shell properties therefore hold for every core behaviour, and the real-core BMC
(`real_bmc`) checks the composition directly to the stated depth.

**Scope / bounds.** The real-core k-induction proofs (C1–C5) run on the d=3, d=5 and d=7 graphs with LANES=8
(`core.sby` tasks `prove`, `prove_d5`, `prove_d7`). These properties concern control and masking, so they stay
tractable as the datapath grows: the d=7 proof takes minutes, mostly elaboration. Functional equivalence of the larger
cores is covered by co-simulation (M2) and by the Z3 one-step check (below), not by k-induction.
C2/C4 are scoped to `cycle_budget ≠ 0`. With the watchdog disabled the 20-bit `cycles` counter could only
wrap after 2^20 work cycles. The analytical worst case is (max_rounds+1)·(V+1+2·⌈V/LANES⌉+2) + 2V + 4, which
for max_rounds = 255 is below 2^17 for d ≤ 7.

**Inductive strengthening (design history).** The first k-induction attempts failed on unreachable
states. The resulting strengthening invariants are part of the RTL (`ifdef FORMAL`) and of the harness:
core-busy ⇔ dispatcher-waiting; drop mode ⇒ beat counter idle; harness framing ⇔ DUT framing;
non-saturating frame accounting; the tag-location invariant; and egress status-range invariants. One
assertion was over-strong (it forbade the host from raising `cfg_valid` in the core-start cycle, which is
legal because `cfg_ready` is low). It was weakened to the intended property: no write is *accepted*.
None of these steps exposed a functional RTL bug. Co-simulation had already passed on the same RTL.

## TLA+ (TLC) — host ↔ accelerator ↔ software-fallback protocol (`tla/QSXProtocol.tla`)

Safety: `NoDoubleCommit`, `NoSkip` (exactly the prefix 1..k committed), `ExclusiveSource` (HW xor SW),
`NoInvalidCommit` (no non-OK HW result committed), `NoOverflow` (FIFO depth K).
Liveness: `AllCommitted`, `EachRoundCompletes`. Fairness: weak fairness on host submit/bypass, timeout,
fallback decode, receive, commit and on closing a configuration session. **No fairness for the
accelerator**, which may stall or lose requests forever. Reconfiguration sessions are bounded by `MaxCfg`.

**Counterexample found and fixed.** The first spec (`MC_v0_nobypass.cfg`) violates liveness. Timed-out
requests left in a stalled accelerator fill its K-deep FIFO and block every later submission. Fix: a host
submission deadline that bypasses the accelerator (`HostBypass`). Mutation checks: removing the
stale-response filter (`CHECK_STALE=FALSE`) or the status check (`CHECK_STATUS=FALSE`) violates `Safety`.

## Z3 / SMT — bounded equivalence of the real core (`z3/check_core_steps.py`)

Yosys exports `rtl/qsx_uf_core.sv` (flattened) as an SMT-LIB transition relation. For **all** register and
input values (reachable or not), Z3 proves that one clock step in each state equals a reference built
independently from the `.qsxg` graph file (DECISIONS D1):
LABEL (min-label propagation + convergence branch), GROW (saturating support update),
DIST (BFS distance relaxation with absorbing INF) and PEH (canonical lowest-edge-index parent selection).
This also checks the RTL table generator (`rtl/gen_graph.py`). A mutated reference (highest-index parent)
must be SAT, which guards against vacuity. Bound: one transition, per graph instance (d=3, d=5).

## Overhead of verification-driven mechanisms
See `results/M3/overhead.json` (`bench/m3_overhead.py`): extra state for tags/handshakes/config atomicity
(synthesised LUT/FF difference) and the cycle cost of the dispatcher/ingress handshakes, compared with a
bare core.
