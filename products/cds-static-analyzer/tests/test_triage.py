"""Pure decision-file validation for analyzer triage."""

import json

import pytest

from cds_static_analyzer.triage import TriageError, load_decisions


def test_load_decisions_validation(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"fingerprint": "cts1:x", "action": "nope"}]))
    with pytest.raises(TriageError):
        load_decisions(str(bad))

    noreason = tmp_path / "nr.json"
    noreason.write_text(
        json.dumps([{"fingerprint": "cts1:x", "action": "suppress"}])
    )
    with pytest.raises(TriageError):
        load_decisions(str(noreason))
