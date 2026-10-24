---------------------------- MODULE QSXProtocol ----------------------------
(***************************************************************************)
(* Host <-> accelerator <-> software-fallback protocol of QShield-X.        *)
(*                                                                         *)
(* The host submits decoding requests for rounds 1..N (tag = round) to an  *)
(* in-order accelerator through a bounded FIFO (depth K, backpressure).    *)
(* The accelerator answers each request with OK or an error status         *)
(* (TIMEOUT / WATCHDOG / PARITY / FRAME / CFG_INVALID), or loses it        *)
(* (hang/crash model). A host deadline timer may expire at any time while  *)
(* a request is outstanding (real time is abstracted away), after which    *)
(* the round is re-decoded by the software fallback. Late hardware         *)
(* responses for such rounds must be discarded. Results are committed in   *)
(* round order. Reconfiguration sessions (BEGIN/WRITE/COMMIT) may run only *)
(* while the accelerator is idle; a partially written configuration makes  *)
(* the accelerator answer CFG_INVALID.                                     *)
(*                                                                         *)
(* CHECK_STALE / CHECK_STATUS are mutation switches: setting either to     *)
(* FALSE removes a host-side guard and TLC must find a safety violation.   *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS N,            \* number of rounds
          K,            \* accelerator input FIFO depth
          CHECK_STALE,  \* host discards responses for rounds not awaiting HW
          CHECK_STATUS, \* host commits HW results only when status = OK
          CHECK_BYPASS, \* host may bypass a blocked accelerator (submission deadline)
          MaxCfg        \* bound on reconfiguration sessions (keeps the model finite)

Rounds == 1..N
Phases == {"new", "hw", "sw", "ready_hw", "ready_sw", "committed"}

VARIABLES
  phase,      \* phase[r]
  src,        \* src[r] \in {"none","hw","sw"}: source of the committed result
  ncommit,    \* number of commit events per round (for NoDoubleCommit)
  hwq,        \* requests inside the accelerator FIFO (sequence of tags)
  respq,      \* responses from accelerator to host: sequence of [tag, ok]
  nextc,      \* next round to commit (in-order commit pointer)
  cfg,        \* accelerator configuration: "valid" | "open" | "partial"
  badok,      \* TRUE iff a non-OK HW result was ever committed
  ncfg        \* reconfiguration sessions started

vars == <<phase, src, ncommit, hwq, respq, nextc, cfg, badok, ncfg>>

Init ==
  /\ phase = [r \in Rounds |-> "new"]
  /\ src = [r \in Rounds |-> "none"]
  /\ ncommit = [r \in Rounds |-> 0]
  /\ hwq = << >>
  /\ respq = << >>
  /\ nextc = 1
  /\ cfg = "valid"
  /\ badok = FALSE
  /\ ncfg = 0

\* ---------------------------------------------------------------- host
HostSend(r) ==
  /\ phase[r] = "new"
  /\ \A q \in 1..(r-1) : phase[q] # "new"           \* submit in order
  /\ Len(hwq) < K                                    \* backpressure: never overwrite
  /\ cfg # "open"                                    \* no submissions during a session
  /\ hwq' = Append(hwq, r)
  /\ phase' = [phase EXCEPT ![r] = "hw"]
  /\ UNCHANGED <<src, ncommit, respq, nextc, cfg, badok, ncfg>>

\* Submission deadline: a round that cannot be (or is not) submitted in time is decoded in software.
\* Added after TLC found a liveness counterexample without it (results/M3/tla/v0_*.log): stale requests
\* left in a stalled accelerator fill its FIFO and block every later submission forever.
HostBypass(r) ==
  /\ CHECK_BYPASS
  /\ phase[r] = "new"
  /\ \A q \in 1..(r-1) : phase[q] # "new"
  /\ phase' = [phase EXCEPT ![r] = "sw"]
  /\ UNCHANGED <<src, ncommit, hwq, respq, nextc, cfg, badok, ncfg>>

\* Deadline expiry (or explicit error) moves the round to the software fallback.
HostTimeout(r) ==
  /\ phase[r] = "hw"
  /\ phase' = [phase EXCEPT ![r] = "sw"]
  /\ UNCHANGED <<src, ncommit, hwq, respq, nextc, cfg, badok, ncfg>>

HostRecv ==
  /\ respq # << >>
  /\ LET m == Head(respq) IN
       /\ respq' = Tail(respq)
       /\ IF CHECK_STALE /\ phase[m.tag] # "hw"
            THEN UNCHANGED <<phase, badok>>                   \* stale: discard
          ELSE IF m.ok \/ ~CHECK_STATUS
            THEN /\ phase' = [phase EXCEPT ![m.tag] = "ready_hw"]
                 /\ badok' = (badok \/ ~m.ok)
          ELSE /\ phase' = [phase EXCEPT ![m.tag] = "sw"]    \* error status -> fallback
               /\ UNCHANGED badok
  /\ UNCHANGED <<src, ncommit, hwq, nextc, cfg, ncfg>>

SWDecode(r) ==                                         \* software fallback is reliable
  /\ phase[r] = "sw"
  /\ phase' = [phase EXCEPT ![r] = "ready_sw"]
  /\ UNCHANGED <<src, ncommit, hwq, respq, nextc, cfg, badok, ncfg>>

HostCommit ==
  /\ nextc <= N
  /\ phase[nextc] \in {"ready_hw", "ready_sw"}
  /\ src' = [src EXCEPT ![nextc] = IF phase[nextc] = "ready_hw" THEN "hw" ELSE "sw"]
  /\ ncommit' = [ncommit EXCEPT ![nextc] = @ + 1]
  /\ phase' = [phase EXCEPT ![nextc] = "committed"]
  /\ nextc' = nextc + 1
  /\ UNCHANGED <<hwq, respq, cfg, badok, ncfg>>

\* Reconfiguration: only when the accelerator holds no requests.
CfgBegin ==
  /\ cfg # "open" /\ hwq = << >> /\ ncfg < MaxCfg
  /\ cfg' = "open"
  /\ ncfg' = ncfg + 1
  /\ UNCHANGED <<phase, src, ncommit, hwq, respq, nextc, badok>>
CfgCommit(complete) ==
  /\ cfg = "open"
  /\ cfg' = IF complete THEN "valid" ELSE "partial"
  /\ UNCHANGED <<phase, src, ncommit, hwq, respq, nextc, badok, ncfg>>

\* ---------------------------------------------------------------- accelerator
HWProcess(ok) ==
  /\ hwq # << >>
  /\ cfg # "open"                                     \* RTL: dispatcher gated while open
  /\ LET okv == ok /\ cfg = "valid" IN                 \* partial config -> CFG_INVALID
       respq' = Append(respq, [tag |-> Head(hwq), ok |-> okv])
  /\ hwq' = Tail(hwq)
  /\ UNCHANGED <<phase, src, ncommit, nextc, cfg, badok, ncfg>>

HWLose ==                                              \* hang / lost frame
  /\ hwq # << >>
  /\ hwq' = Tail(hwq)
  /\ UNCHANGED <<phase, src, ncommit, respq, nextc, cfg, badok, ncfg>>

Next ==
  \/ \E r \in Rounds : HostSend(r) \/ HostBypass(r) \/ HostTimeout(r) \/ SWDecode(r)
  \/ HostRecv \/ HostCommit
  \/ CfgBegin \/ \E c \in BOOLEAN : CfgCommit(c)
  \/ \E ok \in BOOLEAN : HWProcess(ok)
  \/ HWLose

\* Fairness: host, fallback, commit and the session close are weakly fair. The accelerator gets
\* no fairness (it may stall or lose requests forever); progress relies on the deadline timer.
Fairness ==
  /\ \A r \in Rounds : WF_vars(HostBypass(r)) /\ WF_vars(HostTimeout(r)) /\ WF_vars(SWDecode(r))
  /\ WF_vars(HostRecv) /\ WF_vars(HostCommit)
  /\ WF_vars(CfgCommit(TRUE))

Spec == Init /\ [][Next]_vars /\ Fairness

\* ---------------------------------------------------------------- properties
TypeOK ==
  /\ phase \in [Rounds -> Phases]
  /\ src \in [Rounds -> {"none", "hw", "sw"}]
  /\ Len(hwq) <= K
  /\ nextc \in 1..(N+1)
  /\ cfg \in {"valid", "open", "partial"}

NoDoubleCommit == \A r \in Rounds : ncommit[r] <= 1
\* No round skipped: exactly the prefix 1..nextc-1 is committed.
NoSkip == \A r \in Rounds : (phase[r] = "committed") <=> (r < nextc)
\* A committed round has exactly one source (HW xor SW).
ExclusiveSource == \A r \in Rounds : (phase[r] = "committed") <=> (src[r] # "none")
\* Never commit a hardware result whose status was not OK.
NoInvalidCommit == ~badok
NoOverflow == Len(hwq) <= K

Safety == NoDoubleCommit /\ NoSkip /\ ExclusiveSource /\ NoInvalidCommit /\ NoOverflow

\* Liveness: every round is eventually committed (each request completes; the only "error state" of
\* a request is fallback to software, which is reliable). Requires the open session to close (fair).
AllCommitted == <>(nextc = N + 1)
EachRoundCompletes == \A r \in Rounds : <>(phase[r] = "committed")
=============================================================================
