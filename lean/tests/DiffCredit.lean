/-
  Differential test driver for the Credit ledger's explored machine (T8): reads one (configuration,
  state) per line, prints every successor `Kamanu.Credit.cnext` lists.
  tests/test_lean_credit.py records the steps `kamanu.fast.credit.explore` takes and compares the sets.

  Input line:  own creditKind debitKind bound base slack returns reflexive denyRecord atomic lag clean
               ambiguous failures inFlight   nslots (guarded allowed key status).. hb hasLast last y doubt fails
               (kinds as numbers: 0 request 1 deny 2 response 3 error 4 refund 5 confirm; denyRecord -1: none;
                statuses: 0 pending 1 admitted 2 running 3 done 4 failed 5 denied)
  Output line: '-' or successors separated by ';', each
               verb guarded allowed key | nslots (guarded allowed key status).. hb last('N' when none) y doubt fails
  verbs: 0 issue 1 permit 2 deny 3 record 4 succeed 5 failClean 6 failAmbiguous
-/
import Kamanu.CreditExec
open Kamanu Kamanu.Credit

def kindOf : Int → Kind
  | 0 => .request | 1 => .deny | 2 => .response | 3 => .error | 4 => .refund | _ => .confirm

def statusOf : Int → Status
  | 0 => .pending | 1 => .admitted | 2 => .running | 3 => .done | 4 => .failed | _ => .denied

def statusNum : Status → Nat
  | .pending => 0 | .admitted => 1 | .running => 2 | .done => 3 | .failed => 4 | .denied => 5

def verbNum : CVerb → Nat
  | .issue => 0 | .permit => 1 | .deny => 2 | .record => 3 | .succeed => 4 | .failClean => 5
  | .failAmbiguous => 6

def b2n (b : Bool) : Nat := if b then 1 else 0

def showReq (r : CReq) : String := s!"{b2n r.guarded} {b2n r.allowed} {r.key}"

def showState (q : QState) : String :=
  let ls := match q.last with
    | some x => toString x
    | none => "N"
  let slots := q.slots.foldl (fun acc x => acc ++ s!" {showReq x.rq} {statusNum x.st}") ""
  s!"{q.slots.length}{slots} {q.hb} {ls} {q.y} {q.doubt} {q.fails}"

def runCase (xs : List Int) : Option String := do
  let get (i : Nat) : Int := xs.getD i 0
  let c : Cfg :=
    { own := get 0 != 0, creditKind := kindOf (get 1), debitKind := kindOf (get 2), bound := get 3 != 0,
      base := (get 4).toNat, slack := get 5, returns := get 6 != 0, reflexive := get 7 != 0,
      denyRecord := if get 8 < 0 then none else some (kindOf (get 8)), atomic := get 9 != 0,
      lag := (get 10).toNat, clean := get 11 != 0, ambiguous := get 12 != 0,
      failures := (get 13).toNat, inFlight := (get 14).toNat }
  let n := (get 15).toNat
  let slots := (List.range n).map (fun i =>
    ({ rq := ⟨get (16 + 4 * i) != 0, get (17 + 4 * i) != 0, (get (18 + 4 * i)).toNat⟩,
       st := statusOf (get (19 + 4 * i)) } : QSlot))
  let p := 16 + 4 * n
  let q : QState :=
    { slots := slots, hb := get p, last := if get (p + 1) != 0 then some (get (p + 2)) else none,
      y := get (p + 3), doubt := (get (p + 4)).toNat, fails := (get (p + 5)).toNat }
  let out := (cnext c q).map (fun (l, q') => s!"{verbNum l.verb} {showReq l.rq} | {showState q'}")
  some (if out.isEmpty then "-" else ";".intercalate out)

def tokens (s : String) : List String :=
  let step := fun (acc : List String × String) (c : Char) =>
    if c = ' ' ∨ c = '\n' ∨ c = '\r' then
      (if acc.2.isEmpty then acc else (acc.2 :: acc.1, ""))
    else (acc.1, acc.2.push c)
  let r := s.toList.foldl step ([], "")
  (if r.2.isEmpty then r.1 else r.2 :: r.1).reverse

partial def loop (h : IO.FS.Stream) : IO Unit := do
  let line ← h.getLine
  if line.isEmpty then return ()
  match runCase ((tokens line).filterMap String.toInt?) with
  | some out => IO.println out
  | none => IO.println "ERR"
  loop h

def main : IO Unit := do
  loop (← IO.getStdin)
