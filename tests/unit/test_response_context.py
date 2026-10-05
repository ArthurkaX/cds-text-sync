# -*- coding: utf-8 -*-
"""
test_response_context.py — the daemon's ``context`` block on every response.

``ide_response_context`` builds a compact "where am I" snapshot -- project,
IDE id, PLC state, whether edits are allowed -- from the daemon's *cached*
state, and ``attach_response_metadata`` puts it beside ``instance`` on every
command envelope. The point of the block is that an agent can see the state
instead of learning it from a refusal, so the tests pin its shape and, above
all, that building it never touches the PLC.
"""

from __future__ import annotations

import dis
import json
import os
import sys
from types import SimpleNamespace

import pytest

BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if BRIDGE not in sys.path:
    sys.path.insert(0, BRIDGE)

import ide_response_context as ctx  # noqa: E402

STATE_KEY = "_codesys_daemon_loop"


@pytest.fixture(autouse=True)
def _clean_state():
    """No daemon state and no remembered session between tests."""
    saved_state = getattr(sys, STATE_KEY, None)
    saved_seen = dict(ctx._seen_session)
    if hasattr(sys, STATE_KEY):
        delattr(sys, STATE_KEY)
    yield
    if saved_state is None:
        if hasattr(sys, STATE_KEY):
            delattr(sys, STATE_KEY)
    else:
        setattr(sys, STATE_KEY, saved_state)
    ctx._seen_session.clear()
    ctx._seen_session.update(saved_seen)


def _install(monkeypatch, online="run", connected=True, project=None, started_ts=None):
    """A daemon with a cached wrapper (or none) and an optional project."""
    wrapper = None
    if online is not None:
        wrapper = SimpleNamespace(
            is_connected=connected,
            is_running=(online == "run"),
            application_state=online,
        )
    state = {"online_app": wrapper}
    if started_ts is not None:
        state["started_ts"] = started_ts
    sys._codesys_daemon_loop = state
    info = {"id": "ide-999", "project": project}
    monkeypatch.setattr(ctx, "_instance_info", lambda: info)
    monkeypatch.setattr(
        ctx,
        "_get_plc_status_snapshot",
        lambda: {
            "online": None if online is None else connected,
            "application_state": online or "",
            "application": "Application",
            "running": online == "run",
        },
    )
    return wrapper


PROJECT = {"name": "cts-reference-project", "path": r"S:\cts\cts.project", "sync_folder": r"S:\cts"}


# ── the online case: edits are blocked, and it says so ─────────────────────


def test_online_blocks_edits_and_explains(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    block = ctx.build_context()
    assert block["project"] == "cts-reference-project"
    assert block["ide"] == "ide-999"
    assert block["plc"]["online"] is True
    assert block["plc"]["state"] == "run"
    assert block["edits_allowed"] is False
    assert "cts disconnect" in block["hint_short"]
    assert "online" in block["hint"].lower()
    assert isinstance(block["age_s"], int)


def test_offline_allows_edits_with_no_hint(monkeypatch):
    _install(monkeypatch, online="stop", connected=False, project=PROJECT)
    block = ctx.build_context()
    assert block["plc"]["online"] is False
    assert block["edits_allowed"] is True
    assert "hint" not in block
    assert "hint_short" not in block


def test_unknown_state_is_null_not_a_wait(monkeypatch):
    _install(monkeypatch, online=None, project=PROJECT, started_ts=1000.0)
    block = ctx.build_context()
    assert block["plc"]["online"] is None
    # Unknown is neither permission nor refusal: live, edits_allowed was true
    # here while an edit was refused, which read as "go ahead".
    assert block["edits_allowed"] is None
    assert "hint" in block
    # The age is how long we have run without a session -- not omitted.
    assert block["age_s"] >= 1_000_000


def test_edits_allowed_is_the_tri_state_of_online(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    assert ctx.build_context()["edits_allowed"] is False
    _install(monkeypatch, online="stop", connected=False, project=PROJECT)
    assert ctx.build_context()["edits_allowed"] is True
    _install(monkeypatch, online=None, project=PROJECT)
    assert ctx.build_context()["edits_allowed"] is None


def test_no_project_is_called_out(monkeypatch):
    _install(monkeypatch, online=None, project=None, started_ts=1000.0)
    block = ctx.build_context()
    assert block["project"] is None
    assert "No project" in block["hint"]


def test_state_falls_back_to_the_running_flag(monkeypatch):
    _install(monkeypatch, project=PROJECT)
    monkeypatch.setattr(
        ctx,
        "_get_plc_status_snapshot",
        lambda: {"online": True, "application_state": "", "running": False},
    )
    assert ctx.build_context()["plc"]["state"] == "stop"


# ── the schema: only the documented keys, hint only when needed ────────────


def test_the_plain_keys_are_exactly_the_contract(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    assert set(ctx.build_context()) == {
        "project", "ide", "plc", "edits_allowed", "age_s", "hint", "hint_short",
    }


def test_a_quiet_context_has_no_hint_keys(monkeypatch):
    _install(monkeypatch, online="stop", connected=False, project=PROJECT)
    assert "hint" not in ctx.build_context()
    assert "hint_short" not in ctx.build_context()


# ── age_s tracks the cached session, and resets when the handle changes ────


def test_age_resets_when_the_session_handle_changes(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    first = ctx.build_context()["age_s"]
    # A different wrapper object (a reconnect) is a fresh cache.
    sys._codesys_daemon_loop["online_app"] = SimpleNamespace(
        is_connected=True, is_running=True, application_state="run"
    )
    assert ctx.build_context()["age_s"] <= max(first, 0)


# ── cheap: cached only, never a PLC/IDE call ───────────────────────────────


def test_building_the_context_touches_the_plc_at_most_once(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    calls = {"snapshot": 0, "instance": 0}
    real_snapshot = ctx._get_plc_status_snapshot
    monkeypatch.setattr(ctx, "_get_plc_status_snapshot",
                        lambda: (calls.__setitem__("snapshot", calls["snapshot"] + 1),
                                 real_snapshot())[1])

    ctx.build_context()

    assert calls["snapshot"] == 1


_OPENERS = ("ensure_online_connection", "create_online_application",
            "require_online_session", "adopt_existing_online_session",
            "login", "connect_to_device_impl")


def _global_names(func):
    names = set()
    todo = [func.__code__]
    while todo:
        code = todo.pop()
        for instruction in dis.get_instructions(code):
            if instruction.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                names.add(instruction.argval)
        todo.extend(c for c in code.co_consts if hasattr(c, "co_code"))
    return names


@pytest.mark.parametrize("name", ["build_context", "attach_response_metadata"])
def test_the_context_builder_never_opens_a_session(name):
    reached = _global_names(getattr(ctx, name))
    assert not (reached & set(_OPENERS))


def test_cost_of_a_context_block_is_small(monkeypatch):
    """A guard, not a benchmark: the block stays a few hundred bytes."""
    _install(monkeypatch, online="run", project=PROJECT)
    assert len(json.dumps(ctx.build_context())) < 1000


# ── attach_response_metadata: instance + context on the envelope ───────────


def test_attach_puts_context_beside_instance(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    response = {"ok": True, "data": {"status": "pong"}}
    returned = ctx.attach_response_metadata(response)
    assert returned is response
    assert response["data"] == {"status": "pong"}
    assert response["instance"]["id"] == "ide-999"
    assert response["context"]["project"] == "cts-reference-project"


def test_attach_echoes_the_request_id_only_when_present(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    without = ctx.attach_response_metadata({"ok": True})
    assert "request_id" not in without
    with_id = ctx.attach_response_metadata({"ok": True}, request_id="42-1")
    assert with_id["request_id"] == "42-1"


def test_attach_leaves_a_non_dict_response_alone():
    assert ctx.attach_response_metadata("not a dict") == "not a dict"
    assert ctx.attach_response_metadata(None) is None


# ── every representative command envelope gets one context, at the top ─────


@pytest.mark.parametrize(
    "envelope",
    [
        {"ok": True, "data": {"status": "pong"}},                                # ping
        {"ok": True, "data": {"saved": False}},                                  # editing (import)
        {"ok": True, "data": {"messages": [], "success": True}},                 # build
        {"ok": True, "data": {"downloaded": True, "option": "Never"}},           # download
        {"ok": False, "error": "The IDE is online with the PLC; ..."},           # refusal
        {"ok": True, "data": {"leaves": [{"path": "GVL.a", "type": "BOOL"}]}},   # tree
    ],
    ids=["ping", "import", "build", "download", "refusal", "tree"],
)
def test_every_representative_envelope_gets_one_context(monkeypatch, envelope):
    _install(monkeypatch, online="run", project=PROJECT)
    before = json.loads(json.dumps(envelope))
    ctx.attach_response_metadata(envelope)
    assert "context" in envelope
    # Additive only: every original key is untouched.
    for key, value in before.items():
        assert envelope[key] == value


def test_context_is_once_at_the_top_not_in_the_arrays(monkeypatch):
    _install(monkeypatch, online="run", project=PROJECT)
    envelope = {"ok": True, "data": {"leaves": [{"path": "GVL.a"}]}}
    ctx.attach_response_metadata(envelope)
    assert "context" in envelope
    assert "context" not in envelope["data"]
    assert "context" not in envelope["data"]["leaves"][0]
