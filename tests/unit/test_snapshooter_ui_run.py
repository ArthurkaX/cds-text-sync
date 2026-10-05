# -*- coding: utf-8 -*-
"""
test_snapshooter_ui_run.py — the assembled ``project_snapshooter_ui.run`` contract.

``run`` is the WinForms front end of the Snapshooter wizard.  It injects the
backend module's namespace, imports the .NET/WinForms surface, resolves the
active project, builds the variable tree, constructs the ``SnapshooterForm``
dialog, pumps WinForms messages until the user closes it, and hands back the
last preset document the form worked with.

None of that can run under CPython: ``import clr`` and ``System.Windows.Forms``
only exist inside CODESYS' IronPython.  So this module fakes the .NET boundary
(clr / System.Windows.Forms / System.Drawing) and the backend boundary (the
``backend`` dict ``run`` receives), then exercises ``run`` and every button
handler on the form it builds.  It pins the parts a decomposition of ``run``
is most likely to break by accident:

* the ordered side effects of startup (clr references, backend calls, log
  lines, ``build_tree``, ``build_tui_tree``, ``Form.Show``, the message pump);
* the ``RuntimeError`` path from ``build_tree`` (exact MessageBox text, no form
  built, ``run`` returns ``None``);
* the return value (``form._last_data``);
* each handler's full side-effect trace and message text (save, load, diff,
  restore, search, check cascade).

The tests talk to ``run`` and to the form instance the fake ``Form`` base class
records — never to the private stages — so the decomposition can rename and
move stages without editing this grid.
"""

import importlib.machinery
import importlib.util
import os
import sys
import types

import pytest


_UI_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "products",
        "codesys-host",
        "src",
        "ide_bridge",
        "project_snapshooter_ui.py",
    )
)


# ── The fake .NET boundary ─────────────────────────────────────────────────


class _Sink(object):
    """Permissive stand-in for any WinForms member we do not model.

    Reading an attribute, calling it, or ``+=``-ing an event handler all return
    the same sink, which is exactly how the form uses the .NET surface it only
    sets and never reads back.
    """

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self

    def __iadd__(self, other):
        return self


class _Controls(object):
    def __init__(self):
        self.items = []

    def Add(self, item):
        self.items.append(item)
        return item


class _Nodes(object):
    """TreeNode/NodeCollection subset: Add sets Parent, Count, indexing."""

    def __init__(self, owner=None):
        self.owner = owner
        self.items = []

    def Add(self, node):
        node.Parent = self.owner
        self.items.append(node)
        return node

    def Clear(self):
        self.items = []

    @property
    def Count(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


class _TreeNode(object):
    def __init__(self, text=""):
        self.Text = text
        self.Name = ""
        self.Tag = None
        self.Checked = False
        self.Parent = None
        self.Nodes = _Nodes(self)
        self.expanded = False

    def Expand(self):
        self.expanded = True

    def EnsureVisible(self):
        pass


class _Size(object):
    def __init__(self, width, height):
        self.Width = width
        self.Height = height


class _Point(object):
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class _Padding(object):
    def __init__(self, *values):
        self.Values = values


class _Font(object):
    def __init__(self, *args):
        self.Args = args


class _DockStyle(object):
    Top = "Top"
    Fill = "Fill"
    Bottom = "Bottom"


class _AnchorStyles(object):
    Top = 1
    Bottom = 2
    Left = 4
    Right = 8


class _FormStartPosition(object):
    CenterScreen = "CenterScreen"


class _FontStyle(object):
    Bold = "Bold"
    Regular = "Regular"


class _Keys(object):
    Enter = "Enter"
    F3 = "F3"


class _MessageBoxButtons(object):
    OK = "OK"
    YesNo = "YesNo"


class _MessageBoxIcon(object):
    Warning = "Warning"
    Information = "Information"


class _DialogResult(object):
    OK = "OK"
    Yes = "Yes"
    No = "No"
    Cancel = "Cancel"


class _Widget(object):
    """Base for every control the form constructs and only configures."""

    def __init__(self, *args, **kwargs):
        self.Controls = _Controls()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Sink()


class _Label(_Widget):
    pass


class _Button(_Widget):
    pass


class _Panel(_Widget):
    pass


class _TextBox(_Widget):
    def __init__(self):
        _Widget.__init__(self)
        self.Text = ""


class _TreeView(_Widget):
    def __init__(self):
        _Widget.__init__(self)
        self.Nodes = _Nodes(None)
        self.SelectedNode = None

    def BeginUpdate(self):
        pass

    def EndUpdate(self):
        pass


class DotNet(object):
    """Records the .NET surface ``run`` touches and answers as configured."""

    def __init__(self):
        self.events = []
        self.forms = []
        self.on_tick = None
        self.messagebox_calls = []
        self.messagebox_answers = []
        self.messagebox_default = _DialogResult.OK
        self.dialogs = []
        self.save_dialog_result = _DialogResult.Cancel
        self.save_dialog_chosen = None
        self.open_dialog_result = _DialogResult.Cancel
        self.open_dialog_chosen = None
        self._install()

    def _rec(self, name, *payload):
        self.events.append((name,) + payload)

    def _install(self):
        dotnet = self

        class Clr(object):
            def AddReference(self, name):
                dotnet._rec("clr.AddReference", name)

        class MessageBox(object):
            @staticmethod
            def Show(message, caption, buttons=None, icon=None):
                dotnet._rec("MessageBox.Show", message, caption)
                dotnet.messagebox_calls.append((message, caption, buttons, icon))
                if dotnet.messagebox_answers:
                    return dotnet.messagebox_answers.pop(0)
                return dotnet.messagebox_default

        class _Dialog(object):
            def __init__(self):
                self.Filter = ""
                self.FileName = ""
                self.InitialDirectory = ""

            def ShowDialog(self, parent=None):
                dotnet._rec(self._kind + ".ShowDialog")
                dotnet.dialogs.append(self)
                dotnet._rec(self._kind + ".FileName", self.FileName)
                chosen = (
                    dotnet.save_dialog_chosen
                    if self._kind == "SaveFileDialog"
                    else dotnet.open_dialog_chosen
                )
                if chosen is not None:
                    self.FileName = chosen
                return (
                    dotnet.save_dialog_result
                    if self._kind == "SaveFileDialog"
                    else dotnet.open_dialog_result
                )

        class SaveFileDialog(_Dialog):
            _kind = "SaveFileDialog"

        class OpenFileDialog(_Dialog):
            _kind = "OpenFileDialog"

        class Form(_Widget):
            def __init__(self):
                _Widget.__init__(self)
                self.ClientSize = _Size(760, 560)
                self._closed = False
                self.Visible = False
                dotnet._rec("Form.__init__")
                dotnet.forms.append(self)

            def Show(self):
                self.Visible = True
                dotnet._rec("Form.Show")

            def Close(self):
                self._closed = True

        class Application(object):
            @staticmethod
            def DoEvents():
                dotnet._rec("Application.DoEvents")
                form = dotnet.forms[-1] if dotnet.forms else None
                if form is None:
                    return
                if dotnet.on_tick is not None:
                    dotnet.on_tick(form)
                form._closed = True

        forms = types.ModuleType("System.Windows.Forms")
        for name, value in (
            ("Form", Form),
            ("TreeView", _TreeView),
            ("Button", _Button),
            ("Label", _Label),
            ("TextBox", _TextBox),
            ("Panel", _Panel),
            ("DockStyle", _DockStyle),
            ("FormStartPosition", _FormStartPosition),
            ("AnchorStyles", _AnchorStyles),
            ("MessageBox", MessageBox),
            ("MessageBoxButtons", _MessageBoxButtons),
            ("MessageBoxIcon", _MessageBoxIcon),
            ("DialogResult", _DialogResult),
            ("SaveFileDialog", SaveFileDialog),
            ("OpenFileDialog", OpenFileDialog),
            ("Application", Application),
            ("Padding", _Padding),
            ("TreeNode", _TreeNode),
            ("Keys", _Keys),
        ):
            setattr(forms, name, value)

        class Color(object):
            @staticmethod
            def FromArgb(*args):
                return ("FromArgb",) + args

        drawing = types.ModuleType("System.Drawing")
        for name, value in (
            ("Point", _Point),
            ("Size", _Size),
            ("Font", _Font),
            ("FontStyle", _FontStyle),
            ("Color", Color),
        ):
            setattr(drawing, name, value)

        self.clr = Clr()
        self.modules = {
            "clr": self.clr,
            "System": types.ModuleType("System"),
            "System.Windows": types.ModuleType("System.Windows"),
            "System.Windows.Forms": forms,
            "System.Drawing": drawing,
        }
        self._save_dialog_cls = SaveFileDialog
        self._open_dialog_cls = OpenFileDialog


class FakeTime(object):
    def __init__(self, dotnet, values=None):
        self.dotnet = dotnet
        self.values = list(values or [0.0])
        self.index = 0

    def time(self):
        if self.index < len(self.values):
            value = self.values[self.index]
            self.index += 1
        else:
            value = self.values[-1]
        self.dotnet._rec("time.time", value)
        return value

    def sleep(self, seconds):
        self.dotnet._rec("time.sleep", seconds)

    def strftime(self, fmt):
        return "2026-01-01T00:00"


class SnapshotOnlineError(RuntimeError):
    """Backend's online-session guard error, mirrored for the fake."""


# ── The fake backend boundary ──────────────────────────────────────────────


class _ModelNode(object):
    def __init__(self, name, path, leaf=False):
        self.name = name
        self.path = path
        self.type = ""
        self.value = ""
        self.leaf = leaf
        self.parent = None
        self.children = []
        self.leaf_count = 1 if leaf else 0
        self.search_text = name.lower()
        self.excluded_from_build = False

    def add(self, child):
        child.parent = self
        self.children.append(child)
        if child.leaf:
            self.leaf_count += 1
        else:
            self.leaf_count += child.leaf_count
        return child


def _default_model(app="Application"):
    """A small tree: Application > (GVL > a, b) + x."""
    root = _ModelNode(app, app, leaf=False)
    gvl = root.add(_ModelNode("GVL", "GVL", leaf=False))
    a = gvl.add(_ModelNode("a", "GVL.a", leaf=True))
    a.type = "INT"
    a.value = "1"
    a.search_text = "gvl.a a"
    b = gvl.add(_ModelNode("b", "GVL.b", leaf=True))
    b.type = "BOOL"
    b.value = "TRUE"
    b.search_text = "gvl.b b"
    x = root.add(_ModelNode("x", "App.x", leaf=True))
    x.type = "REAL"
    x.value = "0.0"
    x.search_text = "app.x x"
    # ``add`` snapshots a child's leaf_count when the child is attached; give
    # the branches their final totals after the whole subtree exists.
    gvl.leaf_count = 2
    root.leaf_count = 3
    return root


class Backend(object):
    """The ``backend`` namespace dict ``run`` receives from the wizard module."""

    def __init__(self, dotnet, snapshot_dir):
        self.dotnet = dotnet
        self.snapshot_dir = snapshot_dir
        self.project = "PROJECT"
        self.project_name = "MyProject"
        self.tree_rows = [{"path": "GVL.a"}, {"path": "GVL.b"}, {"path": "App.x"}]
        self.root_model = _default_model()
        self.build_tree_error = None
        self.take_result = {"paths": []}
        self.load_result = {"paths": []}
        self.diff_report = {"same": [], "missing": [], "type_changed": [], "value_changed": []}
        self.restore_result = {"written": 0, "skipped": 0}
        self.online_error = None
        self.os = os
        self.time = FakeTime(dotnet)
        self.SnapshotOnlineError = SnapshotOnlineError

    def _rec(self, name, *payload):
        self.dotnet._rec(name, *payload)

    def _get_active_project(self):
        self._rec("_get_active_project")
        return self.project

    def _log(self, message):
        self._rec("_log", message)

    def _ensure_default_snapshot_dir(self, project):
        self._rec("_ensure_default_snapshot_dir", project)
        return self.snapshot_dir

    def _project_name(self, project):
        self._rec("_project_name", project)
        return self.project_name

    def build_tree(self, app="Application", project=None):
        self._rec("build_tree", app, project)
        if self.build_tree_error is not None:
            raise self.build_tree_error
        return self.tree_rows

    def build_tui_tree(self, rows, app="Application"):
        self._rec("build_tui_tree", app)
        return self.root_model

    def _text(self, value):
        return "" if value is None else str(value)

    def _branch_summary(self, node):
        return "sum:{0}".format(node.name)

    def _default_preset_path(self, project, label=""):
        self._rec("_default_preset_path", project, label)
        return os.path.join(self.snapshot_dir, label)

    def _snapshot_default_label(self, base="preset"):
        self._rec("_snapshot_default_label", base)
        return "preset_20260101"

    def _vars_from_data(self, data):
        return [{"path": path} for path in data.get("paths", [])]

    def take(self, paths=None, app="Application", label="", project=None):
        self._rec("take", tuple(paths or ()), app, label)
        return self.take_result

    def save(self, data, path):
        self._rec("save", path)

    def load(self, path):
        self._rec("load", path)
        return self.load_result

    def compare(self, data, current=None):
        self._rec("compare")
        return self.diff_report

    def restore(self, data, apply=False, project=None):
        self._rec("restore", apply)
        return self.restore_result

    def ensure_snapshot_import_allowed(self):
        self._rec("ensure_snapshot_import_allowed")
        if self.online_error is not None:
            raise self.online_error

    def as_dict(self):
        return {
            "_get_active_project": self._get_active_project,
            "_log": self._log,
            "_ensure_default_snapshot_dir": self._ensure_default_snapshot_dir,
            "_project_name": self._project_name,
            "build_tree": self.build_tree,
            "build_tui_tree": self.build_tui_tree,
            "_text": self._text,
            "_branch_summary": self._branch_summary,
            "_default_preset_path": self._default_preset_path,
            "_snapshot_default_label": self._snapshot_default_label,
            "_vars_from_data": self._vars_from_data,
            "take": self.take,
            "save": self.save,
            "load": self.load,
            "compare": self.compare,
            "restore": self.restore,
            "ensure_snapshot_import_allowed": self.ensure_snapshot_import_allowed,
            "SnapshotOnlineError": self.SnapshotOnlineError,
            "os": self.os,
            "time": self.time,
        }


# ── Harness ────────────────────────────────────────────────────────────────


def _load_ui_module():
    """Import a fresh ``project_snapshooter_ui`` (no module-level imports)."""
    loader = importlib.machinery.SourceFileLoader(
        "project_snapshooter_ui_under_test", _UI_PATH
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# Backend-boundary calls this grid treats as observable side effects.  ``_text``,
# ``_branch_summary`` and ``_vars_from_data`` are pure read helpers used while
# rendering, so they are deliberately excluded from the order assertions.
_BACKEND_NAMES = frozenset([
    "_get_active_project",
    "_log",
    "_ensure_default_snapshot_dir",
    "_project_name",
    "build_tree",
    "build_tui_tree",
    "_default_preset_path",
    "_snapshot_default_label",
    "take",
    "save",
    "load",
    "compare",
    "restore",
    "ensure_snapshot_import_allowed",
    "time.time",
    "time.sleep",
])


class Scenario(object):
    def __init__(self, ui, backend, dotnet):
        self.ui = ui
        self.backend = backend
        self.dotnet = dotnet
        self._mark = 0

    @property
    def events(self):
        return self.dotnet.events

    def event_names(self):
        return [event[0] for event in self.events]

    def mark(self):
        """Start counting backend calls from here (skips ``run`` startup)."""
        self._mark = len(self.events)

    def backend_calls(self):
        """Backend-boundary calls since the last ``mark()``, in order."""
        return [
            event[0]
            for event in self.events[self._mark:]
            if event[0] in _BACKEND_NAMES
        ]

    def form(self):
        assert self.dotnet.forms, "run built no form"
        return self.dotnet.forms[-1]

    def messages(self):
        return self.dotnet.messagebox_calls


@pytest.fixture
def scenario(tmp_path):
    dotnet = DotNet()
    saved = {}
    for name, module in dotnet.modules.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    backend = Backend(dotnet, str(tmp_path))
    ui = _load_ui_module()
    try:
        yield Scenario(ui, backend, dotnet)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _run(scenario, app="Application", save_to="", backend=None):
    return scenario.ui.run(
        backend if backend is not None else scenario.backend.as_dict(),
        app=app,
        save_to=save_to,
    )


# ── Startup: side-effect order and the RuntimeError path ───────────────────


def test_startup_side_effects_run_in_order(scenario):
    """The whole startup trace, in order, before the message pump."""
    result = _run(scenario)

    assert result is None
    assert scenario.event_names()[:6] == [
        "clr.AddReference",
        "clr.AddReference",
        "_get_active_project",
        "_log",
        "_ensure_default_snapshot_dir",
        "_project_name",
    ]
    assert scenario.events[0] == ("clr.AddReference", "System.Windows.Forms")
    assert scenario.events[1] == ("clr.AddReference", "System.Drawing")

    backend_order = scenario.backend_calls()
    assert backend_order == [
        "_get_active_project",
        "_log",
        "_ensure_default_snapshot_dir",
        "_project_name",
        "_log",
        "_log",
        "time.time",
        "build_tree",
        "time.time",
        "_log",
        "build_tui_tree",
        "time.sleep",
    ]

    tail = scenario.event_names()[-3:]
    assert tail == ["Form.Show", "Application.DoEvents", "time.sleep"]
    # The pump: DoEvents then a 50 ms sleep, once per tick, until the form closes.
    assert scenario.events[-1] == ("time.sleep", 0.05)
    assert scenario.event_names().count("Application.DoEvents") == 1


def test_log_lines_carry_app_and_project(scenario):
    _run(scenario, app="MyApp")

    logs = [event[1] for event in scenario.events if event[0] == "_log"]
    assert logs[0] == "=== _run_winforms_interactive START app=MyApp ==="
    assert logs[1] == "project_name=MyProject"
    assert logs[2] == "calling build_tree (structure only, no PLC read)..."
    assert logs[3] == "build_tree returned 3 rows in 0.00s"


def test_project_name_blank_falls_back_to_project(scenario):
    scenario.backend.project_name = ""
    _run(scenario)

    logs = [event[1] for event in scenario.events if event[0] == "_log"]
    assert "project_name=project" in logs


def test_build_tree_runtime_error_shows_message_and_returns_none(scenario):
    scenario.backend.build_tree_error = RuntimeError("no sync folder")

    result = _run(scenario)

    assert result is None
    assert scenario.dotnet.forms == []
    assert len(scenario.messages()) == 1
    message, caption, buttons, icon = scenario.messages()[0]
    assert message == (
        "Cannot build Snapshooter variable tree.\n\nno sync folder\n\n"
        "Snapshooter exports .dump\\IDE.xml and builds "
        ".dump\\snapshots\\variable_tree.json via CPython. Check cds-sync-folder "
        "and the external Python engine."
    )
    assert caption == "Project_snapshooter"
    assert buttons == "OK"
    assert icon == "Warning"
    assert "build_tui_tree" not in scenario.backend_calls()
    assert "Application.DoEvents" not in scenario.event_names()


def test_run_returns_the_forms_last_data(scenario):
    sentinel = {"paths": ["GVL.a"]}

    def tick(form):
        form._last_data = sentinel

    scenario.dotnet.on_tick = tick
    assert _run(scenario) is sentinel


def test_save_to_argument_is_inert(scenario):
    """``save_to`` is accepted and forwarded but never read by ``run``."""
    _run(scenario, save_to="/tmp/should-not-be-used")

    assert "save_to" not in "".join(scenario.event_names())
    assert scenario.backend_calls() == [
        "_get_active_project",
        "_log",
        "_ensure_default_snapshot_dir",
        "_project_name",
        "_log",
        "_log",
        "time.time",
        "build_tree",
        "time.time",
        "_log",
        "build_tui_tree",
        "time.sleep",
    ]


def test_backend_names_are_injected_as_module_globals(scenario):
    backend = scenario.backend.as_dict()
    scenario.ui.run(backend, app="Application")

    # ``globals().update(backend)`` makes the wizard's helpers module globals,
    # so the form methods (and the run body) resolve them without arguments.
    assert scenario.ui.take is backend["take"]
    assert scenario.ui.build_tree is backend["build_tree"]
    assert scenario.ui.os is backend["os"]


# ── The form's tree population ─────────────────────────────────────────────


def test_form_populates_the_tree_and_status(scenario):
    _run(scenario)
    form = scenario.form()

    assert form._leaf_count == 3
    assert [str(node.Name) for node in form._all_leaf_nodes] == [
        "GVL.a",
        "GVL.b",
        "App.x",
    ]
    assert form._selected_count == 0
    assert form.status.Text == "Selected: 0/3 leaves"
    assert form.Text == "Project_snapshooter"
    assert form.tree.CheckBoxes is True
    # Root row plus one branch row plus the three leaves.
    root_ui = form.tree.Nodes[0]
    assert root_ui.Name == "Application"
    assert root_ui.expanded is True
    assert form.tree.SelectedNode is root_ui


def test_leaf_and_branch_row_text(scenario):
    _run(scenario)
    form = scenario.form()

    texts = [str(form._node_text(model)) for model in form._node_models.values()]
    assert "GVL" + "    " + "sum:GVL" in texts
    leaf_text = "a".ljust(34) + " " + "INT".ljust(12) + " 1"
    assert leaf_text in texts
    assert "Application" + "    " + "sum:Application" in texts


def test_title_uses_project_and_app(scenario):
    _run(scenario, app="MyApp")
    form = scenario.form()

    title = [child for child in form.Controls.items][0]
    assert title.Text == "Snapshooter :: MyProject :: MyApp"


# ── Check cascade ──────────────────────────────────────────────────────────


def test_checking_the_root_cascades_to_leaves(scenario):
    _run(scenario)
    form = scenario.form()
    root_ui = form.tree.Nodes[0]
    root_ui.Checked = True

    form._on_after_check(None, types.SimpleNamespace(Node=root_ui))

    assert form._selected_count == 3
    assert all(node.Checked for node in form._all_leaf_nodes)
    assert form.status.Text == "Selected: 3/3 leaves"


def test_unchecking_a_leaf_leaves_the_count_stale(scenario):
    """Known quirk: a leaf's own checkbox never moves ``_selected_count``.

    ``_on_after_check`` folds in ``_set_children_checked``'s delta, which only
    counts *descendant* leaves -- a leaf has none, so unchecking one updates the
    branch tri-state but leaves the "Selected: n/m leaves" label stale.  Pinned
    as-is; the decomposition must not "fix" it.
    """
    _run(scenario)
    form = scenario.form()
    root_ui = form.tree.Nodes[0]
    root_ui.Checked = True
    form._on_after_check(None, types.SimpleNamespace(Node=root_ui))
    assert form._selected_count == 3

    leaf = [n for n in form._all_leaf_nodes if n.Name == "GVL.a"][0]
    leaf.Checked = False
    form._on_after_check(None, types.SimpleNamespace(Node=leaf))

    assert leaf.Checked is False
    assert form._selected_count == 3
    assert form.status.Text == "Selected: 3/3 leaves"
    # The parent tri-state, however, is recomputed and does see the change.
    gvl_ui = form.tree.Nodes[0].Nodes[0]
    assert gvl_ui.Checked is False
    assert form.tree.Nodes[0].Checked is False


def test_reentrant_check_is_ignored(scenario):
    _run(scenario)
    form = scenario.form()
    form._checking = True
    root_ui = form.tree.Nodes[0]
    root_ui.Checked = True

    form._on_after_check(None, types.SimpleNamespace(Node=root_ui))

    assert form._selected_count == 0
    assert form.status.Text == "Selected: 0/3 leaves"


# ── Save ───────────────────────────────────────────────────────────────────


def test_save_without_selection_warns_and_writes_nothing(scenario):
    _run(scenario)
    form = scenario.form()

    form._on_save(None, None)

    assert len(scenario.messages()) == 1
    assert scenario.messages()[0][:2] == ("Select at least one leaf variable.", "Save")
    assert "take" not in scenario.backend_calls()
    assert "save" not in scenario.backend_calls()


def test_save_writes_the_selected_paths(scenario, tmp_path):
    snapshot_dir = str(tmp_path)
    scenario.backend.take_result = {"paths": ["GVL.a"]}
    scenario.dotnet.save_dialog_result = _DialogResult.OK
    scenario.dotnet.save_dialog_chosen = os.path.join(snapshot_dir, "speed.json")
    _run(scenario)
    form = scenario.form()
    leaf = [n for n in form._all_leaf_nodes if n.Name == "GVL.a"][0]
    leaf.Checked = True
    scenario.mark()

    form._on_save(None, None)

    assert scenario.backend_calls() == [
        "_snapshot_default_label",
        "_default_preset_path",
        "take",
        "save",
    ]
    take_event = [e for e in scenario.events if e[0] == "take"][0]
    assert take_event[1] == ("GVL.a",)
    assert take_event[2] == "Application"
    assert take_event[3] == "speed"
    save_event = [e for e in scenario.events if e[0] == "save"][0]
    assert save_event[1] == os.path.join(snapshot_dir, "speed.json")
    assert form._last_data == {"paths": ["GVL.a"]}
    assert scenario.messages()[0][:2] == ("Saved 1 variables.", "Save")


def test_save_uses_the_first_checked_label_and_initial_directory(scenario, tmp_path):
    scenario.dotnet.save_dialog_result = _DialogResult.Cancel
    _run(scenario)
    form = scenario.form()
    for node in form._all_leaf_nodes:
        node.Checked = True

    form._on_save(None, None)

    label_event = [e for e in scenario.events if e[0] == "_snapshot_default_label"][0]
    assert label_event[1] == "GVL.a"
    path_event = [e for e in scenario.events if e[0] == "_default_preset_path"][0]
    assert path_event[2] == "preset_20260101"
    dialog = scenario.dotnet.dialogs[0]
    assert dialog.FileName == "preset_20260101"
    assert dialog.InitialDirectory == str(tmp_path)
    assert "take" not in scenario.backend_calls()


def test_save_dialog_cancel_is_a_noop(scenario):
    scenario.dotnet.save_dialog_result = _DialogResult.Cancel
    _run(scenario)
    form = scenario.form()
    form._all_leaf_nodes[0].Checked = True

    form._on_save(None, None)

    assert "take" not in scenario.backend_calls()
    assert "save" not in scenario.backend_calls()
    assert form._last_data is None
    assert scenario.messages() == []


# ── Load ───────────────────────────────────────────────────────────────────


def test_load_crashes_after_checking_matching_leaves(scenario, tmp_path):
    """Known defect: ``_on_load`` always raises ``_recompute_parent_states``.

    ``_recompute_parent_states`` collects ``id(parent)`` ints into ``seen`` and
    then sorts ``seen`` as if it held nodes (``str(n.Name)``), so the Load button
    dies with ``AttributeError: 'int' object has no attribute 'Name'`` on any
    non-empty tree.  The checkboxes and ``_last_data`` are already updated by
    then, but the status label and the "Loaded N variables." box never happen.
    Pinned as-is; the decomposition must not silently repair it.
    """
    scenario.backend.load_result = {"paths": ["GVL.a", "App.x"]}
    scenario.dotnet.open_dialog_result = _DialogResult.OK
    scenario.dotnet.open_dialog_chosen = os.path.join(str(tmp_path), "p.json")
    _run(scenario)
    form = scenario.form()

    with pytest.raises(AttributeError):
        form._on_load(None, None)

    checked = sorted(node.Name for node in form._all_leaf_nodes if node.Checked)
    assert checked == ["App.x", "GVL.a"]
    assert form._selected_count == 2
    assert form._last_data == {"paths": ["GVL.a", "App.x"]}
    load_event = [e for e in scenario.events if e[0] == "load"][0]
    assert load_event[1] == os.path.join(str(tmp_path), "p.json")
    # The status label and the completion MessageBox are never reached.
    assert form.status.Text == "Selected: 0/3 leaves"
    assert scenario.messages() == []


def test_load_dialog_cancel_is_a_noop(scenario):
    scenario.dotnet.open_dialog_result = _DialogResult.Cancel
    _run(scenario)
    form = scenario.form()

    form._on_load(None, None)

    assert "load" not in scenario.backend_calls()
    assert form._last_data is None
    assert scenario.messages() == []


# ── Diff ───────────────────────────────────────────────────────────────────


def test_diff_uses_last_data_and_warns_on_differences(scenario):
    scenario.backend.take_result = {"paths": ["GVL.a"]}
    scenario.backend.diff_report = {
        "same": ["a"],
        "missing": ["b"],
        "type_changed": [],
        "value_changed": ["c", "d"],
    }
    _run(scenario)
    form = scenario.form()
    form._last_data = {"paths": ["GVL.a"]}

    form._on_diff(None, None)

    assert [e[0] for e in scenario.events if e[0] in ("take", "compare")] == [
        "take",
        "compare",
    ]
    take_event = [e for e in scenario.events if e[0] == "take"][0]
    assert take_event[1] == ("GVL.a",)
    message = scenario.messages()[0]
    assert message[0] == "same: 1\nmissing: 1\ntype changed: 0\nvalue changed: 2"
    assert message[1] == "Diff"
    assert message[3] == "Warning"
    assert form._last_data == {"paths": ["GVL.a"]}


def test_diff_reports_identical_with_information_icon(scenario):
    scenario.backend.diff_report = {
        "same": ["a"],
        "missing": [],
        "type_changed": [],
        "value_changed": [],
        "identical": True,
    }
    _run(scenario)
    form = scenario.form()
    form._last_data = {"paths": ["GVL.a"]}

    form._on_diff(None, None)

    assert scenario.messages()[0][3] == "Information"


def test_diff_loads_a_dialog_when_there_is_no_last_data(scenario, tmp_path):
    scenario.dotnet.open_dialog_result = _DialogResult.Cancel
    _run(scenario)
    form = scenario.form()

    form._on_diff(None, None)

    assert "OpenFileDialog.ShowDialog" in scenario.event_names()
    assert "compare" not in scenario.backend_calls()
    assert scenario.messages() == []


# ── Restore ────────────────────────────────────────────────────────────────


def test_restore_is_blocked_while_online(scenario):
    scenario.backend.online_error = SnapshotOnlineError("Snapshot import is disabled.")
    _run(scenario)
    form = scenario.form()
    form._last_data = {"paths": ["GVL.a"]}

    form._on_restore(None, None)

    assert scenario.messages()[0][:2] == ("Snapshot import is disabled.", "Restore blocked")
    assert "restore" not in scenario.backend_calls()
    assert "take" not in scenario.backend_calls()


def test_restore_declined_confirmation_does_not_write(scenario):
    scenario.dotnet.messagebox_answers = [_DialogResult.No]
    _run(scenario)
    form = scenario.form()
    form._last_data = {"paths": ["GVL.a"]}

    form._on_restore(None, None)

    assert "restore" not in scenario.backend_calls()
    assert "take" in scenario.backend_calls()
    message = scenario.messages()[0]
    assert message[2] == "YesNo"
    assert message[0].endswith("\n\nWrite matching variables to PLC?")


def test_restore_confirmed_writes_and_reports(scenario):
    scenario.dotnet.messagebox_answers = [_DialogResult.Yes]
    scenario.backend.restore_result = {"written": 2, "skipped": 1}
    _run(scenario)
    form = scenario.form()
    form._last_data = {"paths": ["GVL.a"]}

    form._on_restore(None, None)

    restore_event = [e for e in scenario.events if e[0] == "restore"][0]
    assert restore_event[1] is True
    assert [e[0] for e in scenario.events if e[0] in ("take", "compare", "restore")] == [
        "take",
        "compare",
        "restore",
    ]
    assert scenario.messages()[-1][:2] == ("Written: 2\nSkipped: 1", "Restore")
    assert form._last_data == {"paths": ["GVL.a"]}


# ── Search ─────────────────────────────────────────────────────────────────


def test_search_next_selects_the_first_match(scenario):
    _run(scenario)
    form = scenario.form()
    form.search_box.Text = "gvl.a"

    form._on_search_next(None, None)

    assert form.tree.SelectedNode.Name == "GVL.a"
    assert form._last_search_query == "gvl.a"
    assert form._last_search_index == 0
    assert scenario.messages() == []


def test_search_next_wraps_around(scenario):
    _run(scenario)
    form = scenario.form()
    form.search_box.Text = "gvl"
    form._on_search_next(None, None)  # -> GVL.a, index 0
    form.tree.SelectedNode = [n for n in form._all_leaf_nodes if n.Name == "GVL.b"][0]

    form._on_search_next(None, None)  # index 1 -> wraps to 0

    assert form.tree.SelectedNode.Name == "GVL.a"


def test_search_prev_selects_the_last_match(scenario):
    _run(scenario)
    form = scenario.form()
    form.search_box.Text = "gvl"

    form._on_search_prev(None, None)

    assert form.tree.SelectedNode.Name == "GVL.b"


def test_search_without_matches_reports(scenario):
    _run(scenario)
    form = scenario.form()
    form.search_box.Text = "nothing-like-this"

    form._on_search_next(None, None)

    assert scenario.messages()[0][:2] == ("No matching variable path.", "Search")
    assert form._last_search_index == -1


def test_empty_search_query_does_nothing(scenario):
    _run(scenario)
    form = scenario.form()
    form.search_box.Text = "   "

    form._on_search_next(None, None)

    assert scenario.messages() == []


def test_search_enter_key_runs_forward_search(scenario):
    _run(scenario)
    form = scenario.form()
    form.search_box.Text = "app.x"
    args = types.SimpleNamespace(KeyCode="Enter", Handled=False, SuppressKeyPress=False)

    form._on_search_key(None, args)

    assert form.tree.SelectedNode.Name == "App.x"
    assert args.Handled is True
    assert args.SuppressKeyPress is True


# ── Close ──────────────────────────────────────────────────────────────────


def test_close_button_closes_the_form(scenario):
    _run(scenario)
    form = scenario.form()

    form._on_close(None, None)

    assert form._closed is True


def test_form_closed_handler_marks_closed(scenario):
    _run(scenario)
    form = scenario.form()

    form._on_closed(None, None)

    assert form._closed is True
