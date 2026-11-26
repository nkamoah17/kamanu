"""Own tests for kamanu.lint: forms the seed specs do not exercise."""
import pytest

from kamanu.lint import check, strip_comments

SAFE = "SPECIFICATION Spec\nINVARIANTS TypeOK\n"
LIVE = "SPECIFICATION Spec\nPROPERTIES Live\n"


def spec(next_body, extra="", tail="Spec == Init /\\ [][Next]_vars"):
    return f"""---- MODULE M ----
CONSTANT Flag, Other
VARIABLES x, y
vars == <<x, y>>
Init == x = 0 /\\ y = 0
Move == x' = x + 1 /\\ y' = y
{extra}
Next == {next_body}
{tail}
====
"""


@pytest.mark.parametrize("next_body,extra", [
    ("Move \\/ UNCHANGED vars", ""),
    ("Move \\/ UNCHANGED <<x, y>>", ""),
    ("Move \\/ UNCHANGED <<y, x>>", ""),
    ("Move \\/ (UNCHANGED x /\\ UNCHANGED y)", ""),
    ("Move \\/ Idle", "Idle == UNCHANGED vars"),
    ("Move \\/ Busy", "Stay == UNCHANGED vars\nBusy == Flag /\\ Stay"),
    ("Move \\/ Busy", "On == Flag /\\ Other\nBusy == On /\\ UNCHANGED vars"),
    ("Move \\/ Busy(TRUE)", "Busy(c) == c /\\ UNCHANGED vars"),
    ("Move \\/ (\\E i \\in {1, 2} : UNCHANGED vars)", ""),
    ("Move \\/ (\\E i \\in {1, 2} : i = 1 /\\ UNCHANGED vars)", ""),
    ("Move \\/ (IF Flag THEN UNCHANGED vars ELSE Move)", ""),
    ("Move \\/ (CASE Flag -> UNCHANGED vars [] OTHER -> Move)", ""),
    ("Move \\/ (LET s == vars IN UNCHANGED s)", ""),
    ("Move \\/ (~Off /\\ UNCHANGED vars)", "Off == Flag"),
    ("\\/ Move\n        \\/ /\\ Flag\n           /\\ UNCHANGED vars", ""),
    ("/\\ Flag\n        /\\ \\/ Move\n           \\/ UNCHANGED vars", ""),
    ("/\\ TRUE\n        /\\ \\/ UNCHANGED vars\n           \\/ Move", ""),
])
def test_l1_flags_always_enabled_stutter(next_body, extra):
    assert check(spec(next_body, extra), SAFE) == {"L1"}


@pytest.mark.parametrize("next_body,extra", [
    ("Move", ""),
    ("Move \\/ (x = 3 /\\ UNCHANGED vars)", ""),
    ("Move \\/ (Done /\\ UNCHANGED vars)", "Done == x = 3"),
    ("Move \\/ (Done /\\ UNCHANGED vars)", "Done == Deep\nDeep == y = 3"),
    ("Move \\/ Busy(x = 3)", "Busy(c) == c /\\ UNCHANGED vars"),
    ("Move \\/ (UNCHANGED x /\\ y' = 1)", ""),
    ("Move \\/ UNCHANGED x", ""),
    ("Move \\/ UNCHANGED <<x>>", ""),
    ("Move \\/ (\\E i \\in {x} : UNCHANGED vars)", ""),
    ("Move \\/ (\\E i \\in {1, 2} : x = i /\\ UNCHANGED vars)", ""),
    ("Move \\/ (IF x = 3 THEN UNCHANGED vars ELSE Move)", ""),
    ("Move \\/ (CASE x = 3 -> UNCHANGED vars [] OTHER -> Move)", ""),
    ("Move \\/ (ENABLED Move /\\ UNCHANGED vars)", ""),
    ("Move \\/ (Imported /\\ UNCHANGED vars)", ""),
    ("/\\ x = 3\n        /\\ \\/ Move\n           \\/ UNCHANGED vars", ""),
    ("\\/ Move\n        \\/ /\\ x = 3\n           /\\ \\/ UNCHANGED vars\n              \\/ Move", ""),
    ("Move \\/ (~Done /\\ UNCHANGED vars)", "Done == x = 3"),
    ("Move \\/ (x = 3 /\\ \\E i \\in {1} : Move \\/ UNCHANGED vars)", ""),
    ("Move \\/ (x = 0 => Move \\/ UNCHANGED vars)", ""),
])
def test_l1_accepts_guarded_stutter(next_body, extra):
    assert check(spec(next_body, extra), SAFE) == set()


def test_l1_ignores_a_stutter_outside_the_next_action():
    assert check(spec("Move", "Unused == UNCHANGED vars"), SAFE) == set()


def test_l1_ignores_commented_stutter():
    assert check(spec("Move \\* \\/ UNCHANGED vars"), SAFE) == set()
    assert check(spec("Move (* (* nested *) \\/ UNCHANGED vars *)"), SAFE) == set()


def test_l1_uses_the_next_named_by_the_spec():
    tla = spec("Move", "Bad == Move \\/ UNCHANGED vars", "Spec == Init /\\ [][Bad]_vars")
    assert check(tla, SAFE) == {"L1"}


def test_l1_inline_action_and_tuple_subscript():
    tla = spec("Move", "", "Spec == Init /\\ [][Move \\/ UNCHANGED vars]_<<x, y>>")
    assert check(tla, SAFE) == {"L1"}


def test_l1_variables_declared_elsewhere_come_from_the_subscript():
    tla = """---- MODULE E ----
EXTENDS K
VARIABLE z
all == <<kv, z>>
Next == Step \\/ UNCHANGED <<z>>
Spec == Init /\\ [][Next]_all
====
"""
    assert check(tla, SAFE) == set()
    assert check(tla.replace("UNCHANGED <<z>>", "UNCHANGED all"), SAFE) == {"L1"}


def test_l1_opaque_subscript_name():
    tla = "---- MODULE E ----\nEXTENDS K\nNext == Step \\/ UNCHANGED kv\nSpec == I /\\ [][Next]_kv\n====\n"
    assert check(tla, SAFE) == {"L1"}


def test_l1_next_and_init_form_of_the_cfg():
    assert check(spec("Move \\/ UNCHANGED vars"), "INIT Init\nNEXT Next\n") == {"L1"}


def test_text_after_the_module_end_is_ignored():
    assert check(spec("Move") + "Next == UNCHANGED vars\n", SAFE) == set()


def test_strings_do_not_open_comments():
    tla = spec('Move \\/ (Label = "(*" /\\ UNCHANGED vars)', 'Label == "(*"')
    assert check(tla, SAFE) == {"L1"}


def test_recursive_definitions_terminate():
    assert check(spec("Move \\/ Loop", "Loop == Loop"), SAFE) == set()


@pytest.mark.parametrize("line", ["ASSUME x", "CONSTANT F = WF_vars", "PROBE SF_vars(A)"])
def test_l2(line):
    assert "L2" in check(spec("Move"), SAFE + line + "\n")


@pytest.mark.parametrize("line", ["\\* WF_vars(Move)", "(* ASSUME x *)", 'CONSTANT F = "WF_x"',
                                  "CONSTANT NOT_WF_x = 1"])
def test_l2_needs_real_cfg_text(line):
    assert "L2" not in check(spec("Move"), SAFE + line + "\n")


@pytest.mark.parametrize("word", ["PROPERTY", "PROPERTIES"])
def test_l3_either_spelling(word):
    fair = spec("Move", tail="Spec == Init /\\ [][Next]_vars /\\ WF_vars(Next)")
    assert check(fair, f"SPECIFICATION Spec\n{word} Live\nSYMMETRY P\n") == {"L3"}


def test_l3_needs_a_property():
    assert check(spec("Move"), SAFE + "SYMMETRY P\n") == set()


@pytest.mark.parametrize("cfg,want", [
    ("INVARIANT TypeOK", set()),
    ("INVARIANTS\n  TypeOK\n  Safe", set()),
    ("INVARIANT Safe\n  TypeOK", set()),
    ("INVARIANT Safe", {"L4"}),
    ("INVARIANT NotTypeOK", {"L4"}),
    ("INVARIANT TypeOK\nINVARIANT Safe", {"L4"}),
    ("\\* INVARIANT TypeOK\nINVARIANT Safe", {"L4"}),
])
def test_l4(cfg, want):
    assert check(spec("Move"), "SPECIFICATION Spec\n" + cfg + "\n") == want


def test_no_invariants_is_not_l4():
    assert check(spec("Move"), "SPECIFICATION Spec\n") == set()


def test_l5():
    fair = spec("Move", tail="Spec == Init /\\ [][Next]_vars /\\ SF_vars(Next)")
    assert check(fair, "SPECIFICATION Spec\nINVARIANT TypeOK\nPROPERTY Live\n") == {"L5"}


@pytest.mark.parametrize("word", ["CONSTRAINT", "CONSTRAINTS", "ACTION_CONSTRAINT",
                                  "ACTION_CONSTRAINTS"])
def test_l6_every_spelling(word):
    assert check(spec("Move"), SAFE + f"{word} Bound\n") == {"L6"}


def test_cfg_keywords_in_comments_and_strings_do_not_count():
    cfg = SAFE + '\\* CONSTRAINT Bound\n(* SYMMETRY P *)\nCONSTANT F = "PROPERTY"\n'
    assert check(spec("Move"), cfg) == set()


def test_l7_no_fairness():
    assert check(spec("Move"), LIVE) == {"L7"}


def test_l7_unused_fairness_definition_does_not_count():
    assert check(spec("Move", "Fair == WF_vars(Move)"), LIVE) == {"L7"}


def test_l7_fairness_in_a_comment_does_not_count():
    assert check(spec("Move", tail="Spec == Init /\\ [][Next]_vars \\* /\\ WF_vars(Next)"),
                 LIVE) == {"L7"}


@pytest.mark.parametrize("tail,extra", [
    ("Spec == Init /\\ [][Next]_vars /\\ WF_vars(Next)", ""),
    ("Spec == Init /\\ [][Next]_vars /\\ SF_vars(Next)", ""),
    ("Spec == Init /\\ [][Next]_vars /\\ WF_<<x, y>>(Next)", ""),
    ("Spec == Init /\\ [][Next]_vars /\\ Fair", "Fair == WF_vars(Move)"),
    ("Spec == Init /\\ [][Next]_vars /\\ Fair", "Fair == Deep\nDeep == WF_vars(Move)"),
    ("Spec == Init /\\ [][Next]_vars /\\ \\A i \\in {1} : WF_vars(Move)", ""),
])
def test_l7_finds_fairness(tail, extra):
    assert check(spec("Move", extra, tail), LIVE) == set()


def test_l7_stays_quiet_when_the_spec_is_defined_elsewhere():
    tla = "---- MODULE MC ----\nEXTENDS Task\nGoal == TRUE\n====\n"
    assert check(tla, LIVE) == set()


def test_l7_cfg_without_a_specification():
    assert check(spec("Move"), "INIT Init\nNEXT Next\nPROPERTY Live\n") == {"L7"}


def test_strip_comments_handles_nesting():
    assert strip_comments("a (* b (* c *) d *) e").split() == ["a", "e"]


def test_strip_comments_keeps_columns_and_lines():
    text = 'a (* b\nc *) d \\* e\n"\\* f"'
    clean = strip_comments(text)
    assert clean.splitlines() == ["a     ", "     d     ", '"\\* f"']
    assert len(clean) == len(text)
