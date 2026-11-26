/-
  Differential test driver for the budget key's cell (X3): reads one (cell, state) per line and prints
  every successor `Kamanu.Budget.bnext` lists, the stutter included. tests/test_lean_budget.py walks
  kamanu/fast/budget.py's KeySet on the same cell and compares the successor sets.

  Input line:   maxReq maxFails clean ambiguous reconcile cap ntemplates (req)..
                nslots (req st eff recd).. nhist (kind id req).. fails
  a req:        amt session tenant principal purpose window
  Output line:  successors separated by ';', each  nslots (req st eff recd).. nhist (kind id req).. fails
  statuses: 0 pending 1 admitted 2 running 3 done 4 failed 5 denied
  kinds:    0 request 1 deny 2 response 3 error 4 refund 5 confirm
  The cap is one number for every key, as KeySet's Cap is.
-/
import Kamanu.BudgetExec
open Kamanu Kamanu.Budget

def kindOf : Nat → Kind
  | 0 => .request | 1 => .deny | 2 => .response | 3 => .error | 4 => .refund | _ => .confirm

def kindNum : Kind → Nat
  | .request => 0 | .deny => 1 | .response => 2 | .error => 3 | .refund => 4 | .confirm => 5

def stOf : Nat → Status
  | 0 => .pending | 1 => .admitted | 2 => .running | 3 => .done | 4 => .failed | _ => .denied

def stNum : Status → Nat
  | .pending => 0 | .admitted => 1 | .running => 2 | .done => 3 | .failed => 4 | .denied => 5

def b2n (b : Bool) : Nat := if b then 1 else 0

def showReq (r : BReq) : String :=
  s!"{r.amt} {r.session.id} {r.key.tenant.id} {r.key.principal.id} {r.key.purpose.id} {r.key.window.id}"

def showState (σ : BState) : String :=
  let slots := σ.slots.foldl (fun acc s => acc ++ s!" {showReq s.rq} {stNum s.st} {b2n s.eff} {b2n s.recd}") ""
  let hist := σ.hist.foldl (fun acc e => acc ++ s!" {kindNum e.kind} {e.id} {showReq e.rq}") ""
  s!"{σ.slots.length}{slots} {σ.hist.length}{hist} {σ.fails}"

def readReq (get : Nat → Nat) (p : Nat) : BReq :=
  ⟨get p, ⟨get (p + 1)⟩, ⟨⟨get (p + 2)⟩, ⟨get (p + 3)⟩, ⟨get (p + 4)⟩, ⟨get (p + 5)⟩⟩⟩

def runCase (xs : Array Nat) : String := Id.run do
  let get (i : Nat) : Nat := xs.getD i 0
  let cap := get 5
  let nt := get 6
  let templates := (List.range nt).map (fun j => readReq get (7 + 6 * j))
  let p := 7 + 6 * nt
  let ns := get p
  let slots := (List.range ns).map (fun j =>
    let q := p + 1 + 9 * j
    (⟨readReq get q, stOf (get (q + 6)), get (q + 7) != 0, get (q + 8) != 0⟩ : BSlot))
  let h := p + 1 + 9 * ns
  let nh := get h
  let hist := (List.range nh).map (fun j =>
    let q := h + 1 + 8 * j
    (⟨kindOf (get q), get (q + 1), readReq get (q + 2)⟩ : BEvent))
  let fails := get (h + 1 + 8 * nh)
  let c : BCell := ⟨templates, get 0, get 1, get 2 != 0, get 3 != 0, get 4 != 0, fun _ => cap⟩
  let σ : BState := ⟨hist, slots, fails⟩
  return ";".intercalate ((bnext c σ).map showState)

def tokens (s : String) : Array Nat := Id.run do
  let mut out : Array Nat := #[]
  let mut cur : Nat := 0
  let mut any := false
  for ch in s.toList do
    if ch.isDigit then
      cur := cur * 10 + (ch.toNat - '0'.toNat)
      any := true
    else if any then
      out := out.push cur
      cur := 0
      any := false
  if any then out := out.push cur
  return out

partial def loop (h : IO.FS.Stream) (o : IO.FS.Stream) : IO Unit := do
  let line ← h.getLine
  if line.isEmpty then return ()
  o.putStrLn (runCase (tokens line))
  loop h o

def main : IO Unit := do
  loop (← IO.getStdin) (← IO.getStdout)
