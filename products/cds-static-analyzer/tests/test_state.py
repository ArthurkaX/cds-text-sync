"""
test_analyze_state.py - baseline/suppressions read/write, atomicity, expiry.
"""

import datetime
import os

import pytest

from cds_static_analyzer import state as st


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path / ".cts-analyze")


def test_read_missing_files_return_empty(state_dir):
    assert st.read_baseline(state_dir) == ([], 1)
    assert st.read_suppressions(state_dir) == []
    assert st.read_session(state_dir) == {"decisions": []}


def test_baseline_round_trip(state_dir):
    entries = [
        {
            "fingerprint": "cts1:bbb",
            "rule_id": "CTS0002",
            "unit_id": "U",
            "message": "m2",
        },
        {
            "fingerprint": "cts1:aaa",
            "rule_id": "CTS0001",
            "unit_id": "U",
            "message": "m1",
        },
    ]
    st.write_baseline(state_dir, entries)
    loaded, schema = st.read_baseline(state_dir)
    assert schema == 1
    # Sorted by fingerprint, one entry per line.
    assert [e["fingerprint"] for e in loaded] == ["cts1:aaa", "cts1:bbb"]
    text = open(st.baseline_path(state_dir), encoding="utf-8").read()
    assert text.count("\n    {") == 2  # one entry per line
    assert "fingerprint_schema" in text


def test_suppressions_round_trip_and_reason_required(state_dir):
    entries = [
        {
            "fingerprint": "cts1:aaa",
            "rule_id": "CTS0002",
            "unit_id": "U",
            "reason": "read by a method outside this view",
            "until": "",
        }
    ]
    st.write_suppressions(state_dir, entries)
    loaded = st.read_suppressions(state_dir)
    assert loaded[0]["reason"] == "read by a method outside this view"

    # A suppression without a reason is rejected on read.
    st.write_suppressions(
        state_dir,
        [
            {
                "fingerprint": "cts1:bbb",
                "rule_id": "CTS0001",
                "unit_id": "",
                "reason": "",
                "until": "",
            }
        ],
    )
    with pytest.raises(st.StateError):
        st.read_suppressions(state_dir)


def test_expiry(state_dir):
    fresh = {"until": (datetime.date.today() + datetime.timedelta(days=1)).isoformat()}
    past = {"until": "2000-01-01"}
    none = {"until": ""}
    assert not st.is_expired(fresh)
    assert st.is_expired(past)
    assert not st.is_expired(none)


def test_session_round_trip(state_dir):
    decisions = [{"fingerprint": "cts1:aaa", "action": "fix-later", "note": "TICKET-1"}]
    st.write_session(state_dir, decisions)
    assert st.read_session(state_dir)["decisions"] == decisions


def test_atomic_write_leaves_no_tmp_files(state_dir):
    st.write_json_atomic(os.path.join(state_dir, "x.json"), {"a": 1})
    assert not os.path.exists(os.path.join(state_dir, "x.json.tmp"))
    assert os.path.exists(os.path.join(state_dir, "x.json"))


def _seed_baseline(state_dir, schema):
    os.makedirs(state_dir, exist_ok=True)
    path = st.baseline_path(state_dir)
    with open(path, "w", encoding="utf-8") as fh:
        import json

        json.dump(
            {"schema_version": 1, "fingerprint_schema": schema, "entries": []},
            fh,
        )
    return path


def test_validate_baseline_schema_missing_file_is_fine(state_dir):
    st.validate_baseline_schema(state_dir)  # no baseline: no-op


def test_validate_baseline_schema_mismatch_rejected(state_dir):
    _seed_baseline(state_dir, 2)
    with pytest.raises(st.StateError) as exc:
        st.validate_baseline_schema(state_dir)
    message = str(exc.value)
    assert "baseline fingerprint schema 2 is unsupported" in message
    assert "cts analyze baseline update" in message


def test_validate_baseline_schema_missing_field_treated_as_current(state_dir):
    """The explicit field is validated, never inferred from fingerprint
    string prefixes; a baseline without the field predates it (schema 1)."""
    path = _seed_baseline(state_dir, 1)
    st.validate_baseline_schema(state_dir)
    # A baseline whose *entries* carry another schema's fingerprints but
    # whose explicit field is current must still validate.
    with open(path, "w", encoding="utf-8") as fh:
        import json

        json.dump(
            {"entries": [{"fingerprint": "cts2:abc"}]},  # no fingerprint_schema field
            fh,
        )
    st.validate_baseline_schema(state_dir)


def test_validate_baseline_schema_bad_field_rejected(state_dir):
    _seed_baseline(state_dir, "future")
    with pytest.raises(st.StateError) as exc:
        st.validate_baseline_schema(state_dir)
    assert "bad fingerprint_schema" in str(exc.value)


def test_write_baseline_uses_supported_schema_constant(state_dir):
    from cds_static_analyzer.fingerprint import FINGERPRINT_SCHEMA

    st.write_baseline(state_dir, [])
    entries, schema = st.read_baseline(state_dir)
    assert schema == FINGERPRINT_SCHEMA
    text = open(st.baseline_path(state_dir), encoding="utf-8").read()
    assert f'"fingerprint_schema": {FINGERPRINT_SCHEMA}' in text

