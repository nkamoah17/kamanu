/-
  The driver of tests/test_lean_kernel.py: run `ksuccs` (Kamanu/KernelExec.lean, proved equal
  to `KStep` by `mem_ksuccs`) on the states of standard input. Run as
  `lake env lean --run tests/DiffKernel.lean` in lean/.

  Numbers separated by spaces, one line each:
    C maxReq maxFails clean ambiguous reconcile reflexive deny atomic lag session policy cap
      nTemplates (amt key)..          the configuration of the states that follow
    S fails nSlots (amt key st eff recd).. nHist (kind id amt key)..          a state
  Booleans are 0 and 1. deny is 0 for none, else 1 + the kind. Kinds, statuses and policies
  are numbered by the functions below, in README's order. Each S line is answered by one line:
  the states of `ksuccs`, the state itself included, in the form above without the S,
  separated by ';'. A line the driver cannot read is answered by ERR.
-/
import Kamanu
open Kamanu

namespace DiffKernel

def kinds : List Kind := [.request, .deny, .response, .error, .refund, .confirm]
def statuses : List Status := [.pending, .admitted, .running, .done, .failed, .denied]

def ofBool (b : Bool) : Nat := if b then 1 else 0
def toBool : Nat → Option Bool
  | 0 => some false
  | 1 => some true
  | _ => none

structure Config where
  H : Harness
  ts : List Req
  p : Profile
  policy : Nat
  cap : Nat

abbrev P (α : Type) := StateT (List Nat) Option α

def nat : P Nat := fun
  | x :: xs => some (x, xs)
  | [] => none

def lift {α : Type} (o : Option α) : P α := fun xs => o.map (·, xs)
def bool : P Bool := do lift (toBool (← nat))

def many {α : Type} (f : P α) : P (List α) := do
  let k ← nat
  (List.range k).mapM fun _ => f

def req : P Req := do return ⟨← nat, ← nat⟩
def slot : P Slot := do
  let rq ← req
  let st ← lift (statuses[← nat]?)
  return ⟨rq, st, ← bool, ← bool⟩
def event : P Event := do
  let kd ← lift (kinds[← nat]?)
  return ⟨kd, ← nat, ← nat, ← nat⟩

def denyKind : P (Option Kind) := do
  match ← nat with
  | 0 => return none
  | d + 1 => return some (← lift kinds[d]?)

def config : P Config := do
  let maxReq ← nat
  let maxFails ← nat
  let clean ← bool
  let ambiguous ← bool
  let reconcile ← bool
  let reflexive ← bool
  let denyRecord ← denyKind
  let atomic ← bool
  let lag ← nat
  let session ← bool
  let policy ← nat
  let cap ← nat
  let ts ← many req
  return { H := ⟨fun t => t ∈ ts, maxReq, maxFails, clean, ambiguous, reconcile⟩, ts := ts,
           p := ⟨reflexive, denyRecord, atomic, lag, fun k => if session then k else 0⟩,
           policy := policy, cap := cap }

def state : P KState := do
  let fails ← nat
  let slots ← many slot
  return ⟨← many event, slots, fails⟩

def put (xs : List Nat) : String := " ".intercalate (xs.map toString)

def showState (σ : KState) : String :=
  put ([σ.fails, σ.slots.length]
    ++ σ.slots.flatMap (fun s => [s.rq.amt, s.rq.key, statuses.idxOf s.st, ofBool s.eff, ofBool s.recd])
    ++ [σ.hist.length]
    ++ σ.hist.flatMap (fun e => [kinds.idxOf e.kind, e.id, e.amt, e.key]))

def run (c : Config) (σ : KState) : Option (List KState) :=
  match c.policy with
  | 0 => some (ksuccs c.H c.ts c.p (pRespBasis c.cap) σ)
  | 1 => some (ksuccs c.H c.ts c.p (pReqBasis c.cap) σ)
  | 2 => some (ksuccs c.H c.ts c.p (pReqBasisNR c.cap) σ)
  | 3 => some (ksuccs c.H c.ts c.p (pRefundOnError c.cap) σ)
  | 4 => some (ksuccs c.H c.ts c.p (pRefundOnReconcile c.cap) σ)
  | _ => none

/-- All of a line read by `f`, or nothing. -/
def whole {α : Type} (f : P α) (words : List String) : Option α := do
  let xs ← words.mapM String.toNat?
  match f xs with
  | some (a, []) => some a
  | _ => none

partial def loop (inp out : IO.FS.Stream) (c : Option Config) : IO Unit := do
  let line ← inp.getLine
  if line.isEmpty then
    out.flush
    return ()
  match line.trimAscii.toString.splitOn " " with
  | "C" :: words => loop inp out (whole config words)
  | "S" :: words =>
    match c, whole state words with
    | some c, some σ =>
      match run c σ with
      | some ts => out.putStrLn (";".intercalate (ts.map showState))
      | none => out.putStrLn "ERR"
    | _, _ => out.putStrLn "ERR"
    loop inp out c
  | _ =>
    out.putStrLn "ERR"
    loop inp out c

end DiffKernel

def main : IO Unit := do
  DiffKernel.loop (← IO.getStdin) (← IO.getStdout) none
