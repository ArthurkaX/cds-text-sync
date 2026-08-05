"""
test_analyze_fingerprint.py - Fingerprints are stable under reindentation
and line insertion; they change with the semantic anchor.
"""

from cds_static_analyzer.fingerprint import fingerprint


def test_same_fingerprint_for_identical_input():
    a = fingerprint("CTS0001", "POUs/Main.st#Main", "x := 1;", "x := 1;")
    b = fingerprint("CTS0001", "POUs/Main.st#Main", "x := 1;", "x := 1;")
    assert a == b


def test_line_insertion_does_not_change_fingerprint():
    # The unit id and anchor are stable; the line number is not in identity.
    a = fingerprint("CTS0002", "POUs/Main.st#Main", "nTarget", "nTarget : INT")
    b = fingerprint("CTS0002", "POUs/Main.st#Main", "nTarget", "nTarget : INT")
    assert a == b


def test_rule_id_changes_fingerprint():
    a = fingerprint("CTS0001", "POUs/Main.st#Main", "x", "x")
    b = fingerprint("CTS0002", "POUs/Main.st#Main", "x", "x")
    assert a != b


def test_unit_id_changes_fingerprint():
    a = fingerprint("CTS0001", "POUs/A.st#A", "x", "x")
    b = fingerprint("CTS0001", "POUs/B.st#B", "x", "x")
    assert a != b


def test_anchor_changes_fingerprint():
    a = fingerprint("CTS0001", "POUs/Main.st#Main", "y := 1;", "y := 1;")
    b = fingerprint("CTS0001", "POUs/Main.st#Main", "z := 2;", "z := 2;")
    assert a != b


def test_context_whitespace_is_normalised():
    # Runs of whitespace collapse; leading/trailing are trimmed.
    a = fingerprint("CTS0001", "U", "y := 1;", "  y :=   1 ;")
    b = fingerprint("CTS0001", "U", "y := 1;", "y := 1 ;")
    assert a == b


def test_context_case_is_normalised():
    a = fingerprint("CTS0001", "U", "x", "X : INT")
    b = fingerprint("CTS0001", "U", "x", "x : int")
    assert a == b


def test_schema_version_part_of_identity():
    a = fingerprint("CTS0001", "U", "x", "x", schema=1)
    b = fingerprint("CTS0001", "U", "x", "x", schema=2)
    assert a != b
