"""
test_analyze_config.py - cts-analyze.toml parsing, overrides, path scopes.
"""

import pytest

from cds_static_analyzer.config import (
    ConfigError,
    _glob_match,
    load_config,
)


def _write_config(tmp_path, text):
    path = tmp_path / "cts-analyze.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_defaults_without_config(tmp_path):
    config = load_config(str(tmp_path / "missing.toml"))
    assert config.fail_on == "suspicious"
    assert config.incomplete == "warn"
    assert config.enabled_for("CTS0034") is False
    assert config.enabled_for("CTS0001") is True


def test_full_config(tmp_path):
    path = _write_config(
        tmp_path,
        "\n".join(
            [
                "[analyze]",
                'fail_on = "danger"',
                'incomplete = "error"',
                "",
                "[rules.CTS0001]",
                "enabled = false",
                "",
                "[rules.CTS0004]",
                'severity = "danger"',
                "",
                "[[rule_scope]]",
                'path = "POUs/Generated/**"',
                "enabled = false",
                "",
                "[[rule_scope]]",
                'path = "POUs/Sim/**"',
                'exclude = ["CTS0002"]',
            ]
        ),
    )
    config = load_config(path)
    assert config.fail_on == "danger"
    assert config.incomplete == "error"
    assert config.enabled_for("CTS0001") is False
    assert config.enabled_for("CTS0002") is True
    assert config.severity_for("CTS0004", "style") == "danger"
    assert config.path_excluded("POUs/Generated/Foo.st") is True
    assert config.path_excluded("POUs/Real/Foo.st") is False
    assert "CTS0002" in config.rules_excluded_for("POUs/Sim/Sim.st")
    assert "CTS0001" not in config.rules_excluded_for("POUs/Sim/Sim.st")


def test_bad_fail_on(tmp_path):
    path = _write_config(tmp_path, '[analyze]\nfail_on = "catastrophic"\n')
    with pytest.raises(ConfigError):
        load_config(path)


def test_bad_incomplete(tmp_path):
    path = _write_config(tmp_path, '[analyze]\nincomplete = "sometimes"\n')
    with pytest.raises(ConfigError):
        load_config(path)


def test_bad_severity_override(tmp_path):
    path = _write_config(tmp_path, '[rules.CTS0001]\nseverity = "loud"\n')
    with pytest.raises(ConfigError):
        load_config(path)


def test_rule_ids_are_case_normalized_and_unknown_ids_rejected(tmp_path):
    path = _write_config(tmp_path, '[rules.cts0001]\nenabled = false\n')
    config = load_config(path)
    assert config.enabled_for("CTS0001") is False

    path = _write_config(tmp_path, '[rules.CTS9999]\nenabled = false\n')
    with pytest.raises(ConfigError, match="unknown rule"):
        load_config(path)


def test_malformed_toml(tmp_path):
    path = _write_config(tmp_path, "[analyze\nbroken =")
    with pytest.raises(ConfigError):
        load_config(path)


def test_rule_scope_needs_path(tmp_path):
    path = _write_config(tmp_path, "[[rule_scope]]\nenabled = false\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_glob_semantics():
    # ** crosses directories; * does not.
    assert _glob_match("POUs/Generated/**", "POUs/Generated/A.st")
    assert _glob_match("POUs/Generated/**", "POUs/Generated/Deep/B.st")
    assert not _glob_match("POUs/*.st", "POUs/Deep/B.st")


def test_rule_options_parsed_and_available(tmp_path):
    path = _write_config(
        tmp_path,
        "\n".join(
            [
                "[rules.CTS0001]",
                "options.min_tokens = 6",
                "",
                "[rules.CTS0004]",
                "options.min_occurrences = 3",
                "options.max_trivial_integer = 20",
            ]
        ),
    )
    config = load_config(path)
    assert config.options_for("CTS0001") == {"min_tokens": 6}
    assert config.options_for("CTS0004") == {"min_occurrences": 3, "max_trivial_integer": 20}
    assert config.options_for("CTS0002") == {}


def test_unknown_rule_option_not_rejected_at_load(tmp_path):
    """A typo in an option name must not fail config load: typos are
    surfaced per-run as ``rule-option`` Diagnostics, never config errors."""
    path = _write_config(
        tmp_path,
        "\n".join(
            [
                "[rules.CTS0001]",
                "options.typo_option = 5",
            ]
        ),
    )
    config = load_config(path)
    # Unknown key is stored as-is; validation happens at dispatch time.
    assert "typo_option" in config.options_for("CTS0001")
