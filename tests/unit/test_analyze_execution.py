"""Tests for the analyzer's task and POU execution graph."""

from cds_text_sync.analyze import execution
from cds_text_sync.analyze import project as pm
from cds_text_sync.analyze.project import ProjectSnapshot


def _st(path, text):
    return pm._build_st_unit(path, text)


def _task(name, pou):
    xml = (
        '<Single><List Name="PouList"><Single>'
        f'<Single Name="Name">{pou}</Single>'
        "</Single></List></Single>"
    )
    return pm.Unit(f"{name}.xml#{name}", "task_config", name, f"{name}.xml", xml)


def test_execution_graph_reaches_function_from_task_program():
    main = _st("Main.st", "PROGRAM Main\nIMPLEMENTATION\nHelper();\nEND_PROGRAM\n")
    helper = _st("Helper.st", "FUNCTION Helper\nIMPLEMENTATION\nEND_FUNCTION\n")
    graph = execution.ExecutionGraph(
        ProjectSnapshot(".", [main, helper, _task("Fast", "Main")])
    )

    assert graph.tasks_for("Main") == {"Fast"}
    assert graph.tasks_for("Helper") == {"Fast"}
    assert graph.reachable_from("Fast") == {"main", "helper"}


def test_execution_graph_resolves_fb_method_from_local_instance():
    main = _st(
        "Main.st",
        "PROGRAM Main\nVAR\n    Conveyor : FB_Conveyor;\nEND_VAR\n"
        "IMPLEMENTATION\nConveyor.Run();\nEND_PROGRAM\n",
    )
    fb = _st("FB_Conveyor.st", "FUNCTION_BLOCK FB_Conveyor\nEND_FUNCTION_BLOCK\n")
    method = _st(
        "FB_Conveyor.Run.st",
        "METHOD Run\nIMPLEMENTATION\nEND_METHOD\n",
    )
    graph = execution.ExecutionGraph(
        ProjectSnapshot(".", [main, fb, method, _task("Fast", "Main")])
    )

    assert graph.tasks_for("FB_Conveyor") == {"Fast"}
    assert graph.tasks_for("FB_Conveyor.Run") == {"Fast"}


def test_execution_graph_does_not_reach_unrelated_pou():
    main = _st("Main.st", "PROGRAM Main\nIMPLEMENTATION\nEND_PROGRAM\n")
    other = _st("Other.st", "FUNCTION Other\nIMPLEMENTATION\nEND_FUNCTION\n")
    graph = execution.ExecutionGraph(
        ProjectSnapshot(".", [main, other, _task("Fast", "Main")])
    )

    assert graph.tasks_for("Other") == set()
