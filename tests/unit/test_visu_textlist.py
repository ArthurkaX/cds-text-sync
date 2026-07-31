# -*- coding: utf-8 -*-
"""
test_visu_textlist.py -- Text-ID allocation against the GlobalTextList.

A Text ID is the only part of a compiled screen that is *shared* state: every
screen in a project draws its captions from one list, and an id is handed out
by reading the current maximum and adding one. That makes allocation the one
place in the pipeline where two runs can corrupt each other, and the corruption
is silent -- a duplicate id compiles, imports, and shows the wrong caption.
"""

import os
import subprocess
import sys
import textwrap

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_text_sync.visu import textlist


_ENTRY = """          <Single Type="{53da1be7-ad25-47c3-b0e8-e26286dad2e0}" Method="IArchivable">
            <Single Name="TextID" Type="string">{id}</Single>
            <Single Name="TextDefault" Type="string">{text}</Single>
            <List Name="LanguageTexts" Type="System.Collections.ArrayList" />
          </Single>
"""

_SKELETON = """<?xml version='1.0' encoding='utf-8'?>
<Single Type="{{6198ad31-4b98-445c-927f-3258a0e82fe3}}" Method="IArchivable">
      <Single Name="Object" Type="{{63784cbb-9ba0-45e6-9d69-babf3f040511}}" Method="IArchivable">
        <List Name="TextList" Type="System.Collections.ArrayList">
{entries}        </List>
      </Single>
</Single>
"""


def _project_view(tmp_path, entries=(("100", "Start"),)):
    """A project-view directory holding a minimal but real GlobalTextList."""
    pous = tmp_path / "POUs"
    pous.mkdir(parents=True, exist_ok=True)
    body = "".join(
        _ENTRY.replace("{id}", i).replace("{text}", t) for i, t in entries
    )
    (pous / "GlobalTextList.xml").write_text(
        _SKELETON.format(entries=body), encoding="utf-8"
    )
    return str(tmp_path)


def _ids_in(project_view):
    path = os.path.join(project_view, "POUs", "GlobalTextList.xml")
    return [e.get("text_id") for e in textlist._read_textlist_entries(path)]


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


def test_a_new_text_takes_the_next_id(tmp_path):
    pv = _project_view(tmp_path, [("100", "Start"), ("101", "Stop")])
    assert textlist.allocate_text_id(pv, "Reset") == "102"
    assert _ids_in(pv) == ["100", "101", "102"]


def test_the_same_text_reuses_its_id(tmp_path):
    """Captions repeat across a screen; each repeat must not grow the list."""
    pv = _project_view(tmp_path, [("100", "Start")])
    assert textlist.allocate_text_id(pv, "Start") == "100"
    assert _ids_in(pv) == ["100"]


# ---------------------------------------------------------------------------
# Two processes at once
# ---------------------------------------------------------------------------


_WORKER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {root!r})
    from cds_text_sync.visu import textlist
    pv, tag = sys.argv[1], sys.argv[2]
    for n in range(8):
        textlist.allocate_text_id(pv, "{{0}}-{{1}}".format(tag, n))
    """
)


def test_two_processes_do_not_hand_out_the_same_id(tmp_path):
    """The bug this file exists for.

    Allocation reads ``max(id) + 1`` and then appends. Run two compiles at once
    -- two authors, or one author with two screens in flight -- and both read
    the same maximum, both append it, and two screens end up pointing at one
    entry. In the IDE that is a label showing another screen's text, and no
    check we have can see it: the XML is well formed and every reference
    resolves.
    """
    pv = _project_view(tmp_path, [("100", "Start")])
    script = tmp_path / "worker.py"
    script.write_text(_WORKER.format(root=_ROOT), encoding="utf-8")

    procs = [
        subprocess.Popen([sys.executable, str(script), pv, tag])
        for tag in ("A", "B")
    ]
    for proc in procs:
        assert proc.wait(timeout=120) == 0

    ids = _ids_in(pv)
    assert len(ids) == len(set(ids)), "duplicate Text ID: {0}".format(ids)
    assert len(ids) == 17  # the seed plus 8 from each worker


# ---------------------------------------------------------------------------
# The lock itself
# ---------------------------------------------------------------------------


def test_the_lock_file_does_not_outlive_the_allocation(tmp_path):
    """A lock left behind would make the next author wait 30s for nothing."""
    pv = _project_view(tmp_path)
    textlist.allocate_text_id(pv, "Reset")
    lock = os.path.join(pv, "POUs", "GlobalTextList.xml.lock")
    assert not os.path.exists(lock)


def test_a_stale_lock_is_broken_rather_than_waited_out(tmp_path, monkeypatch):
    """A process that dies mid-write must not wedge every later compile.

    Failing closed here would turn one crashed run into a project that cannot
    compile another screen until somebody finds and deletes a file they have
    never heard of.
    """
    pv = _project_view(tmp_path)
    lock = os.path.join(pv, "POUs", "GlobalTextList.xml.lock")
    open(lock, "w").close()
    monkeypatch.setattr(textlist, "_lock_age", lambda _path: 999.0)

    assert textlist.allocate_text_id(pv, "Reset") == "101"
    assert not os.path.exists(lock)
