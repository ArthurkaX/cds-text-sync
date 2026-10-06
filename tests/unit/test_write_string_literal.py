# -*- coding: utf-8 -*-
"""
test_write_string_literal.py — writing a STRING variable.

Live, ``cts write GVL.sName hello`` answered "'hello' is not a literal."  A
STRING/WSTRING value has to be an ST string literal ("'hello'"), and the
declared type of the variable is not reachable from the online API.

The fix does not guess the type: CODESYS itself says "is not a literal", and
only that answer triggers a retry with the quoted form.  A bare value for a
numeric variable still fails with its own error, and the reply says when the
literal was used -- a silent rewrite would be worse than the failure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)


@pytest.fixture(scope="module")
def helpers():
    spec = importlib.util.spec_from_file_location(
        "ide_online_helpers", BRIDGE_DIR / "ide_online_helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _OnlineApp(object):
    is_logged_in = True


class _Recorder(object):
    """The online API as the write path sees it: prepared values in order."""

    def __init__(self, fail=()):
        self.prepared = []
        self.writes = 0
        #: value -> exception to raise from set_prepared_value
        self.fail = dict(fail)

    def __call__(self, online_app, names, *args):
        name = names[0]
        if name == "set_prepared_value":
            value = args[1]
            self.prepared.append(value)
            if value in self.fail:
                raise self.fail[value]
            return None
        if name == "write_prepared_values":
            self.writes += 1
            return None
        raise AssertionError("unexpected call: {0}".format(name))


@pytest.fixture
def recorder(helpers, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(helpers, "require_online_session", lambda project: _OnlineApp())
    monkeypatch.setattr(helpers, "_require_existing_login", lambda app: True)
    monkeypatch.setattr(helpers, "release_watches", lambda app: None)
    monkeypatch.setattr(helpers, "_call_online_app", rec)
    return rec


NOT_A_LITERAL = ValueError("'hello' is not a literal.")


def test_a_bare_string_is_retried_as_an_st_literal(helpers, recorder):
    recorder.fail["hello"] = NOT_A_LITERAL

    result = helpers.write_variable_impl(object(), "GVL.sName", "hello")

    assert recorder.prepared == ["hello", "'hello'"]
    assert result["written"] is True
    assert result["value"] == "'hello'"
    # The rewrite is said out loud: silently quoting would hide a typo.
    assert result["string_literal"] is True
    assert "'hello'" in result["note"]


def test_an_already_quoted_value_is_not_quoted_again(helpers, recorder):
    result = helpers.write_variable_impl(object(), "GVL.sName", "'hello'")

    assert recorder.prepared == ["'hello'"]
    assert "string_literal" not in result


def test_a_double_quoted_value_counts_as_a_literal(helpers, recorder):
    result = helpers.write_variable_impl(object(), "GVL.sName", '"hello"')

    assert recorder.prepared == ['"hello"']
    assert "string_literal" not in result


def test_a_non_literal_error_for_a_bare_value_that_is_not_a_string_propagates(
    helpers, recorder
):
    """`cts write GVL.iCount abc` must fail, not become 'abc'."""
    recorder.fail["abc"] = ValueError("Cannot convert 'abc' to INT")
    recorder.fail["'abc'"] = ValueError("'abc' is not a literal.")

    with pytest.raises(ValueError) as excinfo:
        helpers.write_variable_impl(object(), "GVL.iCount", "abc")

    assert "Cannot convert" in str(excinfo.value)


def test_a_failed_retry_says_both_things_failed(helpers, recorder):
    """The user has to know the value was requoted before the real error."""
    recorder.fail["hello"] = NOT_A_LITERAL
    recorder.fail["'hello'"] = ValueError("some other reason")

    with pytest.raises(RuntimeError) as excinfo:
        helpers.write_variable_impl(object(), "GVL.sName", "hello")

    assert "some other reason" in str(excinfo.value)
    assert "'hello'" in str(excinfo.value)
    assert "failed too" in str(excinfo.value)


def test_a_numeric_write_never_sees_a_retry(helpers, recorder):
    result = helpers.write_variable_impl(object(), "GVL.iCount", "42")

    assert recorder.prepared == ["42"]
    assert result["value"] == "42"
    assert "string_literal" not in result


def test_quotes_and_dollar_are_escaped_the_st_way(helpers):
    assert helpers._st_string_literal("don't") == "'don$'t'"
    assert helpers._st_string_literal("a$b") == "'a$$b'"
    assert helpers._st_string_literal("plain") == "'plain'"


def test_the_batch_path_quotes_strings_too(helpers, monkeypatch):
    """A snapshot keeps the bare value it read back; restoring it must work."""
    rec = _Recorder(fail={"hello": NOT_A_LITERAL})
    monkeypatch.setattr(helpers, "require_online_session", lambda project: _OnlineApp())
    monkeypatch.setattr(helpers, "_require_existing_login", lambda app: True)
    monkeypatch.setattr(helpers, "_call_online_app", rec)

    result = helpers.write_variables_impl(
        object(), [{"name": "GVL.sName", "value": "hello"}]
    )

    assert rec.prepared == ["hello", "'hello'"]
    assert result["written"] == 1
    assert result["results"][0]["string_literal"] is True
    assert result["results"][0]["value"] == "'hello'"


def test_the_batch_path_leaves_a_bad_value_failed(helpers, monkeypatch):
    rec = _Recorder(
        fail={
            "abc": ValueError("Cannot convert 'abc' to INT"),
            "'abc'": ValueError("'abc' is not a literal."),
        }
    )
    monkeypatch.setattr(helpers, "require_online_session", lambda project: _OnlineApp())
    monkeypatch.setattr(helpers, "_require_existing_login", lambda app: True)
    monkeypatch.setattr(helpers, "_call_online_app", rec)

    result = helpers.write_variables_impl(
        object(), [{"name": "GVL.iCount", "value": "abc"}]
    )

    assert result["results"][0]["prepared"] is False
    assert "Cannot convert" in result["results"][0]["write_error"]
