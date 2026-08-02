from cds_text_sync.analyze.file_directives import (
    directive_info,
    ignored_rules,
    is_ignored,
)


def test_file_directive_supports_multiple_rules_and_reason():
    text = "// cts:ignore-file CTS0001, CTS0002 -- legacy module\nPROGRAM Main"
    rules = ignored_rules(text)
    assert rules == {"CTS0001", "CTS0002"}
    assert is_ignored("CTS0001", rules)
    assert not is_ignored("CTS0004", rules)


def test_file_directive_supports_block_comments_and_wildcard():
    rules = ignored_rules("(* cts:ignore-file * -- generated *)\nPROGRAM Main")
    assert rules == {"*"}
    assert is_ignored("CTS0004", rules)


def test_normal_comment_is_not_a_directive():
    assert not ignored_rules("// cts:ignore-file CTS0001 in documentation")


def test_directive_info_normalizes_case_and_reports_bad_reason():
    rules, issues = directive_info("// cts:ignore-file cts0001 -- legacy\n")
    assert rules == frozenset({"CTS0001"})
    assert issues == ()

    _, issues = directive_info("// cts:ignore-file CTS0001\n")
    assert issues[0][0] == "directive-missing-reason"


def test_directive_info_accepts_em_dash_but_reports_portability_hint():
    rules, issues = directive_info("// cts:ignore-file CTS0001 — legacy\n")
    assert rules == frozenset({"CTS0001"})
    assert issues[0][0] == "directive-em-dash"
