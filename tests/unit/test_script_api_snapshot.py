# -*- coding: utf-8 -*-
"""test_script_api_snapshot.py — the scripting-API snapshot and its checker.

``tools/script_api_snapshot.py`` turns decompiled CODESYS sources into
``products/codesys-host/api/scriptengine_api.json`` (names and declarations only),
and ``tools/check_script_api.py`` verifies that every ``system``/``online``/
``projects``/``oa``/``device``/``app`` member the bridge calls exists in it.

The point of the pair is ``cts read-log``: a call that is wrong by name only fails
on the live stand.  These tests pin the contract:

* the generator keeps properties (``bool ui_present { get; }`` ends with ``}``,
  not ``;`` -- the first cut dropped every property, and with it ``projects.primary``);
* versions of one interface (``ISystem``, ``ISystem2``, ...) land in one family;
* the checker knows ``is_simulation_mode`` is ``get_simulation_mode``;
* it does not flag inherited ``System.Object`` members used for reflection;
* the committed snapshot is well-formed and covers what the bridge calls;
* the bridge is clean except for the mismatches already reviewed in the tool.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SNAPSHOT = _ROOT / "products" / "codesys-host" / "api" / "scriptengine_api.json"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, str(_ROOT / relative))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generator():
    return _load("script_api_snapshot_under_test", "tools/script_api_snapshot.py")


def _checker():
    return _load("check_script_api_under_test", "tools/check_script_api.py")


SOURCE = """
namespace _3S.CoDeSys.ScriptEngine.BasicFunctionality;

[ReleasedInterface]
public interface ISystem
{
\tbool trace { get; set; }
\tvoid exit([Optional] int exitcode);
\tIList<string> get_messages(Guid category);
}

public interface ISystem2 : ISystem
{
\tIList<string> get_messages(string category);
\tstring profile { get; }
}

public sealed class NotAnInterface
{
\tpublic void call_me() { }
}
"""


def test_generator_keeps_properties_methods_and_events():
    module = _generator()
    members = {
        (member, declaration)
        for _, member, declaration in module.parse_interfaces(SOURCE)
    }
    names = {member for member, _ in members}
    assert {"trace", "exit", "get_messages", "profile"} <= names
    # The property is kept with its declaration, so a reader sees the signature.
    assert any(decl.startswith("string profile") for _, decl in members)
    # A class body is not an interface and must not be parsed.
    assert "call_me" not in names


def test_generator_merges_interface_versions_into_one_family():
    module = _generator()
    assert module.family_of("ISystem") == "ISystem"
    assert module.family_of("ISystem2") == "ISystem"
    assert module.family_of("IScriptProject13") == "IScriptProject"
    assert module.family_of("IScriptProjectArchiveCategories") == "IScriptProjectArchiveCategories"


def test_snapshot_versions_sort_naturally():
    module = _generator()
    names = ["ISystem10", "ISystem2", "ISystem"]
    assert sorted(names, key=module._version_key) == ["ISystem", "ISystem2", "ISystem10"]


def test_the_committed_snapshot_is_well_formed():
    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert set(snapshot) == {"note", "families"}
    families = snapshot["families"]
    assert families, "the snapshot must not be empty"
    for family, data in families.items():
        assert set(data) == {"types", "members"}, family
        # A family is named after its unversioned interface, which may itself be a
        # marker with no members, so only the versioned list must be present.
        assert data["types"], family
        assert all(t.startswith(family) for t in data["types"]), family
        for member, declarations in data["members"].items():
            assert isinstance(member, str) and member
            assert declarations and all(isinstance(d, str) for d in declarations)
    # No method bodies: nothing may contain a C# statement terminator inside braces.
    assert "'" not in json.dumps(snapshot)


def test_the_snapshot_covers_what_the_bridge_calls():
    families = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["families"]
    expected = {
        "ISystem": {"get_messages", "get_message_objects", "clear_messages", "ui", "commands"},
        "IScriptOnline": {"create_online_application", "create_online_device"},
        "IScriptProjects": {"primary", "open"},
        "IScriptOnlineApplication": {
            "application",
            "application_state",
            "read_value",
            "start",
            "stop",
            "reset",
            "create_boot_application",
            "source_download",
        },
        "IScriptObject": {"get_name"},
        "IScriptApplication": {"build"},
        "IScriptTreeObject": {"get_children"},
        "IScriptDeviceObject": {"get_simulation_mode", "set_simulation_mode"},
    }
    for family, members in expected.items():
        assert family in families, family
        assert members <= set(families[family]["members"]), family


def test_the_checker_accepts_a_member_that_exists_and_flags_one_that_does_not(tmp_path):
    module = _checker()
    snapshot = {
        "families": {
            "ISystem": {"types": ["ISystem"], "members": {"get_messages": ["x"]}},
            "IScriptOnline": {"types": ["IScriptOnline"], "members": {}},
        }
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    source = tmp_path / "sample.py"
    source.write_text(
        "system.get_messages('x')\nsystem.get_messags('x')\n",
        encoding="utf-8",
    )
    findings = module.check([str(source)], str(path))
    assert [(receiver, member) for _, _, receiver, member in findings] == [("system", "get_messags")]


def test_the_checker_knows_the_is_get_spelling(tmp_path):
    module = _checker()
    snapshot = {
        "families": {
            "IScriptDeviceObject": {
                "types": ["IScriptDeviceObject"],
                "members": {"get_simulation_mode": ["x"], "set_simulation_mode": ["y"]},
            },
            "IScriptTreeObject": {"types": ["IScriptTreeObject"], "members": {}},
        }
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    source = tmp_path / "sample.py"
    source.write_text("device.is_simulation_mode\ndevice.set_simulation_mode(True)\n", encoding="utf-8")
    assert module.check([str(source)], str(path)) == []


def test_the_checker_ignores_system_object_members(tmp_path):
    module = _checker()
    snapshot = {"families": {"IScriptOnline": {"types": [], "members": {}}}}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    source = tmp_path / "sample.py"
    source.write_text("online.GetType()\n", encoding="utf-8")
    assert module.check([str(source)], str(path)) == []


def test_the_known_mismatches_are_empty_and_the_ratchet_holds():
    """The one entry was a real bug, and the product fix removed it.

    ``projects.close(prj)`` in _cmd_project_close called a method
    IScriptProjects does not have; the handler now says so instead. The map
    stays as the escape hatch -- if a call must stay for a reason, it goes here
    with that reason, and this test is what makes deleting the entry the last
    step of fixing it.
    """
    module = _checker()
    assert module.KNOWN_MISMATCHES == {}
    for key, reason in module.KNOWN_MISMATCHES.items():
        assert len(reason) > 40, key
    # The bridge today has no unreviewed call; a new one would show up here.
    assert module.check([]) == []


def test_the_receiver_map_only_names_unambiguous_variables():
    module = _checker()
    assert module.RECEIVERS
    for receiver, families in module.RECEIVERS.items():
        assert receiver.isidentifier(), receiver
        assert families and all(f.startswith("I") for f in families)


def test_ci_product_checks_runs_the_scripting_api_check(monkeypatch, capsys):
    """`all` must run it: 0.2 s, and the alternative is a failure at the stand."""
    import sys as _sys

    _sys.path.insert(0, str(_ROOT / "tools"))
    import ci_product_checks

    monkeypatch.setattr(_sys, "argv", ["ci_product_checks.py", "scriptapi"])
    ci_product_checks.main()

    assert "script API check" in capsys.readouterr().out
