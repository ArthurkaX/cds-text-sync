"""Fingerprint stability contract tests."""

from cds_static_analyzer.fingerprint import fingerprint


def test_same_fingerprint_for_identical_input():
    assert fingerprint("CTS0001", "POUs/Main.st#Main", "x := 1;", "x := 1;") == fingerprint("CTS0001", "POUs/Main.st#Main", "x := 1;", "x := 1;")


def test_line_insertion_does_not_change_fingerprint():
    assert fingerprint("CTS0002", "POUs/Main.st#Main", "nTarget", "nTarget : INT") == fingerprint("CTS0002", "POUs/Main.st#Main", "nTarget", "nTarget : INT")


def test_rule_id_changes_fingerprint():
    assert fingerprint("CTS0001", "POUs/Main.st#Main", "x", "x") != fingerprint("CTS0002", "POUs/Main.st#Main", "x", "x")


def test_unit_id_changes_fingerprint():
    assert fingerprint("CTS0001", "POUs/A.st#A", "x", "x") != fingerprint("CTS0001", "POUs/B.st#B", "x", "x")


def test_anchor_changes_fingerprint():
    assert fingerprint("CTS0001", "POUs/Main.st#Main", "y := 1;", "y := 1;") != fingerprint("CTS0001", "POUs/Main.st#Main", "z := 2;", "z := 2;")


def test_context_whitespace_is_normalised():
    assert fingerprint("CTS0001", "U", "y := 1;", "  y :=   1 ;") == fingerprint("CTS0001", "U", "y := 1;", "y := 1 ;")


def test_context_case_is_normalised():
    assert fingerprint("CTS0001", "U", "x", "X : INT") == fingerprint("CTS0001", "U", "x", "x : int")


def test_schema_version_part_of_identity():
    assert fingerprint("CTS0001", "U", "x", "x", schema=1) != fingerprint("CTS0001", "U", "x", "x", schema=2)


def test_first_occurrence_keeps_the_pre_numbering_identity():
    """Numbering duplicates must not move stored baselines.  The literal below
    is the digest of the payload as it was hashed before ``occurrence``
    existed, so occurrence 0 has to reproduce it byte for byte."""
    historic = "cts1:47807893b2862a55b952885c6e0ed044a6e8ea03"
    assert fingerprint("CTS0001", "U", "x", "x") == historic
    assert fingerprint("CTS0001", "U", "x", "x", occurrence=0) == historic


def test_occurrence_distinguishes_exact_duplicates():
    plain = fingerprint("CTS0007", "U", "level:1", "END_IF;")
    second = fingerprint("CTS0007", "U", "level:1", "END_IF;", occurrence=1)
    third = fingerprint("CTS0007", "U", "level:1", "END_IF;", occurrence=2)
    assert len({plain, second, third}) == 3
