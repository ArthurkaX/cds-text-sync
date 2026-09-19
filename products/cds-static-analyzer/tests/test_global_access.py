"""Contract tests for the shared global read/write capability."""

from cds_static_analyzer import project
from cds_static_analyzer.global_access import GlobalAccessIndex
from cds_static_analyzer.project import ProjectSnapshot


def _unit(path, text):
    return project._build_st_unit(path, text)


def test_global_access_resolves_qualified_bare_and_struct_field_paths():
    gvl = _unit(
        "Globals.st",
        "VAR_GLOBAL\n"
        "    Shared : INT;\n"
        "    State : Data;\n"
        "END_VAR\n",
    )
    program = _unit(
        "Main.st",
        "PROGRAM Main\nIMPLEMENTATION\n"
        "Globals.Shared := 1;\n"
        "Shared := Globals.State.Field;\n",
    )

    accesses = GlobalAccessIndex(ProjectSnapshot(".", [gvl, program])).accesses_for(program)

    assert [(access.target, access.write) for access in accesses] == [
        ("Globals.Shared", True),
        ("Shared", True),
        ("Globals.State.Field", False),
    ]
    assert [access.confidence for access in accesses] == ["high", "medium", "high"]


def test_global_access_does_not_cross_local_shadowing_or_ambiguous_bare_names():
    first = _unit("One.st", "VAR_GLOBAL\n    Shared : INT;\nEND_VAR\n")
    second = _unit("Two.st", "VAR_GLOBAL\n    Shared : INT;\nEND_VAR\n")
    local = _unit(
        "Main.st",
        "PROGRAM Main\nVAR\n    Shared : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nShared := 1;\nOne.Shared := 2;\n",
    )

    accesses = GlobalAccessIndex(ProjectSnapshot(".", [first, second, local])).accesses_for(local)

    assert [(access.target, access.write) for access in accesses] == [("One.Shared", True)]
