/-
  Differential test driver for the steps: reads one (setting, state) per line, prints
  every successor of the Lean machine after the explorer's clip and spent cap.
  `tests/diff_steps.py` walks `Machine.successors` and compares the two sets.

  Input line: as tests/DiffNorm.lean, with `spent` inserted after `v`:
    ... inFlight failures fails v spent hasLast last nslots (amt st)..
  Output line: successors separated by ';', each
    label amt fails v spent last nslots (amt st)..
  labels: 0 issue 1 permit 2 deny 3 record 4 succeed 5 failClean 6 failAmbiguous
          7 refund 8 confirm
-/
import Kamanu.RegisterExec
open Kamanu Kamanu.Fast

def kindOf : Int → Kind
  | 0 => .request | 1 => .deny | 2 => .response | 3 => .error | 4 => .refund | _ => .confirm

def stOf : Int → St
  | 0 => .P | 1 => .A | 2 => .R | 3 => .FC | _ => .FM

def stCode : St → Nat
  | .P => 0 | .A => 1 | .R => 2 | .FC => 3 | .FM => 4

def labelCode : Label → Nat × Nat
  | .issue a => (0, a) | .permit a => (1, a) | .deny a => (2, a) | .record a => (3, a)
  | .succeed a => (4, a) | .failClean a => (5, a) | .failAmbiguous a => (6, a)
  | .refund a => (7, a) | .confirm a => (8, a)

def showState (l : Label) (t : MState) : String :=
  let (lc, a) := labelCode l
  let ls := match t.last with
    | some x => toString x
    | none => "N"
  let slots := t.slots.foldl (fun acc c => acc ++ s!" {c.amt} {stCode c.st}") ""
  s!"{lc} {a} {t.fails} {t.v} {t.spent} {ls} {t.slots.length}{slots}"

def runCase (xs : List Int) : Option String := do
  let get (i : Nat) : Int := xs.getD i 0
  let co : Kind → Int := fun k => match k with
    | .request => get 0 | .deny => get 1 | .response => get 2
    | .error => get 3 | .refund => get 4 | .confirm => get 5
  let nm := (get 9).toNat
  let marks := (List.range nm).map (fun i => kindOf (get (10 + i)))
  let p := 10 + nm
  let na := (get (p + 5)).toNat
  let amounts := (List.range na).map (fun i => (get (p + 6 + i)).toNat)
  let q := p + 6 + na
  let last : Option Int := if get (q + 5) != 0 then some (get (q + 6)) else none
  let ns := (get (q + 7)).toNat
  let slots := (List.range ns).map (fun i =>
    ({ amt := (get (q + 8 + 2 * i)).toNat, st := stOf (get (q + 9 + 2 * i)) } : Call))
  match amounts with
  | [] => none
  | a0 :: rest =>
    let st : Setting :=
      { co := co, w := get 6, T := get 7, refl := get 8 != 0, marks := marks,
        atomic := get p != 0, lag := get (p + 1) != 0, clean := get (p + 2) != 0,
        ambiguous := get (p + 3) != 0, cap := (get (p + 4)).toNat, amt0 := a0, amts := rest,
        inFlight := (get q).toNat, failures := (get (q + 1)).toNat }
    let s : MState :=
      { slots := slots, fails := (get (q + 2)).toNat, v := get (q + 3),
        spent := (get (q + 4)).toNat, last := last }
    let out := (succs st s).map (fun (l, t) => showState l (normFull st id t))
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
  let xs := (tokens line).filterMap String.toInt?
  match runCase xs with
  | some out => IO.println out
  | none => IO.println "ERR"
  loop h

def main : IO Unit := do
  loop (← IO.getStdin)
