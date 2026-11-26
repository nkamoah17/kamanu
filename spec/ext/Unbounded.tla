----------------------------- MODULE Unbounded -----------------------------
(***************************************************************************)
(* Unbounded extension (K9): is a reported deadlock caused by the bound?   *)
(*                                                                         *)
(* The task harness bounds requests with MaxReq, inside Next (Issue needs  *)
(* n < MaxReq). When the agent's retries are all denied, the run ends in a *)
(* state where only that bound stops the agent from trying again. TLC      *)
(* reports DEADLOCK, or a ProgressPossible violation, but with no bound    *)
(* the agent would retry forever without success: a livelock.              *)
(*                                                                         *)
(* This module adds the predicates a classifier needs. A state is Stuck    *)
(* when the task is not done and no progress step is enabled. Every stuck  *)
(* state is BoundOnly when the request count sits at the bound and the     *)
(* agent's guard for Work, minus the bound, still holds.                   *)
(*                                                                         *)
(*   BoundOnlyStuck == Stuck => BoundOnly        (an invariant)            *)
(*                                                                         *)
(* kamanu/unbounded.py checks it at MaxReq and at MaxReq + 1. If the cell  *)
(* is stuck at both bounds and every stuck state is BoundOnly, the verdict *)
(* is LIVELOCK (bound-induced). A stuck state that is not BoundOnly keeps  *)
(* the verdict DEADLOCK. The seed modules stay unchanged.                  *)
(***************************************************************************)
EXTENDS MCTask

\* Work's guard without Issue's bound (n < MaxReq).
WouldWork == /\ ~Goal /\ ~escalated /\ Quiet
             /\ (NeedsApproval => appr = "granted")

Stuck     == ~TaskDone /\ ~ENABLED Progress
BoundOnly == n = MaxReq /\ WouldWork

BoundOnlyStuck == Stuck => BoundOnly
=============================================================================
