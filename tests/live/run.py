#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live scenarios against a small project open in CODESYS.

Manual live checks (type `cts …` on the VM, read the output) do not scale: the
next change is checked a different way than the last one.  This runner drives
`cts` as a subprocess through a handful of scenarios and prints one table, so
every change to the sync can be checked the same way in a minute or two.

It is not collected by pytest (no ``test_`` prefix).  It runs on the machine
where `cts` and CODESYS run -- Windows -- and needs:

  * ``CTS_LIVE_PROJECT``: the project root (a git working tree with
    ``project-view/`` and the sync base) whose project is open in
    CODESYS with the in-IDE agent running.
  * a clean git tree there: every scenario restores the disk with git, so
    uncommitted work would be lost.

Optional arguments select a subset of scenarios by name.

Every scenario ends with ``cts compare`` reporting no difference, so the
project is exactly as it was found.  A scenario that fails names the `cts`
command it ran and the first lines of its output; the exit code is 1.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


_OWNER_ENDS = ("END_PROGRAM", "END_FUNCTION_BLOCK", "END_FUNCTION")


def _names(items):
    """``2 (A: why, B)``: how many compare items, and which."""
    if not items:
        return "0"
    return "{0} ({1})".format(len(items), ", ".join(
        "{0}: {1}".format(item.get("name"), item["reason"]) if item.get("reason") else str(item.get("name"))
        for item in items))


class LiveError(Exception):
    """The project or the IDE is not what a scenario needs."""


def cts_command():
    """The `cts` to run: the checkout's cts.exe, the one under test.  Build
    it first (``dotnet build products/codesys-agent/src/Cts.Cli -c Release``).
    """
    exe = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "products", "codesys-agent", "src", "Cts.Cli", "bin", "Release", "net48", "cts.exe")
    if not os.path.isfile(exe):
        raise LiveError("no {0}: build products/codesys-agent/src/Cts.Cli first".format(exe))
    return [exe]


class Context(object):
    """The project under test and the last `cts` call."""

    def __init__(self, root):
        self.root = root
        self._cts = cts_command()
        self.last = None             # (argv, returncode, stdout, stderr) of the last call
        self.objects = {}            # name -> {"guid", "path"}, see load_objects
        self.files = {}              # file stem -> {extension: path}
        self.view_root = os.path.join(root, "project-view")
        self.cleanup_hooks = []      # IDE-level cleanups a scenario registers (see restore)

    # -- running cts ---------------------------------------------------------

    def cts(self, *args):
        """Run one `cts` command; return ``(returncode, stdout, stderr)``.

        Runs wherever the runner was started, with no working-directory
        setup: a project's sync folder may be stored relative (``..``), and
        the agent must resolve that against the saved project, not the CWD.
        """
        argv = self._cts + [str(a) for a in args]
        done = subprocess.run(
            argv, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        self.last = (argv, done.returncode, done.stdout, done.stderr)
        # The runner changes the IDE only through cts and the agent: a notice
        # of IDE changes made outside cts is the journal counting cts's own write.
        if "changed outside cts" in done.stdout + done.stderr:
            raise AssertionError("the journal reported cts's own IDE write as a user edit")
        return done.returncode, done.stdout, done.stderr

    def cts_ok(self, *args):
        """Run a command that must exit 0; return ``(returncode, stdout, stderr)``.

        The caller still checks the verdict line: exit 0 is not the whole
        answer (``partial`` is not an error code).
        """
        code, out, err = self.cts(*args)
        if code != 0:
            raise AssertionError(
                "`cts {0}` exited {1}, not 0".format(" ".join(str(a) for a in args), code)
            )
        return code, out, err

    def open_project(self, path):
        """`cts project open --path PATH`, which must succeed.  A CODESYS
        newer than the project's compiler asks on every load whether to update
        it (Project Environment): answered Cancel, the project's versions kept,
        as an engineer who does not upgrade answers it.  The open names the
        dialog in its answer, or fails on it when it came first: then it runs again."""
        code, out, err = self.cts("project", "open", "--path", path)
        if "Project Environment" in out + err:
            self.cts_ok("dialog", "answer", "--press", "Cancel")
            if code != 0:
                code, out, err = self.cts("project", "open", "--path", path)
        if code != 0:
            raise AssertionError("`cts project open --path {0}` exited {1}, not 0".format(path, code))
        return code, out, err

    def verdict(self, stdout):
        """The first stdout line, which every `cts` command answers with."""
        for line in stdout.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def json_of(self, stdout):
        """The JSON object in a ``--json`` output, skipping any [INFO] lines."""
        start = stdout.find("{")
        if start < 0:
            raise AssertionError("no JSON in the output: {0!r}".format(stdout[:200]))
        return json.loads(stdout[start:])

    # -- project facts -------------------------------------------------------

    def load_objects(self):
        """Read the IDE's objects by name from the agent's ``project.tree`` (a
        name the tree holds twice is left out) and the view's files by stem."""
        objects, twice = {}, set()

        def visit(node, path):
            for child in node.get("children") or []:
                name = child.get("name") or ""
                if name in objects:
                    twice.add(name)
                objects[name] = {"guid": str(child.get("guid") or "").strip("{}").lower(),
                                 "path": path + (name,)}
                visit(child, path + (name,))

        visit(_agent_call("project.tree", {}), ())
        for name in twice:
            objects.pop(name)
        self.objects = objects
        self.files = {}
        for folder, _dirs, names in os.walk(self.view_root):
            for file_name in names:
                stem, extension = os.path.splitext(file_name)
                self.files.setdefault(stem, {})[extension.lower()] = os.path.join(folder, file_name)

    def _object(self, name):
        found = self.objects.get(name)
        if found is None:
            raise LiveError(
                "the live project has no object named {0}; the runner needs the fixture project".format(name))
        return found

    def guid(self, name):
        return self._object(name)["guid"]

    def file_of(self, name, extension):
        """The view file of object ``name`` with ``extension``: its own, else
        its owner's (a method's text is in its POU's ``.st``)."""
        for owner in reversed(self._object(name)["path"]):
            path = self.files.get(owner, {}).get(extension)
            if path:
                return path
        raise LiveError("object {0} has no {1} file in the view".format(name, extension))

    def st_path(self, name):
        return self.file_of(name, ".st")

    def append_to_body(self, name, line):
        """Add ``line`` as the last line of POU ``name``'s body: before the END
        keyword that closes it in its file (one file per POU), else at the
        file's end (the old layout).  Returns the file's path."""
        path = self.st_path(name)
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().rstrip("\n").split("\n")
        ends = [index for index, text in enumerate(lines) if text.strip().upper() in _OWNER_ENDS]
        lines.insert(ends[0] if ends else len(lines), line)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path

    # -- restore -------------------------------------------------------------

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", self.root] + [str(a) for a in args],
            capture_output=True, text=True,
        )

    def restore(self):
        """Put the disk back and bring the IDE back, then prove both agree.

        Called in a ``finally`` by the runner for every scenario.  A scenario
        that created an object in the IDE registers its removal in
        ``cleanup_hooks``, because git cannot remove it.  An online scenario
        disconnects first: import is refused while online.
        """
        if (self.json_of(self.cts("status", "--json")[1]).get("plc") or {}).get("online") is True:
            self.cts("disconnect")   # an online IDE refuses every edit below
        for hook in self.cleanup_hooks:
            hook()
        self.cleanup_hooks = []
        # The disk first, then the reverse edit: disk wins.
        self.git("checkout", "--", "project-view")
        self.git("clean", "-fd", "project-view")
        self.cts("import", "--force")   # the reverse edit: disk wins
        # Put the tree back exactly as git has it.
        self.git("checkout", "--", "project-view")
        self.git("clean", "-fd", "project-view")
        report = self.text_status()
        changed = report.get("changed") or []
        ide_only = report.get("ide_only") or []
        disk_only = report.get("disk_only") or []
        if changed or ide_only or disk_only:
            raise AssertionError(
                "restore did not converge: changed={0} ide_only={1} disk_only={2}".format(
                    *(_names(items) for items in (changed, ide_only, disk_only))
                )
            )
        # Disk and IDE agree again: so does the sync base, or the next
        # scenario would start from the last one's base.
        self.cts_ok("export", "--force")

    def plc(self):
        """The PLC block of ``cts status``."""
        return self.json_of(self.cts_ok("status", "--json")[1]).get("plc") or {}

    def text_status(self):
        """``cts compare --all``, read per text object: ``same`` counts the
        unchanged ones (each member of a POU file apart), ``changed`` lists
        every difference the IDE and the disk have, ``disk_only`` what only the
        disk has and ``ide_only`` what was deleted from it."""
        _code, out, err = self.cts("compare", "--all", "--json")
        answer = self.json_of(out)
        if "objects" not in answer:
            raise AssertionError("compare: {0} {1}".format(answer.get("message"), err.strip()[-300:]))
        objects = answer["objects"]
        return {
            "same": sum(1 for item in objects["unchanged"] if str(item.get("path", "")).endswith(".st")),
            "changed": objects["modified"] + objects.get("ide_changed", []) + objects.get("not_importable", []),
            "disk_only": objects["added"],
            "ide_only": objects["deleted"],
        }


# -- scenarios ---------------------------------------------------------------
#
# Each returns a one-word detail for the table and raises AssertionError on a
# mismatch.  The caller runs it inside try/finally, so `restore` is the
# scenario's own last word.


def scenario_compare_clean(ctx):
    """The untouched project: disk and IDE agree."""
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] > 0, "no object matched on either side"
    return "same={0} changed=0".format(report["same"])


def scenario_read_object_body(ctx):
    """`cts read-object --body` is the file `cts export` wrote: an FB with its
    members inside, a task as its .xml."""
    ctx.load_objects()
    for path, name, extension in (("Application/FB_Valve", "FB_Valve", ".st"),
                                  ("Task Configuration/Task", "Task", ".xml")):
        target = os.path.join(ctx.root, ".git", "cts", "live-read-object" + extension)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            code, out, _err = ctx.cts_ok("read-object", "--path", path, "--body-file", target)
            assert code == 0, out
            with open(target, "rb") as handle:
                body = handle.read()
        finally:
            if os.path.exists(target):
                os.remove(target)
        with open(ctx.file_of(name, extension), "rb") as handle:
            assert body == handle.read(), "{0}: the body is not the view file".format(name)
    return "st+xml same-as-export"


def scenario_import_text_via_agent(ctx):
    """An .st edit is carried by the in-IDE agent, and compare then agrees."""
    ctx.append_to_body("F_Scale", "// live runner: agent path")

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    return line.split(" s=")[0].replace("ok import ", "")


def scenario_export_fast(ctx):
    """A stable IDE stamp uses git until an import changes the IDE."""
    _code, first, _err = ctx.cts_ok("export")
    assert ctx.verdict(first).startswith("ok export "), ctx.verdict(first)
    _code, second, _err = ctx.cts_ok("export")
    assert "ide=unchanged" in ctx.verdict(second), ctx.verdict(second)
    ctx.append_to_body("F_Scale", "// live runner: invalidate export stamp")
    _code, imported, _err = ctx.cts_ok("import")
    assert ctx.verdict(imported).startswith("ok import "), ctx.verdict(imported)
    _code, after, _err = ctx.cts_ok("export")
    assert "ide=exported" in ctx.verdict(after), ctx.verdict(after)
    return "unchanged then exported"


def scenario_rename_import(ctx):
    """A same-folder rename of the file is renamed through the agent, same guid."""
    ctx.load_objects()
    old_guid = ctx.guid("FB_Motor")
    assert "FB_Drive" not in ctx.objects, "the fixture already has FB_Drive"
    folder = os.path.dirname(ctx.st_path("FB_Motor"))
    new_st = os.path.join(folder, "FB_Drive.st")
    os.rename(os.path.join(folder, "FB_Motor.st"), new_st)
    with open(new_st, encoding="utf-8") as handle:
        content = handle.read()
    assert "FUNCTION_BLOCK FB_Motor" in content
    with open(new_st, "w", encoding="utf-8") as handle:
        handle.write(content.replace("FUNCTION_BLOCK FB_Motor", "FUNCTION_BLOCK FB_Drive"))

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line

    # The old guid now carries the new name.
    ctx.load_objects()
    assert ctx.guid("FB_Drive") == old_guid

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    return "same-guid"


def scenario_task_import(ctx):
    """A task's settings take the agent path, leaf by leaf, not the whole export."""
    ctx.load_objects()
    task_guid = ctx.guid("Task")
    xml_path = ctx.file_of("Task", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        xml = handle.read()
    priority_old = '<Single Name="Priority" Type="string">1</Single>'
    interval_old = '<Single Name="Time" Type="string">200</Single>'
    assert priority_old in xml and interval_old in xml, \
        "the fixture Task.xml does not hold Priority 1 / Interval 200"
    with open(xml_path, "w", encoding="utf-8") as handle:
        handle.write(
            xml.replace(priority_old, priority_old.replace(">1<", ">5<"))
               .replace(interval_old, interval_old.replace(">200<", ">100<"))
        )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line

    fields = _agent_call("objects.fields", {"guid": task_guid})
    tree = fields.get("fields") if isinstance(fields, dict) else None
    assert isinstance(tree, dict), fields
    assert str(tree.get("Priority")) == "5", tree.get("Priority")
    assert str((tree.get("Interval") or {}).get("Time")) == "100", tree.get("Interval")

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    _code, compare_out, _err = ctx.cts_ok("compare")
    compare_line = ctx.verdict(compare_out)
    assert compare_line.startswith("ok ") and "modified=0" in compare_line, compare_line
    return "priority=5 interval=100"


def scenario_vars_online(ctx):
    """Reads and writes go through the agent, spelled and parsed by the IDE;
    `cts status` says online, then offline; `cts stop` and `cts start`
    run through the agent."""
    ctx.cts("connect")               # restore disconnects again
    state = ctx.plc()
    assert state.get("online") is True and state.get("application_state"), state
    stopped = ctx.json_of(ctx.cts_ok("stop", "--json")[1])
    assert stopped.get("application_state") == "stop", stopped
    assert ctx.plc().get("application_state") == "stop"
    started = ctx.json_of(ctx.cts_ok("start", "--json")[1])
    assert started.get("application_state") == "run" and started.get("changed") is True, started
    # The heartbeat counts the bench task's calls, a few a second, once the
    # task cycles again: start answers before the first cycle.
    ctx.cts_ok("wait-ready", "--var", "GVL_Bench.nHeartbeat")
    samples = ctx.json_of(ctx.cts_ok("read", "GVL_Bench.nHeartbeat", "--samples", "3", "--interval", "0.5",
                                     "--json")[1])["samples"]
    beats = [int(sample["results"][0]["value"].split("#")[-1]) for sample in samples]
    assert beats == sorted(beats) and beats[0] < beats[-1], samples
    assert [round(sample["t"] * 2) for sample in samples] == [0, 1, 2], samples
    sampled = ctx.verdict(ctx.cts_ok("read", "GVL_Bench.nHeartbeat", "--samples", "2", "--interval", "1.5")[1])
    assert sampled == "ok read samples=2 changes=1 failed=0", sampled
    ctx.cts_ok("stop")               # the state connect found
    written = ctx.json_of(ctx.cts_ok("write", "GVL_Bench.wData", "16#AB", "--json")[1])
    assert written.get("confirmed") is True, written
    assert written.get("written_as") == "WORD#171", written
    text = ctx.json_of(ctx.cts_ok("write", "GVL_Bench.sCpuMode", "it's $5", "--json")[1])
    assert (text.get("read_back") or {}).get("value") == "'it$'s $$5'", text
    enum = ctx.json_of(ctx.cts_ok("write", "GVL_Bench.eMode", "E_BenchMode#Run", "--json")[1])
    assert (enum.get("read_back") or {}).get("value") == "E_BenchMode.Run", enum
    came = ctx.verdict(ctx.cts_ok("read", "GVL_Bench.eMode", "--until", "Run")[1])
    assert came.startswith("ok read reached=true value=E_BenchMode.Run"), came
    code, out, err = ctx.cts("read", "GVL_Bench.eMode", "--until", "Idle", "--interval", "0.2", "--within", "1")
    assert code == 2 and ctx.verdict(out).startswith("partial read reached=false"), out + err

    together = ctx.json_of(ctx.cts_ok("write", "GVL_Bench.wData", "16#12", "GVL_Bench.eMode", "Idle",
                                      "--json")[1])
    assert together["confirmed"] is True and together["count"] == 2, together
    code, out, err = ctx.cts("write", "GVL_Bench.wData", "16#AB", "GVL_Bench.eMode", "abc")
    assert code != 0 and "GVL_Bench.eMode" in out + err and "nothing written" in out + err, out + err
    unchanged = ctx.json_of(ctx.cts_ok("read", "GVL_Bench.wData", "--json")[1])
    assert unchanged.get("value") == "WORD#18", unchanged
    ctx.cts_ok("write", "GVL_Bench.wData", "16#AB")

    code, out, err = ctx.cts("write", "GVL_Bench.wData", "abc")
    assert code != 0 and "is not a value for GVL_Bench.wData (WORD)" in out + err, out + err

    code, out, err = ctx.cts("read", "GVL_Bench.wData", "GVL_Bench.stBits", "GVL_Bench.nosuch", "--json")
    assert code == 1, (code, out, err)
    rows = ctx.json_of(out)["results"]
    members = [r for r in rows[1:-1]]
    assert rows[0]["value"] == "WORD#171" and rows[0]["read_ok"], rows
    assert members and all(r["name"].startswith("GVL_Bench.stBits.") and r["read_ok"] for r in members), rows
    assert not rows[-1]["read_ok"] and "is not exported" in rows[-1]["read_error"], rows
    single = ctx.json_of(ctx.cts_ok("read", "GVL_Bench.stBits", "--json")[1])["results"]
    assert [r["name"] for r in single] == [r["name"] for r in members], single

    ctx.cts_ok("disconnect")
    code, out, err = ctx.cts("read", "GVL_Bench.wData")
    assert code != 0 and "Run 'cts connect' first" in out + err, out + err
    assert ctx.plc().get("online") is False
    return "status {0}, stop/start, write/write many/read/read many/members/samples/until ok, offline refused".format(
        state["application_state"])


def scenario_snapshooter_online(ctx):
    """`cts snapshooter` over the agent: tree reads the declarations offline,
    take saves live values, diff names what moved, restore --apply writes the
    preset back through the IDE's own literal parser (enum and string too)."""
    ctx.cts("disconnect")
    tree = ctx.json_of(ctx.cts_ok("snapshooter", "tree", "--path", "GVL_Bench.", "--json")[1])
    types = {leaf["path"]: leaf["type"] for leaf in tree["leaves"]}
    assert types.get("GVL_Bench.wData") == "WORD", types
    assert types.get("GVL_Bench.eMode") == "E_BenchMode", types
    code, out, err = ctx.cts("snapshooter", "take", "--path", "GVL_Bench.wData")
    assert code != 0 and "Run 'cts connect' first" in out + err, out + err

    ctx.cts("connect")
    ctx.cts_ok("stop")
    ctx.cts_ok("write", "GVL_Bench.wData", "16#11")
    ctx.cts_ok("write", "GVL_Bench.eMode", "E_BenchMode#Fault")
    ctx.cts_ok("write", "GVL_Bench.sCpuMode", "it's $5")
    preset = os.path.join(tempfile.mkdtemp(prefix="cts-live-snap-"), "preset.json")
    picked = ["--path", "GVL_Bench.wData", "--path", "GVL_Bench.eMode", "--path", "GVL_Bench.sCpuMode"]
    taken = ctx.json_of(ctx.cts_ok("snapshooter", "take", *picked, "--label", "live",
                                   "--out", preset, "--json")[1])
    values = {v["path"]: v["value"] for v in taken["document"]["variables"]}
    assert values == {"GVL_Bench.wData": "WORD#17", "GVL_Bench.eMode": "E_BenchMode.Fault",
                      "GVL_Bench.sCpuMode": "'it$'s $$5'"}, values
    assert os.path.isfile(preset), taken

    ctx.cts_ok("write", "GVL_Bench.wData", "16#22")
    ctx.cts_ok("write", "GVL_Bench.eMode", "E_BenchMode#Idle")
    ctx.cts_ok("write", "GVL_Bench.sCpuMode", "other")
    report = ctx.json_of(ctx.cts_ok("snapshooter", "diff", "--input", preset, "--json")[1])["report"]
    assert sorted(c["path"] for c in report["value_changed"]) == sorted(values), report
    dry = ctx.json_of(ctx.cts_ok("snapshooter", "restore", "--input", preset, "--json")[1])["result"]
    assert dry["would_write"] == 3 and dry["written"] == 0, dry
    applied = ctx.json_of(ctx.cts_ok("snapshooter", "restore", "--input", preset, "--apply",
                                     "--json")[1])["result"]
    assert applied["written"] == 3 and applied["skipped"] == 0, applied
    report = ctx.json_of(ctx.cts_ok("snapshooter", "diff", "--input", preset, "--json")[1])["report"]
    assert report["identical"] is True, report

    wide = ctx.json_of(ctx.cts_ok("snapshooter", "take", "--prefix", "GVL_Bench.", "--json")[1])
    assert wide["count"] == tree["count"], (wide["count"], tree["count"])
    ctx.cts_ok("disconnect")
    return "tree {0} leaves, take/diff/restore --apply round trip, prefix take {1}".format(
        tree["count"], wide["count"])


def scenario_sync_folder_set(ctx):
    """`cts set-sync-folder` finds the fixture's folder by the project's id:
    refused online, refused with nothing stored for a folder inside the
    fixture's repository and for a new folder of a project whose folder is
    elsewhere (that takes --new-id), and nothing new when the folder the
    project file lies in is chosen again."""
    status = ctx.json_of(ctx.cts_ok("status", "--json")[1])
    original, project_id = status.get("sync_folder"), status.get("project_id")
    assert original and project_id, status
    ctx.cts("connect")               # restore disconnects again
    code, out, err = ctx.cts("set-sync-folder", original)
    assert code != 0 and "repeat `cts set-sync-folder`" in out + err, out + err
    ctx.cts_ok("disconnect")
    nested = os.path.join(os.path.dirname(status["project"]), "live-sub")
    code, out, err = ctx.cts("set-sync-folder", "live-sub")
    assert code != 0 and "nothing was stored" in out + err, out + err
    assert not os.path.exists(nested), nested
    again = ctx.json_of(ctx.cts_ok("set-sync-folder", "--json")[1])
    assert again.get("project_id") == project_id and again.get("changed") is False, again
    assert again["git"]["initialized"] is False and not any(again["git"]["added"].values()), again
    assert not again["git"]["settings_created"] and not again["git"]["project_id_added"], again
    # The folder is registered now: another one for the same project is a copy.
    fresh = os.path.join(tempfile.gettempdir(), "cts-live-git-" + os.urandom(6).hex(), "sync")
    code, out, err = ctx.cts("set-sync-folder", fresh)
    assert code != 0 and "--new-id" in out + err and "nothing was stored" in out + err, out + err
    assert not os.path.exists(fresh), fresh
    kept = ctx.json_of(ctx.cts_ok("status", "--json")[1])
    assert kept.get("sync_folder") == original, kept
    return "refused online, nested and a second folder; {0} kept for {1}".format(original, project_id[:8])


def scenario_simulation_toggle(ctx):
    """`cts project simulate` goes through the agent: refused online, then the
    active application's device switched the other way and back, saved each
    time.  The fixture's own state (simulation or a real runtime) is kept."""
    ctx.cts("connect")               # restore disconnects again
    code, out, err = ctx.cts("project", "simulate", "off")
    assert code != 0 and "repeat `cts project simulate`" in out + err, out + err
    ctx.cts_ok("disconnect")
    devices = ctx.json_of(ctx.cts_ok("project", "list-devices", "--json")[1])["devices"]
    start = next(d for d in devices if any(a.get("active") for a in d.get("applications") or []))["simulation"]
    try:
        flipped = ctx.json_of(ctx.cts_ok("project", "simulate", "off" if start else "on", "--json")[1])
        assert flipped.get("before") is start and flipped.get("after") is not start, flipped
        assert flipped.get("saved") is True, flipped
    finally:
        back = ctx.json_of(ctx.cts_ok("project", "simulate", "on" if start else "off", "--json")[1])
        # The saves rewrote the .project; the IDE holds what git has again.
        ctx.git("checkout", "--", ".project")
    assert back.get("after") is start, back
    return "refused online, {0} {1} and back".format(flipped.get("device"), "off" if start else "on")


def scenario_permissions_read(ctx):
    """`cts permissions` is answered by the agent from the sync folder's settings file."""
    data = ctx.json_of(ctx.cts_ok("permissions", "--json")[1])
    assert isinstance(data.get("deny"), list), data
    assert "cds-text-sync.json" in data.get("stored_in", ""), data
    assert "config_error" not in data, data
    return "deny={0}".format(len(data["deny"]))


def scenario_boot_app_online(ctx):
    """`cts boot-app` runs through the agent: refused offline, and while logged
    in it stores the application on the PLC as its boot application."""
    code, out, err = ctx.cts("boot-app")
    assert code != 0 and "Run 'cts connect' first" in out + err, out + err
    ctx.cts_ok("connect")            # restore disconnects again
    created = ctx.json_of(ctx.cts_ok("boot-app", "--json")[1])
    assert created.get("state") == "boot_application_created", created
    return "offline refused, {0} stored".format(created.get("application"))


def scenario_reset_online(ctx):
    """`cts reset` runs through the agent: warm and cold reset the logged-in
    application, origin is refused without --force."""
    ctx.cts_ok("connect")            # restore disconnects again
    for kind in ("warm", "cold"):
        reset = ctx.json_of(ctx.cts_ok("reset", "--kind", kind, "--json")[1])
        assert reset.get("kind") == kind and reset.get("application_state") == "stop", reset
    code, out, err = ctx.cts("reset", "--kind", "origin")
    assert code != 0 and "Pass --force to confirm" in out + err, out + err
    return "warm, cold, origin refused"


def scenario_plc_crc_online(ctx):
    """`cts plc-crc` runs through the agent: after a login the PLC runs the
    code the IDE generated; after an origin reset it holds none and says so;
    a download brings back a match and records the fixture's commit, which
    plc-crc then names."""
    ctx.cts_ok("connect")            # restore disconnects again
    same = ctx.json_of(ctx.cts_ok("plc-crc", "--json")[1])
    assert same["match"] is True and same["plc"] == same["ide"], same
    ctx.cts_ok("reset", "--kind", "origin", "--force")
    gone = ctx.json_of(ctx.cts_ok("plc-crc", "--json")[1])
    assert gone["plc"] is None and gone["match"] is None and "cts download" in gone["note"], gone
    head = ctx.git("rev-parse", "HEAD").stdout.strip()
    downloaded = ctx.json_of(ctx.cts_ok("download", "--start", "0", "--json")[1])
    assert downloaded["source"].get("commit") == head, downloaded["source"]
    back = ctx.json_of(ctx.cts_ok("plc-crc", "--json")[1])
    assert back["match"] is True and back["source"].get("commit") == head, back
    _code, out, _err = ctx.cts_ok("plc-crc")
    assert "commit={0}".format(head[:8]) in ctx.verdict(out), ctx.verdict(out)
    return "match, none after origin, match after download ({0}) from {1}".format(back["plc"]["code"], head[:8])


def scenario_download_online(ctx):
    """`cts download` runs through the agent: a full download resets the
    variables and, with --start 0, leaves the application stopped; by default
    it starts it; with no session it logs in by itself."""
    ctx.cts_ok("connect")            # restore disconnects again
    ctx.cts_ok("write", "GVL_Bench.wData", "16#5A")
    kept = ctx.json_of(ctx.cts_ok("download", "--start", "0", "--json")[1])
    assert kept["downloaded"] is True and kept["logged_in"] is False, kept
    assert kept["started"] is False and kept["application_state"] == "stop", kept
    value = ctx.json_of(ctx.cts_ok("read", "GVL_Bench.wData", "--json")[1])
    assert value.get("value") == "WORD#0", value
    started = ctx.json_of(ctx.cts_ok("download", "--json")[1])
    assert started["started"] is True and started["ready"] is True, started
    assert started["application_state"] == "run", started
    ctx.cts_ok("disconnect")
    login = ctx.json_of(ctx.cts_ok("download", "--start", "0", "--json")[1])
    assert login["logged_in"] is True and login["application_state"] == "stop", login
    return "reset to WORD#0, started, logged in itself"


def scenario_st_tests_simulation(ctx):
    """`cts test` runs the fixture's TestApp in simulation while Application
    stays online with the PLC: the ST tests pass, a broken F_Clamp fails one
    by name, and Application is the active one again after each run."""
    ctx.cts_ok("connect")            # restore disconnects again
    passed = ctx.json_of(ctx.cts_ok("test", "--json")[1])
    assert passed["status"] == "PASS" and passed["passed"] == 3 and passed["failed"] == 0, passed
    assert [t["status"] for t in passed["tests"]] == ["PASS"] * 3, passed["tests"]
    devices = ctx.json_of(ctx.cts_ok("project", "list-devices", "--json")[1])["devices"]
    apps = [a for d in devices for a in d.get("applications") or []]
    assert [a["name"] for a in apps if a.get("active")] == ["Application"], apps
    assert [a["name"] for a in apps if a.get("online")] == ["Application"], apps
    ctx.cts_ok("disconnect")
    ctx.append_to_body("F_Clamp", "F_Clamp := MAX(x, lo);")
    ctx.cts_ok("import")
    code, out, err = ctx.cts("test")
    assert code == 1 and "FAIL F_Clamp cuts to hi got=11.0 want=10.0" in out, out + err
    with open(os.path.join(ctx.root, ".git", "cts", "test", "TestApp.log"), encoding="utf-8") as log:
        lines = log.read().splitlines()
    assert lines[0].endswith("CTS|M|TEST_START|TestApp|") and len(lines) >= 4, lines
    return "3 passed beside the online PLC; a broken F_Clamp failed with what it got, logged"


def scenario_connect_keeps_plc(ctx):
    """`cts connect` never changes the application the PLC runs: with a change
    the IDE would carry as an online change, it logs in without it, says the
    PLC runs other code, and the PLC keeps its code."""
    ctx.cts_ok("connect")            # restore disconnects again
    ctx.cts_ok("download", "--start", "0")
    before = ctx.json_of(ctx.cts_ok("plc-crc", "--json")[1])["plc"]["code"]
    ctx.cts_ok("disconnect")
    ctx.append_to_body("F_Scale", "F_Scale := F_Scale + 0.5;")
    ctx.cts_ok("import")
    _code, out, _err = ctx.cts_ok("connect")
    assert "runs other code than the project" in out, out
    login = ctx.json_of(ctx.cts_ok("connect", "--json")[1])
    assert login["reused_session"] is True, login
    after = ctx.json_of(ctx.cts_ok("plc-crc", "--json")[1])["plc"]["code"]
    assert after == before, (before, after)
    return "online change declined, the PLC kept {0}".format(after)


def scenario_plc_files_online(ctx):
    """`cts plc ls` lists a PLC directory through the agent: the root
    holds PlcLogic, a missing directory fails, and a Windows path (Git Bash's
    rewrite of a leading '/') is refused."""
    ctx.cts_ok("connect")            # restore disconnects again
    root = ctx.json_of(ctx.cts_ok("plc", "ls", ".", "--json")[1])
    logic = [f for f in root["files"] if f["name"] == "PlcLogic"]
    assert logic and logic[0]["is_directory"] is True, root
    assert not any(f["name"] in (".", "..") for f in root["files"]), root
    code, out, err = ctx.cts("plc", "ls", "no-such-dir")
    assert code != 0 and "No directory 'no-such-dir' on the PLC" in out + err, out + err
    code, out, err = ctx.cts("plc", "ls", "C:/Program")
    assert code != 0 and "MSYS_NO_PATHCONV=1" in out + err, out + err
    return "{0} entries at the root".format(root["count"])


def scenario_plc_log_online(ctx):
    """`cts plc-log` reads the runtime log through the device's logger service:
    the loggers, the last entries as log file lines, every entry saved by
    --out, a logger the PLC lacks fails.  `cts plc put` writes a
    file to the PLC and `cts plc get` copies it back byte-equal; a file
    the PLC lacks fails.  The file stays on the simulated PLC, replaced on
    every run."""
    ctx.cts_ok("connect")
    listed = ctx.json_of(ctx.cts_ok("plc-log", "--loggers", "--json")[1])
    assert listed["count"] >= 1 and len(listed["loggers"]) == listed["count"], listed
    tail = ctx.json_of(ctx.cts_ok("plc-log", "--tail", "2", "--json")[1])
    assert tail["logger"] == listed["loggers"][0] and tail["tail_count"] == 2, tail
    assert all(re.match(r"\d{4}-\d\d-\d\dT[\d:.]+Z, 0x[0-9a-f]{8}, \d+, ", line) for line in tail["tail"]), tail
    code, out, err = ctx.cts("plc-log", "--logger", "no-such-logger", "--tail", "1")
    assert code != 0 and "No logger 'no-such-logger' on the PLC" in out + err, out + err
    # Not mkdtemp: its owner-only folder is closed to a CODESYS that runs
    # without the elevation this shell may have.
    folder = os.path.join(tempfile.gettempdir(), "cts-live-plc-" + os.urandom(6).hex())
    os.makedirs(folder)
    try:
        saved = ctx.json_of(ctx.cts_ok("plc-log", "--cts", "--out", folder, "--json")[1])
        with open(saved["saved_to"], encoding="utf-8") as handle:
            assert len(handle.read().splitlines()) == saved["saved_lines"] >= tail["total_lines"], saved
        src = os.path.join(folder, "up.log")
        with open(src, "w", newline="\n") as handle:
            handle.write("first\nlast\n")
        sent = ctx.json_of(ctx.cts_ok("plc", "put", src, "cts-live.log", "--json")[1])
        assert sent["destination"] == "cts-live.log" and sent["size"] == os.path.getsize(src), sent
        copy = os.path.join(folder, "copy.log")
        ctx.cts_ok("plc", "get", "cts-live.log", "--out", copy)
        with open(src, "rb") as one, open(copy, "rb") as two:
            assert one.read() == two.read()
        code, out, err = ctx.cts("plc", "get", "no-such.log", "--out", copy)
        assert code != 0 and "File is not valid" in out + err, out + err
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return "{0} entries in {1}".format(saved["saved_lines"], tail["logger"])


def scenario_devices_online(ctx):
    """`cts project list-devices` (with and without --device) is answered by the agent:
    the device holding the active application, and its online state."""
    listed = ctx.json_of(ctx.cts_ok("project", "list-devices", "--json")[1])
    owner = [d for d in listed["devices"] if any(a.get("active") for a in d["applications"])]
    assert len(owner) == 1, listed
    application = [a for a in owner[0]["applications"] if a["active"]][0]
    assert application["online"] is False, listed
    ctx.cts_ok("connect")            # restore disconnects again
    status = ctx.json_of(ctx.cts_ok("project", "list-devices", "--device", owner[0]["name"].lower(), "--json")[1])
    names = [d["name"] for d in status["devices"]]
    assert owner[0]["name"] in names, status
    online = [a for d in status["devices"] for a in d["applications"] if a["active"]][0]
    assert online["online"] is True and online.get("application_state") in ("run", "stop"), status
    return "{0} devices, {1} online {2}".format(listed["count"], online["name"], online["application_state"])


def scenario_project_reopen(ctx):
    """`cts project list|close|open` go through the agent: close is refused
    online and with unsaved changes, then the project closes and opens again
    as the primary one, and a second open says it already is."""
    listed = ctx.json_of(ctx.cts_ok("project", "list", "--json")[1])
    primary = [p for p in listed["projects"] if p["primary"]]
    assert len(primary) == 1 and primary[0]["path"].lower().endswith(".project"), listed
    path = primary[0]["path"]
    ctx.cts_ok("connect")            # restore disconnects again
    code, out, err = ctx.cts("project", "close")
    assert code != 0 and "`cts disconnect`, then `cts project close`" in out + err, out + err
    ctx.cts_ok("disconnect")
    ctx.cts_ok("save")
    try:
        closed = ctx.json_of(ctx.cts_ok("project", "close", "--json")[1])
        assert closed.get("closed") == primary[0]["name"], closed
        empty = ctx.json_of(ctx.cts_ok("project", "list", "--json")[1])
        assert empty["count"] == 0, empty
    finally:
        ctx.open_project(path)
        # The save rewrote the .project; the IDE holds what git has again.
        ctx.git("checkout", "--", ".project")
    reopened = ctx.json_of(ctx.cts_ok("project", "list", "--json")[1])
    assert [p["path"] for p in reopened["projects"] if p["primary"]] == [path], reopened
    again = ctx.json_of(ctx.cts_ok("project", "open", "--path", path, "--json")[1])
    assert again.get("already_open") is True, again
    return "closed and opened {0}".format(primary[0]["name"])


def scenario_build_errors(ctx):
    """`cts build` goes through the agent: a clean build passes and names a
    `.st` file edited but not imported yet; an imported compile error fails
    it with the compiler's code, object and the `.st` file, line and column
    it is at, a warning listed after it the same way (`--json` too, with
    `ok` false), `cts read-log` shows the error among the Build messages,
    and `cts verify` credits that verdict to the workspace it just imported.
    Each build is the last command `cts status` names."""
    clean = ctx.json_of(ctx.cts_ok("build", "--json")[1])
    assert clean.get("errors") == 0, clean
    last = ctx.json_of(ctx.cts_ok("status", "--json")[1]).get("last_command") or {}
    assert last.get("method") == "build" and last.get("ok") is True, last
    path = ctx.append_to_body("F_Scale", "undefined_thing := 1;")
    ctx.append_to_body("F_Scale", "GVL_Bench.nIter := GVL_Bench.nState;")   # a warning, C0195
    with open(path, encoding="utf-8") as handle:
        line = [text.strip() for text in handle.read().split("\n")].index("undefined_thing := 1;") + 1
    at = "{0}:{1}:1".format(os.path.relpath(path, ctx.root).replace(os.sep, "/"), line)
    # Not imported yet: the IDE's text still builds, and the build says what it left out.
    pending = ctx.json_of(ctx.cts_ok("build", "--json")[1])
    assert pending.get("errors") == 0 and pending.get("not_imported") == [at.rsplit(":", 2)[0]], pending
    ctx.cts_ok("import")
    code, out, err = ctx.cts("build")
    expected = "[C0046] Identifier 'undefined_thing' not defined (in F_Scale at {0})".format(at)
    assert code != 0 and expected in out + err, out + err
    warned = "warning [C0195] Implicit conversion from signed Type 'INT' to unsigned Type 'UDINT'"
    assert "{0} : Possible change of sign (in F_Scale at {1}:{2}:1)".format(
        warned, at.rsplit(":", 2)[0], line + 1) in out, out + err
    code, out, err = ctx.cts("build", "--json")
    failed = ctx.json_of(out)
    assert code != 0 and failed["ok"] is False and failed["errors"] >= 1, out + err
    assert "not_imported" not in failed and "not_imported" not in clean, failed
    assert any(m.get("file") and m.get("line") for m in failed["messages"]), failed
    last = ctx.json_of(ctx.cts_ok("status", "--json")[1]).get("last_command") or {}
    assert last.get("method") == "build" and last.get("ok") is False, last
    log = ctx.json_of(ctx.cts_ok("read-log", "--category", "build", "--last", "4", "--json")[1])
    assert log["category"]["description"] == "Build" and log["count"] == 4, log
    assert "Identifier 'undefined_thing' not defined" in log["messages"], log
    assert log["messages"][-1].startswith("Compile complete -- 2 errors"), log
    code, out, err = ctx.cts("read-log", "--category", "does-not-exist")
    assert code != 0 and "Available categories:" in out + err and "Build (97f48d64" in out + err, out + err
    code, out, err = ctx.cts("verify", "--only", "build", "--sync-folder", ctx.root, "--json")
    stage = [s for s in ctx.json_of(out)["stages"] if s["stage"] == "build"][0]
    assert stage["status"] == "fail", stage
    assert "differs" not in stage["summary"], stage
    found = {(p.get("rule"), p.get("where")) for p in stage.get("problems") or []}
    assert ("C0046", "F_Scale") in found, stage
    assert any(p.get("rule") == "C0046" and p.get("file") == at.rsplit(":", 2)[0] and p.get("line") == line
               for p in stage["problems"]), stage
    assert [p for p in stage["problems"] if p.get("severity") == "warning"] == [{
        "message": "Implicit conversion from signed Type 'INT' to unsigned Type 'UDINT' : Possible change of sign",
        "severity": "warning", "rule": "C0195", "file": at.rsplit(":", 2)[0], "line": line + 1,
        "where": "F_Scale"}], stage
    return "clean, then {0} error(s) in F_Scale, verify fail".format(stage["summary"]["errors"])


def scenario_library_build(ctx):
    """A library project builds through the agent too: `cts build` runs the
    IDE's "Check all Pool Objects", a compile error fails it and installs
    nothing, and `cts build --install` after a clean check saves the project
    and installs it under its Project Information.  Works on a copy of the
    fixture's `library/CtsLiveLib.library`, then reopens the fixture."""
    source = os.path.join(ctx.root, "library", "CtsLiveLib.library")
    assert os.path.isfile(source), "the fixture has no " + source
    listed = ctx.json_of(ctx.cts_ok("project", "list", "--json")[1])
    fixture = [p for p in listed["projects"] if p["primary"]][0]["path"]
    # Beside the fixture, not in %TEMP%: the IDE must see the path the
    # runner wrote, and the git directory is outside the working tree.
    work = os.path.join(ctx.root, ".git", "cts", "live-library")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    library = os.path.join(work, "CtsLiveLib.library")
    shutil.copyfile(source, library)
    ctx.cts_ok("save")
    ctx.cts_ok("project", "close")
    try:
        ctx.open_project(library)
        clean = ctx.json_of(ctx.cts_ok("build", "--json")[1])
        assert clean.get("kind") == "library" and clean.get("errors") == 0, clean
        assert clean.get("application") == "CtsLiveLib" and "installed" not in clean, clean
        gvl = _tree_node("Variables")
        assert gvl, "the library has no Variables list"
        text = _agent_call("objects.text", {"guid": gvl["guid"]})["declaration"]
        broken = text.replace("END_VAR", "\tg_broken : NoSuchType;\nEND_VAR")
        _agent_call("objects.settext", {"guid": gvl["guid"], "declaration": broken})
        code, out, err = ctx.cts("build", "--install")
        assert code != 0 and "[C0077] Unknown type: 'NoSuchType' (in Variables)" in out + err, out + err
        # The install saves first: a library still unsaved was not installed.
        unsaved = ctx.json_of(ctx.cts_ok("status", "--json")[1]).get("unsaved_changes")
        assert unsaved is True, "a check with an error went on to install"
        _agent_call("objects.settext", {"guid": gvl["guid"], "declaration": text})
        code, out, err = ctx.cts("build", "--install")
        line = ctx.verdict(out)
        assert code == 0 and line.startswith("ok build ") and "installed=true" in line, out + err
        assert 'library="cts live library, ' in line and '(cts)"' in line, line
        unsaved = ctx.json_of(ctx.cts_ok("status", "--json")[1]).get("unsaved_changes")
        assert unsaved is False, "the install did not save the library"
    finally:
        ctx.cts("save")   # a step that failed half-way leaves the copy changed
        ctx.cts("project", "close")
        ctx.open_project(fixture)
        # The save rewrote the .project; the IDE holds what git has again.
        ctx.git("checkout", "--", ".project")
        shutil.rmtree(work, ignore_errors=True)
    return line.split(" ", 2)[2]


def scenario_meta_property_import(ctx):
    """A visualization's size lives in a MetaObject property: the replace carries it."""
    ctx.load_objects()
    guid = ctx.guid("Visualization")
    xml_path = ctx.file_of("Visualization", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        xml = handle.read()
    old = '<Single Name="SizeX" Type="int">1024</Single>'
    assert xml.count(old) == 1, "the fixture Visualization.xml does not hold SizeX 1024"
    with open(xml_path, "w", encoding="utf-8") as handle:
        handle.write(xml.replace(old, old.replace(">1024<", ">1280<")))

    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), out
    meta = _agent_call("objects.export", {"guids": [guid]})["objects"][0]["meta"]
    assert '<Single Name="SizeX" Type="int">1280</Single>' in meta, "the IDE does not hold the new size"
    _code, compare_out, _err = ctx.cts_ok("compare")
    compare_line = ctx.verdict(compare_out)
    assert compare_line.startswith("ok ") and "modified=0" in compare_line, compare_line
    return "SizeX 1024->1280"  # the restore's import --force carries 1024 back


def scenario_import_refused_online(ctx):
    """While online, an import is refused and the IDE text stays untouched."""
    ctx.cts("connect")               # restore disconnects again
    status = ctx.json_of(ctx.cts("status", "--json")[1])
    assert (status.get("plc") or {}).get("online") is True, \
        "cts connect did not go online"

    ctx.append_to_body("F_Scale", "// live runner: refused online")

    code, out, err = ctx.cts("import")
    line = ctx.verdict(out)
    combined = out + err
    assert code != 0, "import while online exited 0: {0}".format(line)
    assert "online" in combined and "cts disconnect" in combined, combined[:400]

    # The IDE was never edited: compare sees the disk edit only.
    report = ctx.text_status()
    names = [item.get("name") for item in report.get("changed") or []]
    assert "F_Scale" in names, report
    assert not report.get("ide_only"), report["ide_only"]
    assert not report.get("disk_only"), report["disk_only"]
    return "refused online exit={0}".format(code)


def scenario_new_method_import(ctx):
    """`cts new method` authors a member; the agent creates it under its POU."""
    before = ctx.text_status()["same"]
    ctx.cts_ok("new", "method", "FB_Valve.M_LiveTmp", "--return-type", "BOOL",
               "--text", "M_LiveTmp := TRUE;", "--sync-folder", ctx.root)
    owner = ctx.st_path("FB_Valve")
    with open(owner, encoding="utf-8") as handle:
        assert "METHOD M_LiveTmp : BOOL" in handle.read(), "cts new left FB_Valve.st without the method"
    assert not os.path.exists(owner[:-3] + ".M_LiveTmp.st"), "cts new wrote a file of the method's own"
    # git cannot remove an object git never had: delete it in the IDE on restore.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("M_LiveTmp")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "M_LiveTmp" in out, out[:400]
    # FB_Valve is in the IDE, so the method is created below it.

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 1, report["same"]
    return "same={0}->{1}".format(before, report["same"])


def scenario_new_pou_import(ctx):
    """A new POU is created through the agent, and the project still builds."""
    before = ctx.text_status()["same"]
    ctx.cts_ok("new", "pou", "FB_LiveTmp", "--kind", "function-block",
               "--sync-folder", ctx.root)
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("FB_LiveTmp")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "FB_LiveTmp" in out, out[:400]

    _code, build_out, build_err = ctx.cts_ok("build")
    assert "errors=0" in build_out + build_err, \
        "the created POU does not build: {0}".format((build_out + build_err)[:300])

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 1, report["same"]
    return "same={0}->{1} build-ok".format(before, report["same"])


def scenario_build_all_objects(ctx):
    """A new block nothing calls is left out of the compile, so its error
    builds `ok`; `cts build --all-objects` checks it too and fails, the
    message marked not called by any task, at its file and line."""
    ctx.cts_ok("new", "pou", "FB_LiveUnused", "--kind", "function-block",
               "--text", "nUnknown := 1;", "--sync-folder", ctx.root)
    ctx.cleanup_hooks.append(lambda: _delete_in_ide("FB_LiveUnused"))
    ctx.cts_ok("import")
    plain = ctx.json_of(ctx.cts_ok("build", "--json")[1])
    assert plain["errors"] == 0, plain
    code, out, err = ctx.cts("build", "--all-objects")
    # cts new writes the header, VAR, END_VAR and the marker: the body is line 5.
    expected = "[C0046] Identifier 'nUnknown' not defined (in FB_LiveUnused at project-view/PLC_Stabur/" \
               "Plc Logic/Application/FB_LiveUnused.st:5:1, not called by any task)"
    assert code != 0 and expected in out, out + err
    return "plain build ok, --all-objects: {0}".format(ctx.verdict(out))


def scenario_new_dut_import(ctx):
    """A new DUT is created through the agent, and the project still builds."""
    before = ctx.text_status()["same"]
    ctx.cts_ok("new", "dut", "ST_LiveTmp", "--kind", "struct",
               "--text", "x : INT;", "--sync-folder", ctx.root)
    # git cannot remove an object git never had: delete it in the IDE on restore.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("ST_LiveTmp")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "ST_LiveTmp" in out, out[:400]

    _code, build_out, build_err = ctx.cts_ok("build")
    assert "errors=0" in build_out + build_err, \
        "the created DUT does not build: {0}".format((build_out + build_err)[:300])

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 1, report["same"]
    return "same={0}->{1} build-ok".format(before, report["same"])


def scenario_new_member_import(ctx):
    """A new ACTION and PROPERTY (with accessors) are created in one import."""
    before = ctx.text_status()["same"]
    ctx.cts_ok("new", "action", "FB_Valve.A_LiveTmp",
               "--text", "xOpen := FALSE;", "--sync-folder", ctx.root)
    ctx.cts_ok("new", "property", "FB_Valve.P_LiveTmp", "--type", "BOOL",
               "--get-text", "P_LiveTmp := xOpen;",
               "--set-text", "xOpen := P_LiveTmp;", "--sync-folder", ctx.root)
    # The property create removes its accessors with it; the action is separate.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("P_LiveTmp")
    )
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("A_LiveTmp")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    for name in ("A_LiveTmp", "P_LiveTmp", "Get", "Set"):
        assert name in out, "the verdict did not name {0}: {1!r}".format(name, out[:400])

    _code, build_out, build_err = ctx.cts_ok("build")
    assert "errors=0" in build_out + build_err, \
        "the created members do not build: {0}".format((build_out + build_err)[:300])

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    # The action, the property and its two accessors are four objects.
    assert report["same"] == before + 4, report["same"]
    return "same={0}->{1} build-ok".format(before, report["same"])


def scenario_new_interface_import(ctx):
    """A new INTERFACE and one of its methods are created in one import."""
    before = ctx.text_status()["same"]
    folder = os.path.dirname(ctx.st_path("FB_Valve"))
    with open(os.path.join(folder, "I_LiveTmp.st"), "w", encoding="utf-8") as handle:
        handle.write("INTERFACE I_LiveTmp\nEND_INTERFACE\n")
    with open(os.path.join(folder, "I_LiveTmp.M_LiveTmp.st"), "w", encoding="utf-8") as handle:
        handle.write("METHOD M_LiveTmp : BOOL\nVAR_INPUT\n\tx : BOOL;\nEND_VAR\n")
    # The method hook runs first; deleting the interface removes whatever is
    # still below it.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("M_LiveTmp")
    )
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("I_LiveTmp")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "I_LiveTmp" in out, out[:400]

    _code, build_out, build_err = ctx.cts_ok("build")
    assert "errors=0" in build_out + build_err, \
        "the created interface does not build: {0}".format((build_out + build_err)[:300])

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 2, report["same"]

    # The next export writes the interface like a POU, one file with its
    # method inside, and compare still lists both as unchanged.
    ctx.cts_ok("export")
    assert not os.path.exists(os.path.join(folder, "I_LiveTmp.M_LiveTmp.st")), \
        "export left the method in a file of its own"
    with open(os.path.join(folder, "I_LiveTmp.st"), encoding="utf-8") as handle:
        text = handle.read()
    assert text.startswith("INTERFACE I_LiveTmp"), "export did not project the interface as .st"
    assert "METHOD M_LiveTmp : BOOL" in text, "export did not put the method into I_LiveTmp.st"
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 2, report["same"]
    return "same={0}->{1} build-ok export-st".format(before, report["same"])


def scenario_new_gvl_import(ctx):
    """A new GVL is created through the agent, and compare then agrees."""
    before = ctx.text_status()["same"]
    ctx.cts_ok("new", "gvl", "GVL_LiveTmp", "--text", "x : BOOL;",
               "--sync-folder", ctx.root)
    # git cannot remove an object git never had: delete it in the IDE on restore.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("GVL_LiveTmp")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "GVL_LiveTmp" in out, \
        "the verdict did not name the created GVL: {0!r}".format(out[:400])

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert not report.get("ide_only"), report["ide_only"]
    assert not report.get("disk_only"), report["disk_only"]
    assert report["same"] == before + 1, report["same"]
    return "same={0}->{1}".format(before, report["same"])


def scenario_delete_import(ctx):
    """A GVL whose file is deleted is deleted in the IDE through the agent."""
    before = ctx.text_status()["same"]
    ctx.cts_ok("new", "gvl", "GVL_LiveDel", "--text", "x : BOOL;",
               "--sync-folder", ctx.root)
    # Should the delete not land, restore removes it the old way.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("GVL_LiveDel")
    )
    code, out, _err = ctx.cts_ok("import")
    assert ctx.verdict(out).startswith("ok "), ctx.verdict(out)
    assert ctx.text_status()["same"] == before + 1

    ctx.load_objects()
    os.remove(ctx.st_path("GVL_LiveDel"))
    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "deleted=1" in line, line

    report = ctx.text_status()
    assert not report.get("ide_only"), report["ide_only"]
    assert not report.get("disk_only"), report["disk_only"]
    assert report["same"] == before, report["same"]
    return "same={0}->{1}->{0} deleted=1".format(before, before + 1)


def scenario_new_folder_import(ctx):
    """A new folder with one GVL is created in one agent import, and the
    next export keeps the files in the same place."""
    before = ctx.text_status()["same"]
    folder = os.path.join(os.path.dirname(ctx.st_path("FB_Valve")), "LiveTmpFolder")
    os.mkdir(folder)
    with open(os.path.join(folder, "GVL_LiveTmp.st"), "w", encoding="utf-8") as handle:
        handle.write("VAR_GLOBAL\n\txLiveTmp : BOOL;\nEND_VAR\n")
    # The GVL hook runs first; deleting the folder removes whatever is
    # still below it.
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("GVL_LiveTmp")
    )
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("LiveTmpFolder")
    )

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "LiveTmpFolder" in out and "GVL_LiveTmp" in out, out[:400]

    _code, build_out, build_err = ctx.cts_ok("build")
    assert "errors=0" in build_out + build_err, \
        "the created folder does not build: {0}".format((build_out + build_err)[:300])

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    # The folder itself has no .st: only the GVL counts.
    assert report["same"] == before + 1, report["same"]

    # The next export lays the folder out as a directory with its
    # .cds-object.xml, keeping the GVL's file where the import put it.
    ctx.cts_ok("export")
    for relative in ("GVL_LiveTmp.st", ".cds-object.xml"):
        assert os.path.isfile(os.path.join(folder, relative)), \
            "export left no {0}".format(relative)
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 1, report["same"]

    # The directory removed, its .cds-object.xml with it: the folder goes too.
    shutil.rmtree(folder)
    code, out, _err = ctx.cts_ok("import")
    assert code == 0 and "deleted GVL_LiveTmp" in out and "deleted LiveTmpFolder" in out, out[:400]
    assert _tree_node("LiveTmpFolder") is None, "the folder is still in the IDE"
    assert ctx.text_status()["same"] == before
    return "same={0}->{1} build-ok export-kept folder-deleted".format(before, report["same"])


def scenario_root_import(ctx):
    """A POU and a folder with a POU at the top of project-view/ land at the
    project root (the POUs view), where the POUs every application shares
    live; the export keeps them there, and removing the files removes them
    again."""
    before = ctx.text_status()["same"]
    folder = os.path.join(ctx.view_root, "LiveRootFolder")
    os.mkdir(folder)
    for path, name in ((os.path.join(ctx.view_root, "F_LiveRootTop.st"), "F_LiveRootTop"),
                       (os.path.join(folder, "F_LiveRoot.st"), "F_LiveRoot")):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("FUNCTION {0} : INT\nVAR_INPUT\n\ta : INT;\nEND_VAR\n"
                         "// --- implementation ---\n{0} := a + 1;\nEND_FUNCTION\n".format(name))
    for name in ("F_LiveRootTop", "F_LiveRoot", "LiveRootFolder"):
        ctx.cleanup_hooks.append(lambda name=name: _delete_in_ide(name))

    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    for name in ("F_LiveRootTop", "F_LiveRoot", "LiveRootFolder"):
        assert name in out, out[:400]

    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 2, report["same"]

    # The export keeps both files where the import took them from.
    ctx.cts_ok("export")
    for path in (os.path.join(ctx.view_root, "F_LiveRootTop.st"), os.path.join(folder, "F_LiveRoot.st"),
                 os.path.join(folder, ".cds-object.xml")):
        assert os.path.isfile(path), "export left no {0}".format(path)
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    assert report["same"] == before + 2, report["same"]

    # The directory removed, its .cds-object.xml with it: the folder goes too.
    os.remove(os.path.join(ctx.view_root, "F_LiveRootTop.st"))
    shutil.rmtree(folder)
    code, out, _err = ctx.cts_ok("import")
    assert code == 0 and "deleted F_LiveRootTop" in out and "deleted LiveRootFolder" in out, out[:400]
    assert _tree_node("LiveRootFolder") is None, "the folder is still in the IDE"
    assert ctx.text_status()["same"] == before
    return "same={0}->{1}->{0} export-kept".format(before, report["same"])


def scenario_new_gvl_import_twice(ctx):
    """The same new GVL imported twice: the second run has nothing to do."""
    ctx.cts_ok("new", "gvl", "GVL_LiveTmp", "--text", "x : BOOL;",
               "--sync-folder", ctx.root)
    ctx.cleanup_hooks.append(
        lambda: _delete_in_ide("GVL_LiveTmp")
    )
    code, out, _err = ctx.cts_ok("import")
    assert ctx.verdict(out).startswith("ok "), out[:200]
    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    # The base now holds the object, so the second run is a clean agent plan
    # with no create and no write.
    assert "text=0" in line, "the second import wrote something: {0}".format(line)
    return line.replace("ok import ", "")


def scenario_textlist_import(ctx):
    """A text-list row takes the agent path, through objects.setfield."""
    import csv as csv_module
    import io as io_module

    ctx.load_objects()
    guid = ctx.guid("GlobalTextList")
    csv_path = ctx.file_of("GlobalTextList", ".csv")
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        content = handle.read()
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv_module.DictReader(handle)
        header = reader.fieldnames or []
        rows = list(reader)
    assert header[:2] == ["TextID", "TextDefault"], header
    assert rows, "GlobalTextList.csv has no data rows"
    text_id = rows[0].get("TextID")
    assert text_id, "the first row has no TextID"
    # A comma and a quote in one value: the csv parse, not the line, decides.
    new_default = 'Press, "go"'
    buffer = io_module.StringIO()
    writer = csv_module.DictWriter(buffer, fieldnames=header, lineterminator="\n")
    changed_row = dict(rows[0])
    changed_row["TextDefault"] = new_default
    writer.writerow(changed_row)
    new_line = buffer.getvalue().rstrip("\n")
    disk_lines = content.split("\n")
    for index in range(1, len(disk_lines)):
        if disk_lines[index].startswith(text_id + ","):
            disk_lines[index] = new_line
            break
    else:
        raise LiveError(
            "GlobalTextList.csv has no single-line row for TextID {0}".format(text_id)
        )
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(disk_lines))
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        check = list(csv_module.DictReader(handle))
    assert len(check) == len(rows), "the edit changed the row count"
    assert check[0]["TextDefault"] == new_default, check[0]

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line

    matches = [
        item for item in _ide_text_rows(guid)
        if isinstance(item, dict) and item.get("TextID") == text_id
    ]
    assert len(matches) == 1, matches
    assert matches[0].get("TextDefault") == new_default, matches[0]

    _assert_clean(ctx)
    return "row={0} text={1!r}".format(text_id, new_default)


class AgentCallError(Exception):
    """`cts raw` answered with an error."""


def _agent_call(method, params):
    """One call to the IDE's agent through `cts raw` (the runner needs
    exactly one IDE: with more, cts refuses as ambiguous)."""
    argv = cts_command() + ["raw", method, "--timeout", "15"]
    for key, value in params.items():
        argv += ["--" + key, json.dumps(value)]
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise AgentCallError("`cts raw {0}` exited {1}: {2}".format(method, done.returncode, (done.stdout + done.stderr).strip()[:300]))
    starts = [index for index in (done.stdout.find("{"), done.stdout.find("[")) if index >= 0]
    return json.loads(done.stdout[min(starts):]) if starts else None


def _delete_in_ide(name):
    """A cleanup: delete the IDE objects of that name, if any (a user deletes
    by removing the file and running `cts import`)."""
    try:
        found = _agent_call("objects.find", {"name": name, "path": "", "app": ""})
        for match in found.get("matches") or []:
            _agent_call("objects.delete", {"guid": match["guid"]})
    except AgentCallError:
        pass


def _ide_text_rows(guid):
    """GlobalTextList's TextList rows as the agent's objects.fields reads them."""
    fields = _agent_call("objects.fields", {"guid": guid})
    tree = fields.get("fields") if isinstance(fields, dict) else None
    assert isinstance(tree, dict), fields
    return tree.get("TextList") or []


def _assert_clean(ctx):
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    _code, compare_out, _err = ctx.cts_ok("compare")
    compare_line = ctx.verdict(compare_out)
    assert compare_line.startswith("ok ") and "modified=0" in compare_line, compare_line


def scenario_textlist_rows_import(ctx):
    """A text-list row added and then removed takes the agent path both times."""
    ctx.load_objects()
    guid = ctx.guid("GlobalTextList")
    csv_path = ctx.file_of("GlobalTextList", ".csv")
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        content = handle.read()
    header = content.split("\n", 1)[0].strip()
    assert header == "TextID,TextDefault", "the fixture text list has languages: {0}".format(header)

    def ide_ids():
        return [row.get("TextID") for row in _ide_text_rows(guid) if row.get("TextID")]

    before = ide_ids()
    assert "213" not in before, before
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content.rstrip("\n") + "\n213,Stop\n")
    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert ide_ids() == before + ["213"], ide_ids()
    _assert_clean(ctx)

    # The removal: the csv as git has it, imported again.
    ctx.git("checkout", "--", csv_path)
    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert ide_ids() == before, ide_ids()
    _assert_clean(ctx)
    return "added and removed 213"


def scenario_visu_import(ctx):
    """A visualization's .xml (no text form) takes the agent path as one object."""
    ctx.load_objects()
    guid = ctx.guid("Visualization")
    xml_path = ctx.file_of("Visualization", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        xml = handle.read()
    # One member of the first element (its x position, keyed by its Id).
    old = '<Single Name="Id" Type="long">1473355128</Single>\n                    <Single Name="Value" Type="int">142</Single>'
    assert xml.count(old) == 1, "the fixture Visualization.xml does not hold member 1473355128 = 142"
    with open(xml_path, "w", encoding="utf-8") as handle:
        handle.write(xml.replace(old, old.replace(">142<", ">160<")))

    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line

    exported = _agent_call("objects.export", {"guids": [guid]})
    document = exported["objects"][0]["object"]
    assert '<Single Name="Value" Type="int">160</Single>' in document, "the IDE does not hold the new value"
    _assert_clean(ctx)
    return "member 142->160"


def scenario_import_without_base(ctx):
    """Without refs/cts/base the IDE is the base: an edit is written, a file
    gone from disk deletes nothing."""
    subprocess.run(["git", "update-ref", "-d", "refs/cts/base"], cwd=ctx.root, check=True)
    ctx.append_to_body("FB_Motor", "// live no-base edit")
    os.remove(ctx.st_path("GVL_Bench"))

    code, out, err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    # Every other file matches the IDE: nothing but the edit is written.
    assert "native=0" in line, line
    assert "updated FB_Motor" in out, out[:400]
    assert "deleted" not in out + err, (out + err)[:400]

    report = ctx.text_status()
    assert "FB_Motor" not in _names(report.get("changed") or []), report["changed"]
    # Still in the IDE, only its file is gone: with no base, compare names it as not in the view.
    kept = [item for item in report.get("changed") or [] if item.get("name") == "GVL_Bench"]
    assert kept and "not in the view" in kept[0].get("reason", ""), report
    return "written=FB_Motor kept=GVL_Bench"


def scenario_merge_import(ctx):
    """M_Toggle edited in the IDE and on disk at different lines: import merges both."""
    guid = ctx.guid("M_Toggle")
    texts = _agent_call("objects.texts", {"guids": [guid]})
    ide = [item for item in texts.get("objects") or [] if item.get("guid", "").strip("{}").lower() == guid.lower()]
    assert ide, texts
    original = ide[0]["implementation"]
    # The restore's import writes only what changed on disk; this edit is the IDE's own.
    ctx.cleanup_hooks.append(lambda: _agent_call("objects.settext", {"guid": guid, "implementation": original}))
    _agent_call("objects.settext", {"guid": guid, "implementation": original.rstrip() + "\n// ide edit"})
    st_path = ctx.st_path("M_Toggle")
    with open(st_path, encoding="utf-8") as handle:
        text = handle.read()
    with open(st_path, "w", encoding="utf-8") as handle:
        handle.write(text.replace("xOpen := NOT xOpen;", "// disk edit\nxOpen := NOT xOpen;"))

    code, out, _err = ctx.cts_ok("import")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok "), line
    assert "merged " in out, out
    with open(st_path, encoding="utf-8") as handle:
        merged = handle.read()
    assert "// disk edit" in merged and "// ide edit" in merged, merged
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    return "merged=1"


def scenario_merge_tool_ide_edit_import(ctx):
    """M_Toggle edited on one line in the IDE and on disk: `cts import --tool`
    opens the merge program, and while it is open the IDE's text changes once
    more.  The import is refused before it writes anything, so that edit is not
    lost; the next run with `--take ide` carries it to disk."""
    guid = ctx.guid("M_Toggle")
    texts = _agent_call("objects.texts", {"guids": [guid]})
    ide = [item for item in texts.get("objects") or [] if item.get("guid", "").strip("{}").lower() == guid.lower()]
    assert ide, texts
    original = ide[0]["implementation"]
    line = "xOpen := NOT xOpen;"
    assert line in original, original
    ctx.cleanup_hooks.append(lambda: _agent_call("objects.settext", {"guid": guid, "implementation": original}))
    _agent_call("objects.settext", {"guid": guid, "implementation": original.replace(line, line + " // ide edit")})
    st_path = ctx.st_path("M_Toggle")
    with open(st_path, encoding="utf-8") as handle:
        text = handle.read()
    with open(st_path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(line, line + " // disk edit"))
    # The merge program: the IDE edit someone makes while it is open, then
    # the right side saved as it is.
    tool = tempfile.mkdtemp(prefix="cts-live-tool-")
    ctx.cleanup_hooks.append(lambda: shutil.rmtree(tool, ignore_errors=True))
    ctx.cleanup_hooks.append(lambda: [ctx.git("config", "--unset", key) for key in ("merge.tool", "mergetool.kdiff3.path")])
    edit = cts_command() + ["raw", "objects.settext", "--guid", json.dumps(guid),
                            "--implementation", json.dumps(original.replace(line, line + " // late ide edit"))]
    with open(os.path.join(tool, "edit.json"), "w", encoding="utf-8") as handle:
        json.dump(edit, handle)
    with open(os.path.join(tool, "tool.py"), "w", encoding="utf-8") as handle:
        handle.write("import json, os, subprocess, sys\n"
                     "with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'edit.json'), encoding='utf-8') as handle:\n"
                     "    subprocess.run(json.load(handle), check=True, capture_output=True)\n"
                     "right = sys.argv[sys.argv.index('-o') + 1]\n"
                     "with open(right, 'rb') as handle:\n"
                     "    data = handle.read()\n"
                     "with open(right, 'wb') as handle:\n"
                     "    handle.write(data)\n")
    with open(os.path.join(tool, "tool.cmd"), "w", encoding="utf-8") as handle:
        handle.write('@"{0}" "{1}" %*\r\n'.format(sys.executable, os.path.join(tool, "tool.py")))
    ctx.git("config", "merge.tool", "kdiff3")
    ctx.git("config", "mergetool.kdiff3.path", os.path.join(tool, "tool.cmd"))

    code, out, err = ctx.cts("import", "--tool")
    assert code == 1 and "edited in the IDE since cts read it: M_Toggle" in out + err, (code, out, err)
    with open(st_path, encoding="utf-8") as handle:
        assert line + " // disk edit" in handle.read(), "the refused import wrote the file"
    texts = _agent_call("objects.texts", {"guids": [guid]})
    assert "// late ide edit" in texts["objects"][0]["implementation"], texts
    _code, out, _err = ctx.cts_ok("import", "--take", "ide")
    assert ctx.verdict(out).startswith("ok "), out
    with open(st_path, encoding="utf-8") as handle:
        carried = handle.read()
    assert line + " // late ide edit" in carried and "// disk edit" not in carried, carried
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    return "refused, then take ide"


def scenario_task_conflict_import(ctx):
    """Task.xml changed in the IDE and on disk since the base: a conflict, then --force."""
    ctx.load_objects()
    task_guid = ctx.guid("Task")
    xml_path = ctx.file_of("Task", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        original = handle.read()
    priority = '<Single Name="Priority" Type="string">1</Single>'
    assert priority in original, "the fixture Task.xml does not hold Priority 1"
    ctx.cleanup_hooks.append(lambda: _agent_call("objects.replace", {"guid": task_guid, "xml": original}))
    _agent_call("objects.replace", {"guid": task_guid, "xml": original.replace(priority, priority.replace(">1<", ">3<"))})
    with open(xml_path, "w", encoding="utf-8") as handle:
        handle.write(original.replace(priority, priority.replace(">1<", ">5<")))

    code, out, err = ctx.cts("import")
    assert code == 2, "a task changed on both sides was not a conflict: exit {0}\n{1}{2}".format(code, out, err)
    assert "conflict " in out and "Task.xml" in out, out
    code, out, _err = ctx.cts_ok("import", "--force")
    assert code == 0 and "overwrote-ide " in out, out
    return "conflict exit=2, then --force"


def _tree_node(name):
    """The node named ``name`` in the IDE tree, or None."""
    def find(node):
        for child in node.get("children") or []:
            found = child if child.get("name") == name else find(child)
            if found:
                return found
        return None
    return find(_agent_call("project.tree", {}))


def scenario_task_add_remove_import(ctx):
    """A copy of Task.xml under a new name is imported as a new task; removing the file deletes it."""
    ctx.load_objects()
    task_guid = ctx.guid("Task")
    xml_path = ctx.file_of("Task", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        original = handle.read()
    name = '<Single Name="Name" Type="string">Task</Single>'
    assert name in original, "the fixture Task.xml does not name its object Task"
    copy = os.path.join(os.path.dirname(xml_path), "Task_Live.xml")

    def cleanup():
        if os.path.exists(copy):
            os.remove(copy)
        node = _tree_node("Task_Live")
        if node:
            _agent_call("objects.delete", {"guid": node["guid"]})
    ctx.cleanup_hooks.append(cleanup)
    with open(copy, "w", encoding="utf-8") as handle:
        handle.write(original.replace(name, name.replace(">Task<", ">Task_Live<")))

    code, out, _err = ctx.cts_ok("import")
    assert code == 0 and "created-native Task_Live" in out, out
    node = _tree_node("Task_Live")
    assert node, "the imported task is not in the IDE tree"
    guid = str(node["guid"]).strip("{}").lower()
    assert guid != task_guid.lower(), "the copy kept the GUID of Task"
    with open(copy, encoding="utf-8-sig") as handle:
        assert guid in handle.read().lower(), "the file did not take the new task's GUID"
    os.remove(copy)
    code, out, _err = ctx.cts_ok("import")
    assert code == 0 and "deleted Task_Live" in out, out
    assert _tree_node("Task_Live") is None, "the task of the removed file is still in the IDE"
    return "created, then deleted"


def scenario_visu_copy_import(ctx):
    """A copy of Visualization.xml with its own size, in a folder the IDE
    lacks, is a new visualization in a new folder: the size property comes
    along, and the copy's elements name the new object."""
    ctx.load_objects()
    xml_path = ctx.file_of("Visualization", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        original = handle.read()
    name = '<Single Name="Name" Type="string">Visualization</Single>'
    size = '<Single Name="SizeX" Type="int">1024</Single>'
    assert name in original and size in original, "the fixture Visualization.xml changed"
    folder = os.path.join(os.path.dirname(xml_path), "Visus_Live")
    copy = os.path.join(folder, "Visu_Live.xml")
    body = os.path.join(ctx.root, ".git", "cts", "live-visu-copy.xml")
    os.makedirs(os.path.dirname(body), exist_ok=True)
    os.makedirs(folder, exist_ok=True)

    def cleanup():
        for path in (copy, body):
            if os.path.exists(path):
                os.remove(path)
        if os.path.isdir(folder):
            os.rmdir(folder)
        for name in ("Visu_Live", "Visus_Live"):
            node = _tree_node(name)
            if node:
                _agent_call("objects.delete", {"guid": node["guid"]})
    ctx.cleanup_hooks.append(cleanup)
    with open(copy, "w", encoding="utf-8") as handle:
        handle.write(original.replace(name, name.replace(">Visualization<", ">Visu_Live<"))
                     .replace(size, size.replace(">1024<", ">1280<")))

    code, out, _err = ctx.cts_ok("import")
    assert code == 0 and ctx.verdict(out).startswith("ok ") and "created-native Visus_Live" in out and "created-native Visu_Live" in out, out
    folder_node = _tree_node("Visus_Live")
    assert folder_node and [child.get("name") for child in folder_node.get("children") or []] == ["Visu_Live"], \
        folder_node
    ctx.cts_ok("read-object", "--path", "Application/Visu_Live", "--body-file", body)  # a folder is no parent
    with open(body, encoding="utf-8-sig") as handle:
        assert size.replace(">1024<", ">1280<") in handle.read(), "the copy lost its SizeX"
    report = ctx.json_of(ctx.cts_ok("compare", "--json")[1])
    modified = (report.get("objects") or report).get("modified") or []
    assert not any("Visu_Live" in str(item) for item in modified), modified
    os.remove(copy)
    code, out, _err = ctx.cts_ok("import")
    assert code == 0 and "deleted Visu_Live" in out, out
    return "created in a new folder with SizeX 1280, same as its file, then deleted"


def scenario_sync_to_disk(ctx):
    """M_Toggle edited in the IDE only: cts sync puts the edit into its file."""
    guid = ctx.guid("M_Toggle")
    texts = _agent_call("objects.texts", {"guids": [guid]})
    original = [item for item in texts.get("objects") or []
                if item.get("guid", "").strip("{}").lower() == guid.lower()][0]["implementation"]
    ctx.cleanup_hooks.append(lambda: _agent_call("objects.settext", {"guid": guid, "implementation": original}))
    _agent_call("objects.settext", {"guid": guid, "implementation": original.rstrip() + "\n// ide edit"})

    code, out, _err = ctx.cts_ok("sync")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok sync") and "to_disk=1" in line, out
    with open(ctx.st_path("M_Toggle"), encoding="utf-8") as handle:
        assert "// ide edit" in handle.read()
    report = ctx.text_status()
    assert not report["changed"], report["changed"]
    return "to_disk=1"


def scenario_sync_native_to_disk(ctx):
    """Task's priority changed in the IDE only: cts sync writes its .xml as cts export does."""
    ctx.load_objects()
    guid = ctx.guid("Task")
    xml_path = ctx.file_of("Task", ".xml")
    fields = _agent_call("objects.fields", {"guid": guid}).get("fields") or {}
    original = str(fields.get("Priority"))
    ctx.cleanup_hooks.append(lambda: _agent_call("objects.setfield", {"guid": guid, "path": "Priority",
                                                                      "value": original}))
    _agent_call("objects.setfield", {"guid": guid, "path": "Priority", "value": "9"})

    code, out, _err = ctx.cts_ok("sync")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok sync") and "to_disk=1" in line, out
    with open(xml_path, encoding="utf-8") as handle:
        synced = handle.read()
    assert '<Single Name="Priority" Type="string">9</Single>' in synced, "the IDE's priority is not on disk"
    _code, compare_out, _err = ctx.cts_ok("compare")
    compare_line = ctx.verdict(compare_out)
    assert compare_line.startswith("ok ") and "modified=0" in compare_line and "ide_changed" not in compare_line, \
        compare_line
    ctx.cts_ok("export")
    with open(xml_path, encoding="utf-8") as handle:
        assert handle.read() == synced, "cts export writes the task's .xml differently from cts sync"
    return "to_disk=1 same-as-export"


def scenario_sync_new_in_ide(ctx):
    """A GVL created in the IDE only and a method added to a POU on disk:
    cts sync writes the GVL's file and puts the method into the POU's, compare agrees."""
    before = ctx.text_status()["same"]

    def application(node):
        for child in node.get("children") or []:
            found = child if child.get("name") == "Application" else application(child)
            if found:
                return found
        return None

    parent = application(_agent_call("project.tree", {}))
    assert parent, "the live project has no Application"
    ctx.cleanup_hooks.append(lambda: _delete_in_ide("GVL_LiveIde"))
    _agent_call("objects.create", {"kind": "gvl", "name": "GVL_LiveIde", "parent_guid": parent["guid"],
                                   "declaration": "VAR_GLOBAL\n\tlive_ide : BOOL;\nEND_VAR"})
    ctx.cleanup_hooks.append(lambda: _delete_in_ide("M_LiveIde"))
    _agent_call("objects.create", {"kind": "method", "name": "M_LiveIde", "parent_guid": ctx.guid("FB_Valve"),
                                   "declaration": "METHOD M_LiveIde : BOOL", "implementation": "M_LiveIde := TRUE;"})

    code, out, _err = ctx.cts_ok("sync")
    line = ctx.verdict(out)
    assert code == 0 and line.startswith("ok sync") and "to_disk=2" in line, out
    written = [part.strip()[len("IDE -> disk "):] for part in out.splitlines() if part.strip().startswith("IDE -> disk ")]
    gvl = [path for path in written if path.endswith("/GVL_LiveIde")]
    assert len(written) == 2 and gvl and any(path.endswith("/FB_Valve/M_LiveIde") for path in written), out
    # The line names the object's tree path; its file is in the folder the
    # disk spells, beside FB_Valve's.
    with open(os.path.join(os.path.dirname(ctx.st_path("FB_Valve")), "GVL_LiveIde.st"), encoding="utf-8") as handle:
        assert "live_ide : BOOL;" in handle.read()
    with open(ctx.st_path("FB_Valve"), encoding="utf-8") as handle:
        assert "METHOD M_LiveIde : BOOL" in handle.read(), "the new method is not in the POU's file"
    report = ctx.text_status()
    assert not report["changed"] and not report.get("ide_only") and not report.get("disk_only"), report
    assert report["same"] == before + 2, report["same"]
    return "same={0}->{1} to_disk=2".format(before, report["same"])


def scenario_import_force_ide_only(ctx):
    """Objects only the IDE has: an action under a POU the disk holds, and a
    folder with a GVL in it.  compare names them, cts import --force deletes
    them, and compare is back where it started."""
    before = ctx.text_status()["same"]
    application = _tree_node("Application")
    assert application, "the live project has no Application"
    ctx.cleanup_hooks.append(lambda: _delete_in_ide("A_LiveIde"))
    _agent_call("objects.create", {"kind": "action", "name": "A_LiveIde", "parent_guid": ctx.guid("FB_Valve"),
                                   "implementation": "xOpen := TRUE;"})
    ctx.cleanup_hooks.append(lambda: _delete_in_ide("LiveIdeFolder"))
    folder = _agent_call("objects.create", {"kind": "folder", "name": "LiveIdeFolder",
                                            "parent_guid": application["guid"]})
    _agent_call("objects.create", {"kind": "gvl", "name": "GVL_InLiveFolder", "parent_guid": folder["guid"],
                                   "declaration": "VAR_GLOBAL\n\tin_live_folder : BOOL;\nEND_VAR"})

    _code, out, _err = ctx.cts("compare")
    for name in ("A_LiveIde", "GVL_InLiveFolder"):
        assert name in out, "compare does not name {0}:\n{1}".format(name, out)
    _code, out, _err = ctx.cts_ok("import", "--force")
    for name in ("A_LiveIde", "LiveIdeFolder", "GVL_InLiveFolder"):
        assert _tree_node(name) is None, "import --force left {0} in the IDE:\n{1}".format(name, out)
    report = ctx.text_status()
    assert not report["changed"] and not report["ide_only"] and not report["disk_only"], report
    assert report["same"] == before, (before, report["same"])
    return "action, folder and its GVL deleted, same={0}".format(before)



def scenario_member_folder_import(ctx):
    """A method in a folder below its POU: cts sync writes the folder into the
    pragma line above it, and an import of its edited text with another folder
    in that line writes the text and moves it there, the folder made first."""
    ctx.load_objects()
    valve, toggle = ctx.guid("FB_Valve"), ctx.guid("M_Toggle")

    def put_back():
        _agent_call("objects.move", {"guid": toggle, "parent_guid": valve})
        for name in ("LiveMembers", "LiveOther"):
            _delete_in_ide(name)
    ctx.cleanup_hooks.append(put_back)
    folder = _agent_call("objects.create", {"kind": "folder", "name": "LiveMembers", "parent_guid": valve})
    _agent_call("objects.move", {"guid": toggle, "parent_guid": folder["guid"]})

    ctx.cts_ok("sync")
    path = ctx.st_path("M_Toggle")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert '(* cds-text-sync: Folder="LiveMembers" *)\nMETHOD M_Toggle' in text, text
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text.replace('Folder="LiveMembers"', 'Folder="LiveOther"').replace("M_Toggle := xOpen;", "M_Toggle := xOpen; // live runner"))
    _code, out, _err = ctx.cts_ok("import")
    assert ctx.verdict(out).startswith("ok import text=1"), out
    other = _tree_node("LiveOther")
    assert other and any(child.get("guid") == toggle for child in other.get("children") or []), other
    assert "// live runner" in _agent_call("objects.text", {"guid": toggle})["implementation"]
    report = ctx.text_status()
    assert not report["changed"] and not report["ide_only"] and not report["disk_only"], report
    return "M_Toggle LiveMembers -> LiveOther, text carried"


_LIVE_TOOL = (
    "import os, sys\n"
    "rows = []\n"
    "for side, top in (('L', sys.argv[1]), ('R', sys.argv[2])):\n"
    "    for here, _dirs, names in os.walk(top):\n"
    "        rows += [side + ' ' + os.path.relpath(os.path.join(here, n), top).replace(os.sep, '/') for n in names]\n"
    "open(sys.argv[3], 'w').write('\\n'.join(sorted(rows)))\n"
)

def scenario_compare_tool(ctx):
    """`cts compare --tool` with a difftool chosen opens nothing on a clean project, then the diff
    tool with the IDE's F_Scale left and the edited file right."""
    work = tempfile.mkdtemp(prefix="cts-live-difftool-")
    script, seen = os.path.join(work, "tool.py"), os.path.join(work, "seen.txt")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(_LIVE_TOOL)
    ctx.cleanup_hooks.append(lambda: shutil.rmtree(work, ignore_errors=True))
    ctx.cleanup_hooks.append(lambda: ctx.git("config", "--remove-section", "difftool.ctslive"))
    ctx.cleanup_hooks.append(lambda: ctx.git("config", "--unset", "diff.tool"))
    ctx.git("config", "difftool.ctslive.cmd", '"{0}" "{1}" "$LOCAL" "$REMOTE" "{2}"'.format(
        *(path.replace("\\", "/") for path in (sys.executable, script, seen))))
    ctx.git("config", "diff.tool", "ctslive")

    _code, out, _err = ctx.cts_ok("compare", "--tool")
    line = ctx.verdict(out)
    assert line.startswith("ok compare tool=ctslive files=0"), line
    st_path = ctx.append_to_body("F_Scale", "// live runner: compare tool")
    _code, out, _err = ctx.cts_ok("compare", "--tool")
    line = ctx.verdict(out)
    assert line.startswith("ok compare tool=ctslive files=1"), line
    deadline = time.monotonic() + 30
    while not (os.path.exists(seen) and os.path.getsize(seen)) and time.monotonic() < deadline:
        time.sleep(0.2)
    with open(seen, encoding="utf-8") as handle:
        rows = handle.read().splitlines()
    relative = os.path.relpath(st_path, ctx.root).replace(os.sep, "/")
    assert rows == ["L " + relative, "R " + relative], rows
    return "clean opened nothing, then {0} both sides".format(relative)


def scenario_base_moved_outside(ctx):
    """A sync base moved outside cts stops compare and export; put back, it is clean."""
    ctx.cts_ok("compare")   # reads the base, so cts holds it as its own
    own = ctx.git("rev-parse", "refs/cts/base").stdout.strip()
    ctx.cleanup_hooks.append(lambda: ctx.git("update-ref", "refs/cts/base", own))
    ctx.git("update-ref", "refs/cts/base", "HEAD")
    for command in ("compare", "export"):
        code, out, err = ctx.cts(command)
        assert code == 1 and "refs/cts/base was moved outside cts" in out + err, (command, out, err)
    ctx.git("update-ref", "refs/cts/base", own)
    _assert_clean(ctx)
    return "compare and export refused, clean once put back"


def scenario_branch_checkout(ctx):
    """`cts branch` makes a branch whose commit changes F_Scale and adds a GVL;
    `cts checkout` refuses an unsynced or uncommitted state, then carries the
    switch into the IDE both ways and saves, and saves nothing when no object
    changes."""
    start = ctx.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    ctx.cleanup_hooks.append(lambda: _leave_branch(ctx, start))
    _code, out, _err = ctx.cts_ok("branch", "live-checkout")
    assert ctx.verdict(out).startswith("ok branch branch=live-checkout"), ctx.verdict(out)
    ctx.append_to_body("F_Scale", "// live runner: checkout")
    ctx.cts_ok("new", "gvl", "GVL_LiveCheckout", "--text", "x : BOOL;", "--sync-folder", ctx.root)
    ctx.git("add", "-A", "project-view")
    ctx.git("-c", "user.name=cts", "-c", "user.email=cts@localhost", "commit", "-q", "-m", "live checkout")

    code, out, err = ctx.cts("checkout", start)
    assert code == 1 and "differ" in out + err, ctx.verdict(out)
    _code, out, _err = ctx.cts_ok("import")
    assert "created=1" in ctx.verdict(out), ctx.verdict(out)
    ctx.append_to_body("F_Scale", "// live runner: uncommitted")
    code, out, err = ctx.cts("checkout", start)
    assert code == 1 and "uncommitted" in out + err, ctx.verdict(out)
    ctx.git("checkout", "--", "project-view")

    _code, out, _err = ctx.cts_ok("checkout", start)
    back = ctx.verdict(out)
    assert back.startswith("ok checkout branch={0}".format(start)), back
    assert "deleted=1" in back and "saved=true" in back, back
    _assert_clean(ctx)
    assert "live runner" not in _agent_call("objects.text", {"guid": ctx.guid("F_Scale")}).get("implementation", "")

    _code, out, _err = ctx.cts_ok("checkout", "live-checkout")
    there = ctx.verdict(out)
    assert there.startswith("ok checkout branch=live-checkout") and "created=1" in there, there
    _assert_clean(ctx)

    _code, out, _err = ctx.cts_ok("checkout", start)
    assert "deleted=1" in ctx.verdict(out), ctx.verdict(out)
    _assert_clean(ctx)

    # The same commit, detached: no object changes, so nothing is saved.
    _code, out, _err = ctx.cts_ok("checkout", ctx.git("rev-parse", "HEAD").stdout.strip())
    same = ctx.verdict(out)
    assert "branch=detached" in same and "saved=false" in same, same
    ctx.git("switch", start)
    return "{0} -> live-checkout -> {0}, same commit unsaved".format(start)


def _task_priority(ctx):
    fields = _agent_call("objects.fields", {"guid": ctx.guid("Task")})
    return str(((fields or {}).get("fields") or {}).get("Priority"))


def scenario_branch_checkout_native(ctx):
    """A branch whose commit changes the task's priority (Task.xml, an object
    with no text form): `cts checkout` carries it into the IDE both ways."""
    start = ctx.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    ctx.load_objects()
    xml_path = ctx.file_of("Task", ".xml")
    with open(xml_path, encoding="utf-8-sig") as handle:
        original = handle.read()
    ctx.cleanup_hooks.append(lambda: _leave_native_branch(ctx, start, original))
    priority = '<Single Name="Priority" Type="string">1</Single>'
    assert priority in original, "the fixture Task.xml does not hold Priority 1"
    ctx.cts_ok("branch", "live-native")
    with open(xml_path, "w", encoding="utf-8") as handle:
        handle.write(original.replace(priority, priority.replace(">1<", ">5<")))
    ctx.cts_ok("import")
    ctx.git("add", "-A", "project-view")
    ctx.git("-c", "user.name=cts", "-c", "user.email=cts@localhost", "commit", "-q", "-m", "live native")
    assert _task_priority(ctx) == "5"

    _code, out, _err = ctx.cts_ok("checkout", start)
    back = ctx.verdict(out)
    assert back.startswith("ok checkout branch={0}".format(start)) and "saved=true" in back, back
    assert _task_priority(ctx) == "1", _task_priority(ctx)
    _assert_clean(ctx)

    _code, out, _err = ctx.cts_ok("checkout", "live-native")
    assert ctx.verdict(out).startswith("ok checkout branch=live-native"), ctx.verdict(out)
    assert _task_priority(ctx) == "5", _task_priority(ctx)
    _assert_clean(ctx)

    ctx.cts_ok("checkout", start)
    assert _task_priority(ctx) == "1", _task_priority(ctx)
    return "priority 5 on live-native, 1 on {0}".format(start)


def _leave_native_branch(ctx, start, original):
    """Back on ``start`` without the branch; the IDE's task as the fixture has it."""
    ctx.git("switch", "-f", start)
    ctx.git("branch", "-D", "live-native")
    _agent_call("objects.replace", {"guid": ctx.guid("Task"), "xml": original})


def scenario_commit(ctx):
    """M_Toggle edited in the IDE only: `cts commit` commits the disk as it
    is and warns that the IDE differs; after `cts sync` carries the edit into
    its file, it commits it on a branch with a tag; a second commit finds nothing,
    `cts log` lists it, and `cts checkout` of the start branch takes the edit
    out of the IDE."""
    start = ctx.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    ctx.cleanup_hooks.append(lambda: _leave_commit(ctx, start))
    ctx.cts_ok("branch", "live-commit")
    guid = ctx.guid("M_Toggle")
    texts = _agent_call("objects.texts", {"guids": [guid]})
    original = [item for item in texts.get("objects") or []
                if item.get("guid", "").strip("{}").lower() == guid.lower()][0]["implementation"]
    _agent_call("objects.settext", {"guid": guid, "implementation": original.rstrip() + "\n// live runner: commit"})

    _code, out, err = ctx.cts_ok("commit", "-m", "before the sync")
    line = ctx.verdict(out)
    assert "files=0" in line and "ide_differs=1" in line, line
    assert "the IDE and the disk differ in 1 object(s)" in out + err, out + err
    ctx.cts_ok("sync")
    _code, out, _err = ctx.cts_ok("commit", "-m", "live commit", "--tag", "live-commit-tag")
    line = ctx.verdict(out)
    assert line.startswith("ok commit branch=live-commit") and "files=1" in line and "ide_differs" not in line, line
    assert "tag=live-commit-tag" in line, line
    committed = [path for path in ctx.git("show", "--name-only", "--format=", "HEAD").stdout.splitlines() if path]
    assert os.path.basename(ctx.st_path("M_Toggle")) in [path.rsplit("/", 1)[-1] for path in committed], committed
    assert ctx.git("log", "-1", "--format=%s").stdout.strip() == "live commit"
    _code, out, _err = ctx.cts_ok("commit", "-m", "nothing")
    assert "files=0" in ctx.verdict(out), ctx.verdict(out)
    _code, out, _err = ctx.cts_ok("log", "-n", "2")
    assert ctx.verdict(out).startswith("ok log branch=live-commit") and "commits=2" in ctx.verdict(out), out
    assert " live commit (HEAD, live-commit, tag: live-commit-tag)" in out, out

    _code, out, _err = ctx.cts_ok("checkout", start)
    assert ctx.verdict(out).startswith("ok checkout branch={0}".format(start)), ctx.verdict(out)
    _assert_clean(ctx)
    assert "live runner" not in _agent_call("objects.text", {"guid": guid}).get("implementation", "")
    return "files={0} tagged, then files=0, back on {1}".format(len(committed), start)


def _leave_commit(ctx, start):
    """Back on ``start`` without the scenario's branch and tag."""
    ctx.git("switch", "-f", start)
    ctx.git("branch", "-D", "live-commit")
    ctx.git("tag", "-d", "live-commit-tag")


def scenario_project_update(ctx):
    """The owner's `cts project update`: refused while the branch has no
    upstream, then pulls a team commit (F_Scale) from a bare remote, imports
    it and saves; `cts checkout` of the start branch takes it out again."""
    start = ctx.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    remote = tempfile.mkdtemp(prefix="cts-live-remote-")
    ctx.cleanup_hooks.append(lambda: _leave_update(ctx, start, remote))
    ctx.cts_ok("branch", "live-update")
    code, out, err = ctx.cts("project", "update")
    assert code == 1 and "no upstream" in out + err, ctx.verdict(out)

    subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
    ctx.git("remote", "add", "live-remote", remote)
    # The pushes set the scene, the hook is not under test: git-lfs in it
    # fails on a fixture kept on some virtual drives.
    _push(ctx, "-u", "live-remote", "live-update")
    # The team's commit: on the remote only, this PC one commit behind it.
    ctx.append_to_body("F_Scale", "// live runner: team update")
    ctx.git("add", "-A", "project-view")
    ctx.git("-c", "user.name=cts", "-c", "user.email=cts@localhost", "commit", "-q", "-m", "live team update")
    _push(ctx, "live-remote", "live-update")
    ctx.git("reset", "-q", "--keep", "HEAD~1")
    _assert_clean(ctx)

    _code, out, _err = ctx.cts_ok("project", "update")
    line = ctx.verdict(out)
    assert line.startswith("ok project-update branch=live-update"), line
    assert "pulled=true" in line and "saved=true" in line, line
    _assert_clean(ctx)
    assert "live runner: team update" in _agent_call("objects.text", {"guid": ctx.guid("F_Scale")}).get("implementation", "")

    _code, out, _err = ctx.cts_ok("checkout", start)
    assert ctx.verdict(out).startswith("ok checkout branch={0}".format(start)), ctx.verdict(out)
    _assert_clean(ctx)
    return "refused without upstream, pulled and imported F_Scale, back on {0}".format(start)


def _push(ctx, *args):
    pushed = ctx.git("push", "-q", "--no-verify", *args)
    assert pushed.returncode == 0, pushed.stderr


def _leave_update(ctx, start, remote):
    """Back on ``start`` without the scenario's branch and remote."""
    ctx.git("switch", "-f", start)
    ctx.git("branch", "-D", "live-update")
    ctx.git("remote", "remove", "live-remote")
    shutil.rmtree(remote, ignore_errors=True)


def _leave_branch(ctx, start):
    """Back on ``start`` without the scenario's branch; the IDE's GVL goes too."""
    ctx.git("switch", "-f", start)
    ctx.git("branch", "-D", "live-checkout")
    _delete_in_ide("GVL_LiveCheckout")


SCENARIOS = [
    ("compare_clean", scenario_compare_clean),
    ("read_object_body", scenario_read_object_body),
    ("import_text_via_agent", scenario_import_text_via_agent),
    ("export_fast", scenario_export_fast),
    ("rename_import", scenario_rename_import),
    ("member_folder_import", scenario_member_folder_import),
    ("task_import", scenario_task_import),
    ("task_conflict_import", scenario_task_conflict_import),
    ("task_add_remove_import", scenario_task_add_remove_import),
    ("visu_copy_import", scenario_visu_copy_import),
    ("textlist_import", scenario_textlist_import),
    ("textlist_rows_import", scenario_textlist_rows_import),
    ("visu_import", scenario_visu_import),
    ("meta_property_import", scenario_meta_property_import),
    ("import_refused_online", scenario_import_refused_online),
    ("vars_online", scenario_vars_online),
    ("snapshooter_online", scenario_snapshooter_online),
    ("sync_folder_set", scenario_sync_folder_set),
    ("simulation_toggle", scenario_simulation_toggle),
    ("build_errors", scenario_build_errors),
    ("build_all_objects", scenario_build_all_objects),
    ("library_build", scenario_library_build),
    ("boot_app_online", scenario_boot_app_online),
    ("reset_online", scenario_reset_online),
    ("plc_crc_online", scenario_plc_crc_online),
    ("download_online", scenario_download_online),
    ("st_tests_simulation", scenario_st_tests_simulation),
    ("connect_keeps_plc", scenario_connect_keeps_plc),
    ("plc_files_online", scenario_plc_files_online),
    ("plc_log_online", scenario_plc_log_online),
    ("devices_online", scenario_devices_online),
    ("project_reopen", scenario_project_reopen),
    ("permissions_read", scenario_permissions_read),
    ("new_method_import", scenario_new_method_import),
    ("new_pou_import", scenario_new_pou_import),
    ("new_dut_import", scenario_new_dut_import),
    ("new_member_import", scenario_new_member_import),
    ("new_interface_import", scenario_new_interface_import),
    ("new_gvl_import", scenario_new_gvl_import),
    ("new_gvl_import_twice", scenario_new_gvl_import_twice),
    ("new_folder_import", scenario_new_folder_import),
    ("root_import", scenario_root_import),
    ("delete_import", scenario_delete_import),
    ("import_without_base", scenario_import_without_base),
    ("merge_import", scenario_merge_import),
    ("merge_tool_ide_edit_import", scenario_merge_tool_ide_edit_import),
    ("sync_to_disk", scenario_sync_to_disk),
    ("sync_native_to_disk", scenario_sync_native_to_disk),
    ("sync_new_in_ide", scenario_sync_new_in_ide),
    ("import_force_ide_only", scenario_import_force_ide_only),
    ("base_moved_outside", scenario_base_moved_outside),
    ("compare_tool", scenario_compare_tool),
    ("branch_checkout", scenario_branch_checkout),
    ("branch_checkout_native", scenario_branch_checkout_native),
    ("commit", scenario_commit),
    ("project_update", scenario_project_update),
]


# -- prechecks and main ------------------------------------------------------


def precheck(ctx):
    """One line saying why the runner cannot start, or None when it can."""
    if not os.path.isdir(os.path.join(ctx.root, "project-view")):
        return "{0} has no project-view/; is CTS_LIVE_PROJECT the project root?".format(ctx.root)

    code, out, err = ctx.cts("status", "--json")
    if code != 0:
        first = (err or out).strip().splitlines() or [""]
        return "cts status failed ({0}): {1}".format(code, first[0])

    status = ctx.json_of(out)
    project_file = (status.get("instance") or {}).get("project", {}).get("path") \
        or status.get("project") or ""
    if not project_file:
        return "no project is open in the IDE; open it with the agent running"

    root_key = os.path.normcase(os.path.normpath(ctx.root)).rstrip("\\/") + os.sep
    if not os.path.normcase(os.path.normpath(project_file)).startswith(root_key):
        return "the IDE has a different project open: {0} (expected one under {1})".format(
            project_file, ctx.root
        )

    if (status.get("plc") or {}).get("online") is True:
        return "the IDE is online with the PLC; run `cts disconnect` first"

    dirty = ctx.git("status", "--porcelain").stdout.strip()
    if dirty:
        return "the project has uncommitted changes; scenarios restore the disk with git"

    ctx.load_objects()
    for name in ("F_Scale", "GVL_Fixture"):
        ctx.st_path(name)   # raises LiveError with a clear message
    return None


def run_scenario(ctx, name, function):
    """Run one scenario and return ``(passed, seconds, detail, failed_call)``.

    The restore runs in ``finally`` whatever the scenario did -- an assertion,
    a timeout in `cts`, or a crash -- so a failed scenario still leaves the
    project as it found it.
    """
    started = time.time()
    failed_call = None
    try:
        detail = function(ctx)
        passed = True
    except Exception as error:  # noqa: BLE001 -- a scenario reports, never crashes the run
        passed = False
        detail = str(error).replace("\n", " ")[:200]
        failed_call = ctx.last   # restore below runs more commands
    finally:
        try:
            ctx.restore()
        except Exception as error:  # noqa: BLE001
            if passed:
                passed, detail = False, "restore failed: {0}".format(error).replace("\n", " ")[:200]
                failed_call = ctx.last
    return passed, time.time() - started, detail, failed_call


def report_failure(name, failed_call):
    """The command that failed and its output: the first lines, and for a
    traceback the last ones too, where the exception is."""
    if not failed_call:
        return
    argv, _code, out, err = failed_call
    print("  FAIL {0}: $ {1}".format(name, " ".join(argv)))
    lines = (out + err).splitlines()
    shown = lines[:5]
    if len(lines) > 5 and any(line.startswith("Traceback") for line in shown):
        shown += ["..."] + lines[max(5, len(lines) - 8):]
    for line in shown:
        print("    | {0}".format(line))


def main(argv):
    root = os.environ.get("CTS_LIVE_PROJECT", "").strip()
    if not root:
        print("CTS_LIVE_PROJECT is not set: point it at the project root open in CODESYS")
        return 2
    ctx = Context(os.path.abspath(root))

    try:
        problem = precheck(ctx)
    except LiveError as error:
        problem = str(error)
    if problem:
        print(problem)
        return 2

    wanted = argv[1:]
    selected = [(name, fn) for name, fn in SCENARIOS if not wanted or name in wanted]
    if not selected:
        print("no such scenario: {0}".format(", ".join(wanted)))
        print("scenarios: {0}".format(", ".join(name for name, _ in SCENARIOS)))
        return 2

    results = []
    for name, function in selected:
        results.append((name,) + run_scenario(ctx, name, function))

    print("")
    for name, passed, seconds, detail, failed_call in results:
        print("{0:<24} {1:<5} {2:>6.1f}s  {3}".format(name, "PASS" if passed else "FAIL", seconds, detail))
        if not passed:
            report_failure(name, failed_call)
    passed_count = sum(1 for _n, ok, _s, _d, _f in results if ok)
    print("{0:<24} {1:<5} {2:>6.1f}s  {3} of {4} passed".format(
        "total", "PASS" if passed_count == len(results) else "FAIL",
        sum(s for _n, _o, s, _d, _f in results), passed_count, len(results),
    ))
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
