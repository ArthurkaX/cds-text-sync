from types import SimpleNamespace

from cds_static_analyzer.rules import CTS0007_indentation as indentation


def test_indentation_rule_ignores_section_line_mismatch(monkeypatch):
    """A malformed section must not crash the complete analysis run."""

    class MismatchedSection:
        text = "x := 1;"

        @staticmethod
        def lines():
            yield 1, 0, "x := 1;"
            yield 2, 8, "stale parser line"

    monkeypatch.setattr(indentation, "body", lambda _unit: MismatchedSection())
    unit = SimpleNamespace(implementation="x := 1;")
    context = SimpleNamespace(capability=lambda _capability: None)

    assert list(indentation.check(unit, context)) == []
