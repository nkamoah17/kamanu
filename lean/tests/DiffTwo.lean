/-
  Differential test driver for the two-session caller ledger (T8): reads one (setting, state) per
  line, prints every successor `Kamanu.Two.tnext` lists (the explored machine: R14's steps in each
  session, the shared bound, then `norm2`), or with `N` first the state's own `norm2`.
  tests/test_lean_two.py walks `Machine.successors` and the session swap and compares the sets.

  Input line:  S|N co0..co5 w T refl nmarks marks.. atomic lag clean ambiguous cap namounts amounts..
               inFlight failures shared  then for each session: nslots (amt st).. fails v spent hasLast last
  Output line: '-' or successors separated by ';', each  label amt | session a | session b,
               a session as  nslots (amt st).. fails v spent last('N' when none)
  labels: 0 issue 1 permit 2 deny 3 record 4 succeed 5 failClean 6 failAmbiguous 7 refund 8 confirm
  statuses: 0 P 1 A 2 R 3 FC 4 FM
-/
import Kamanu.TwoExec
open Kamanu Kamanu.Fast Kamanu.Two

def kindOf : Int → Kind
  | 0 => .request | 1 => .deny | 2 => .response | 3 => .error | 4 => .refund | _ => .confirm

def stOf : Int → St
  | 0 => .P | 1 => .A | 2 => .R | 3 => .FC | _ => .FM

def stNum : St → Nat
  | .P => 0 | .A => 1 | .R => 2 | .FC => 3 | .FM => 4

def labelCode : Label → Nat × Nat
  | .issue a => (0, a) | .permit a => (1, a) | .deny a => (2, a) | .record a => (3, a)
  | .succeed a => (4, a) | .failClean a => (5, a) | .failAmbiguous a => (6, a)
  | .refund a => (7, a) | .confirm a => (8, a)

/-- Python's `sorted` on one session's slots: by amount, then the status as its string. -/
def callLt (x y : Call) : Bool :=
  x.amt < y.amt || (x.amt == y.amt && decide (stCode x.st < stCode y.st))

def insertCall (x : Call) : List Call → List Call
  | [] => [x]
  | y :: ys => if callLt y x then y :: insertCall x ys else x :: y :: ys

def sortCalls : List Call → List Call
  | [] => []
  | x :: xs => insertCall x (sortCalls xs)

def showSession (s : MState) : String :=
  let ls := match s.last with
    | some x => toString x
    | none => "N"
  let slots := s.slots.foldl (fun acc c => acc ++ s!" {c.amt} {stNum c.st}") ""
  s!"{s.slots.length}{slots} {s.fails} {s.v} {s.spent} {ls}"

def showState (q : TState) : String := s!"{showSession q.a} | {showSession q.b}"

def showStep (l : Label) (q : TState) : String :=
  let (lc, a) := labelCode l
  s!"{lc} {a} | {showState q}"

/-- One session's state from position `p`; the position after it. -/
def readSession (get : Nat → Int) (p : Nat) : MState × Nat :=
  let n := (get p).toNat
  let slots := (List.range n).map (fun i =>
    ({ amt := (get (p + 1 + 2 * i)).toNat, st := stOf (get (p + 2 + 2 * i)) } : Call))
  let q := p + 1 + 2 * n
  ({ slots := slots, fails := (get q).toNat, v := get (q + 1), spent := (get (q + 2)).toNat,
     last := if get (q + 3) != 0 then some (get (q + 4)) else none }, q + 5)

def runCase (mode : String) (xs : List Int) : Option String := do
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
  let (sa, r) := readSession get (q + 3)
  let (sb, _) := readSession get r
  match amounts with
  | [] => none
  | a0 :: rest =>
    let st : Setting :=
      { co := co, w := get 6, T := get 7, refl := get 8 != 0, marks := marks,
        atomic := get p != 0, lag := get (p + 1) != 0, clean := get (p + 2) != 0,
        ambiguous := get (p + 3) != 0, cap := (get (p + 4)).toNat, amt0 := a0, amts := rest,
        inFlight := (get q).toNat, failures := (get (q + 1)).toNat }
    let shared := get (q + 2) != 0
    let t : TState := ⟨sa, sb⟩
    if mode == "N" then
      some (showState (norm2 st sortCalls t))
    else
      let out := (tnext st shared sortCalls t).map (fun (l, t') => showStep l t')
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
  match tokens line with
  | mode :: rest =>
    match runCase mode (rest.filterMap String.toInt?) with
    | some out => IO.println out
    | none => IO.println "ERR"
  | [] => IO.println "ERR"
  loop h

def main : IO Unit := do
  loop (← IO.getStdin)
