/-
  Differential test driver: reads one test case per line from stdin, applies the Lean
  `clip`, prints `v last` per line. `tests/diff_norm.py` generates the cases, runs
  `Machine._norm` from kamanu/fast/machine.py on the same inputs and compares.

  Line format (integers, space separated):
    co[request deny response error refund confirm] w T refl nmarks marks.. atomic lag
    clean ambiguous cap namounts amounts.. inFlight failures
    fails v hasLast last nslots (amt st)..
  kinds: 0 request 1 deny 2 response 3 error 4 refund 5 confirm
  statuses: 0 P 1 A 2 R 3 FC 4 FM
-/
import Kamanu.Register
open Kamanu Kamanu.Fast

def kindOf : Int → Kind
  | 0 => .request | 1 => .deny | 2 => .response | 3 => .error | 4 => .refund | _ => .confirm

def stOf : Int → St
  | 0 => .P | 1 => .A | 2 => .R | 3 => .FC | _ => .FM

def runCase (xs : List Int) : Option String := do
  let get (i : Nat) : Int := xs.getD i 0
  let co : Kind → Int := fun k => match k with
    | .request => get 0 | .deny => get 1 | .response => get 2
    | .error => get 3 | .refund => get 4 | .confirm => get 5
  let w := get 6
  let T := get 7
  let refl := get 8 != 0
  let nm := (get 9).toNat
  let marks := (List.range nm).map (fun i => kindOf (get (10 + i)))
  let p := 10 + nm
  let atomic := get p != 0
  let lag := get (p + 1) != 0
  let clean := get (p + 2) != 0
  let amb := get (p + 3) != 0
  let cap := (get (p + 4)).toNat
  let na := (get (p + 5)).toNat
  let amounts := (List.range na).map (fun i => (get (p + 6 + i)).toNat)
  let q := p + 6 + na
  let inF := (get q).toNat
  let fl := (get (q + 1)).toNat
  let fails := (get (q + 2)).toNat
  let v := get (q + 3)
  let last : Option Int := if get (q + 4) != 0 then some (get (q + 5)) else none
  let ns := (get (q + 6)).toNat
  let slots := (List.range ns).map (fun i =>
    ({ amt := (get (q + 7 + 2 * i)).toNat, st := stOf (get (q + 8 + 2 * i)) } : Call))
  match amounts with
  | [] => none
  | a0 :: rest =>
    let st : Setting :=
      { co := co, w := w, T := T, refl := refl, marks := marks, atomic := atomic, lag := lag,
        clean := clean, ambiguous := amb, cap := cap, amt0 := a0, amts := rest,
        inFlight := inF, failures := fl }
    let s : MState := { slots := slots, fails := fails, v := v, spent := 0, last := last }
    let t := clip st s
    let ls := match t.last with
      | some l => toString l
      | none => "N"
    some s!"{t.v} {ls}"

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
  let xs := (tokens line).filterMap String.toInt?
  match runCase xs with
  | some out => IO.println out
  | none => IO.println "ERR"
  loop h

def main : IO Unit := do
  loop (← IO.getStdin)
