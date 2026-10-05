# -*- coding: utf-8 -*-
# ruff: noqa: F821  (backend symbols are injected by run())
"""WinForms frontend for the project snapshot tool.

``run`` is a thin orchestrator: it binds the injected backend and the .NET
surface, resolves the active project, builds the variable tree, then hands the
model to the dialog and pumps messages until the user closes it.

The dialog class cannot live at module scope: its base class ``Form`` only
exists after ``run`` has imported ``System.Windows.Forms`` from inside CODESYS'
IronPython.  :func:`_build_form_class` therefore stamps the behaviour that
lives on :class:`_FormMethods` onto a fresh ``Form`` subclass on demand.  The
tree arithmetic that does not touch WinForms at all -- node captions, the
check cascade, the ancestor tri-state walk, search matching, the diff summary
-- sits above the class as plain functions taking the state they need as
arguments, so it can be read and tested without a dialog.

Both layers resolve the backend helpers (``take``, ``save``, ...) and the
WinForms names as module globals that ``run`` injects before building the
class.
"""


def _load_winforms():
    """Import the .NET surface and return it as a ``{name: object}`` mapping.

    ``run`` folds the mapping into this module's globals so the dialog class
    (built afterwards) can resolve ``Form``, ``MessageBox`` and friends.
    """
    import clr

    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")

    from System.Windows.Forms import (
        Form, TreeView, Button, Label, TextBox, Panel, DockStyle,
        FormStartPosition, AnchorStyles, MessageBox, MessageBoxButtons,
        MessageBoxIcon, DialogResult, SaveFileDialog, OpenFileDialog,
        Application, Padding, TreeNode, Keys,
    )
    from System.Drawing import Point, Size, Font, FontStyle, Color

    return {
        "Form": Form, "TreeView": TreeView, "Button": Button, "Label": Label,
        "TextBox": TextBox, "Panel": Panel, "DockStyle": DockStyle,
        "FormStartPosition": FormStartPosition, "AnchorStyles": AnchorStyles,
        "MessageBox": MessageBox, "MessageBoxButtons": MessageBoxButtons,
        "MessageBoxIcon": MessageBoxIcon, "DialogResult": DialogResult,
        "SaveFileDialog": SaveFileDialog, "OpenFileDialog": OpenFileDialog,
        "Application": Application, "Padding": Padding, "TreeNode": TreeNode,
        "Keys": Keys, "Point": Point, "Size": Size, "Font": Font,
        "FontStyle": FontStyle, "Color": Color,
    }


def _prepare_project(app):
    """Resolve the active project, ensure the snapshot dir, log the banner."""
    project = _get_active_project()
    _log("=== _run_winforms_interactive START app={0} ===".format(app))
    _ensure_default_snapshot_dir(project)
    project_name = _project_name(project) or "project"
    _log("project_name={0}".format(project_name))
    return project, project_name


def _build_variable_tree(app, project):
    """Build the TUI tree model, or report the failure and return ``None``."""
    try:
        _log("calling build_tree (structure only, no PLC read)...")
        t0 = time.time()
        rows = build_tree(app=app, project=project)
        _log("build_tree returned {0} rows in {1:.2f}s".format(len(rows), time.time() - t0))
    except RuntimeError as e:
        MessageBox.Show(
            "Cannot build Snapshooter variable tree.\n\n{0}\n\n"
            "Snapshooter exports .dump\\IDE.xml and builds "
            ".dump\\snapshots\\variable_tree.json via CPython. Check cds-sync-folder "
            "and the external Python engine."
            .format(e),
            "Project_snapshooter",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning,
        )
        return None
    return build_tui_tree(rows, app=app)


def _pump_form(form):
    """Show the form and pump WinForms messages until the user closes it."""
    form.Show()
    while not form._closed:
        Application.DoEvents()
        time.sleep(0.05)
    return form._last_data


def run(backend, app="Application", save_to=""):
    globals().update(backend)
    globals().update(_load_winforms())

    project, project_name = _prepare_project(app)
    root_model = _build_variable_tree(app=app, project=project)
    if root_model is None:
        return None
    form_class = _build_form_class()
    return _pump_form(form_class(project, app, project_name, root_model))


# ── Headless check (no Show/DoEvents) ──────────────────────────────────────
#
# ``check`` is the dialog without the person: it builds the same form the way
# ``run`` does, but never shows it or pumps messages, and swaps MessageBox and
# the file dialogs for recording fakes so the handlers can be driven by a
# script.  It is the backend of the daemon's ``snapshooter ui_check`` action.


_DEFAULT_CHECK_STEPS = (
    "check_first_leaf",
    "search_next",
    "search_prev",
    "save",
    "load",
    "diff",
    "restore",
)


class _CheckWindows(object):
    """Stand-in for MessageBox: records each Show and returns scripted answers.

    Answers are consumed in order.  A Yes/No prompt with no scripted answer is
    answered No, so a ``restore`` step stays a dry-run by default.
    """

    def __init__(self, answers=None):
        self.shown = []
        self._answers = list(answers or [])

    def Show(self, message, caption, buttons=None, icon=None):
        self.shown.append({"title": _text(caption), "text": _text(message)})
        if self._answers:
            return self._answers.pop(0)
        if buttons == MessageBoxButtons.YesNo:
            return DialogResult.No
        return DialogResult.OK


class _CheckFileDialog(object):
    """A SaveFileDialog/OpenFileDialog that always yields the scripted path."""

    def __init__(self, owner, kind, path):
        self._owner = owner
        self._kind = kind
        self.Filter = ""
        self.FileName = path
        self.InitialDirectory = ""

    def ShowDialog(self, parent=None):
        # The handler sets FileName to a basename before the dialog opens; the
        # scripted choice is the full path the dialog would return to it.
        self.FileName = self._owner.preset_path
        self._owner.calls.append((self._kind, self.FileName))
        return DialogResult.OK


class _CheckFileDialogs(object):
    """Factory for the two dialogs; records which was used and with what path."""

    def __init__(self, preset_path):
        self.preset_path = preset_path
        self.calls = []

    def SaveFileDialog(self):
        return _CheckFileDialog(self, "SaveFileDialog", self.preset_path)

    def OpenFileDialog(self):
        return _CheckFileDialog(self, "OpenFileDialog", self.preset_path)


class _CheckArgs(object):
    """The event-args stand-in ``_on_after_check`` reads ``.Node`` from."""

    def __init__(self, node):
        self.Node = node


def _step_check_first_leaf(state):
    form = state["form"]
    if not form._all_leaf_nodes:
        raise RuntimeError("the tree has no leaf variables to check")
    node = form._all_leaf_nodes[0]
    node.Checked = True
    form._on_after_check(form.tree, _CheckArgs(node))


def _search(state, direction):
    form = state["form"]
    if not form.search_box.Text:
        leaves = form._all_leaf_nodes
        form.search_box.Text = leaves[0].Name if leaves else ""
    if direction > 0:
        form._on_search_next(None, None)
    else:
        form._on_search_prev(None, None)


def _step_search_next(state):
    _search(state, 1)


def _step_search_prev(state):
    _search(state, -1)


def _step_save(state):
    form = state["form"]
    form._on_save(form.save_btn, None)


def _step_load(state):
    form = state["form"]
    form._on_load(form.load_btn, None)


def _step_diff(state):
    form = state["form"]
    form._on_diff(form.diff_btn, None)


def _step_restore(state):
    form = state["form"]
    form._on_restore(form.restore_btn, None)


_CHECK_STEPS = {
    "check_first_leaf": _step_check_first_leaf,
    "search_next": _step_search_next,
    "search_prev": _step_search_prev,
    "save": _step_save,
    "load": _step_load,
    "diff": _step_diff,
    "restore": _step_restore,
}


def _check_failure(report, error, windows=None):
    report["ok"] = False
    report["error"] = error
    # Nothing ran, so nothing is known to be ok -- ``all_steps_ok`` keeps its
    # initial False and ``failed_steps`` stays empty (they did not fail: they
    # never started).
    if windows is not None:
        report["windows"] = list(windows.shown)
    return report


def _record_check_state(report, form):
    report["checked_leaves"] = len([n for n in form._all_leaf_nodes if n.Checked])
    report["leaf_count"] = form._leaf_count
    parents = {}
    for ui_node, model in form._node_models.items():
        if getattr(model, "leaf", False):
            continue
        parents[getattr(model, "path", "") or getattr(model, "name", "")] = bool(
            ui_node.Checked
        )
    report["parents"] = parents


def _new_check_report(app):
    return {
        "ok": True,
        "app": app,
        "project": "",
        "steps": [],
        "failed_steps": [],
        # False until the steps have run: "nothing failed" is not yet known,
        # and a report that never got that far must not read as a clean one.
        "all_steps_ok": False,
        "windows": [],
        "files": [],
        "checked_leaves": 0,
        "leaf_count": 0,
        "parents": {},
        "preset_file": "",
    }


def _summarize_check_steps(report):
    """Roll the per-step outcomes into ``failed_steps`` / ``all_steps_ok``.

    ``ok`` stays what it was -- false only when the window itself could not be
    built -- so a caller that only branches on it is unaffected.  These two
    fields are what tells a failed *step* from a failed *run*.
    """
    report["failed_steps"] = [
        step["name"] for step in report["steps"] if not step["ok"]
    ]
    report["all_steps_ok"] = not report["failed_steps"]


def _install_check_fakes(preset_path):
    """Swap MessageBox and the file dialogs for the recording stand-ins."""
    windows = _CheckWindows()
    dialogs = _CheckFileDialogs(preset_path)
    globals()["MessageBox"] = windows
    globals()["SaveFileDialog"] = dialogs.SaveFileDialog
    globals()["OpenFileDialog"] = dialogs.OpenFileDialog
    return windows, dialogs


def _build_check_form(app):
    """The form ``run`` would build, without showing or pumping it."""
    project, project_name = _prepare_project(app)
    root_model = _build_variable_tree(app=app, project=project)
    if root_model is None:
        raise RuntimeError("the variable tree could not be built")
    return _build_form_class()(project, app, project_name, root_model), project_name


def _run_check_steps(report, state, steps):
    """Run each named step; an exception is recorded, never propagated."""
    for name in steps:
        entry = {"name": name, "ok": True, "error": ""}
        handler = _CHECK_STEPS.get(name)
        try:
            if handler is None:
                raise ValueError("unknown ui_check step: {0}".format(name))
            handler(state)
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = "{0}: {1}".format(type(exc).__name__, exc)
        report["steps"].append(entry)


def check(backend, app="Application", script=None):
    """Build the dialog without showing it and run a scripted scenario.

    Returns a structural report: ``ok`` (false only when the window itself
    could not be built), ``failed_steps`` (names of the steps that raised) and
    ``all_steps_ok`` (true only when every step ran clean), ``windows``
    (title/text of every MessageBox shown), ``files`` (which file dialog was
    used with which path), ``steps`` (one ``{name, ok, error}`` per scenario
    step, an exception recorded rather than raised), ``checked_leaves``,
    ``leaf_count`` and the check state of each branch in ``parents``.

    ``script`` overrides the default step list (see ``_DEFAULT_CHECK_STEPS``);
    an unknown step name is recorded as a failed step.  The substitutions are
    left in this module's globals -- ``check`` is a one-shot headless entry.
    """
    report = _new_check_report(app)
    globals().update(backend)
    try:
        globals().update(_load_winforms())
    except Exception as exc:
        return _check_failure(
            report, "cannot load the WinForms surface: {0}".format(exc)
        )

    import tempfile

    preset_path = os.path.join(
        tempfile.gettempdir(), "snapshooter-check-{0}.json".format(os.getpid())
    )
    windows, dialogs = _install_check_fakes(preset_path)

    try:
        form, project_name = _build_check_form(app)
    except Exception as exc:
        return _check_failure(
            report,
            "cannot create the Snapshooter window: {0}: {1}".format(
                type(exc).__name__, exc
            ),
            windows,
        )

    report["project"] = project_name
    report["leaf_count"] = form._leaf_count
    report["preset_file"] = preset_path

    state = {"form": form, "save_path": preset_path}
    _run_check_steps(
        report, state, _DEFAULT_CHECK_STEPS if script is None else list(script)
    )
    _summarize_check_steps(report)
    _record_check_state(report, form)
    report["windows"] = list(windows.shown)
    report["files"] = list(dialogs.calls)
    return report


# ── Tree-model arithmetic (no WinForms) ────────────────────────────────────


def _node_row_text(node):
    """The one-line TreeView caption for one variable-tree model node."""
    if node.leaf:
        name = _text(node.name).ljust(34)
        typ = _text(node.type or "").ljust(12)
        text = "{0} {1} {2}".format(name, typ, node.value or "")
        if node.excluded_from_build:
            text = text + " [excluded from build]"
        return text
    return "{0}    {1}".format(node.name, _branch_summary(node))


def _iter_tree(nodes):
    """Depth-first walk over a WinForms node collection."""
    for i in range(nodes.Count):
        node = nodes[i]
        yield node
        for child in _iter_tree(node.Nodes):
            yield child


def _leaf_nodes(nodes):
    """Every UI node tagged as a leaf, in tree order."""
    return [n for n in _iter_tree(nodes) if n.Tag == 1]


def _checked_paths(leaf_nodes):
    """The ``Name`` of every checked leaf, in tree order."""
    return [str(n.Name) for n in leaf_nodes if n.Checked]


def _first_checked_name(nodes):
    """The first checked node's ``Name`` (its text as a fallback)."""
    for node in _iter_tree(nodes):
        if node.Checked:
            return str(node.Name or node.Text or "preset")
    return "preset"


def _set_checked_cascade(node, checked):
    """Push ``checked`` down onto ``node``'s descendants; return the delta.

    Only *descendants* move the delta, and each is counted from the state it
    had before the push -- a partly-filled branch must hand back exactly the
    leaves that changed.  The node itself is not counted here because WinForms
    has already flipped its box by the time the event arrives, so its previous
    state is not visible; the handler adds that one back.
    """
    delta = 0
    for i in range(node.Nodes.Count):
        child = node.Nodes[i]
        if child.Tag == 1:
            if child.Checked != checked:
                delta += 1 if checked else -1
        child.Checked = checked
        delta += _set_checked_cascade(child, checked)
    return delta


def _subtree_leaf_counts(node):
    """``(checked, total)`` leaves in ``node``'s subtree, off the UI tree."""
    checked = 0
    total = 0
    for i in range(node.Nodes.Count):
        child = node.Nodes[i]
        if child.Tag == 1:
            total += 1
            if child.Checked:
                checked += 1
        else:
            child_checked, child_total = _subtree_leaf_counts(child)
            checked += child_checked
            total += child_total
    return checked, total


def _apply_branch_state(branch):
    """Set ``branch`` to checked exactly when every leaf below it is.

    This is the one rule for a branch box, used by both the click path and
    Load.  A partly-filled branch is unchecked, never a third state: a WinForms
    TreeView checkbox has only two.  The counts come from the UI tree rather
    than ``node_models[...].leaf_count``, so the branch always agrees with the
    boxes actually on screen.
    """
    checked, total = _subtree_leaf_counts(branch)
    branch.Checked = total > 0 and checked == total


def _update_parent_state(start_node):
    """Re-derive every ancestor of ``start_node``, bottom-up.

    The click path.  Counting *direct children* -- what this used to do, against
    ``model.leaf_count`` -- disagrees with the leaf rule above as soon as a
    branch has fewer children than leaves (the root of a two-branch tree with
    three leaves could never be ticked) and it compares a child count against a
    leaf count, which are different units.  Reusing ``_apply_branch_state``
    makes a click and a Load agree on the same set of leaves.
    """
    parent = start_node.Parent
    while parent is not None:
        _apply_branch_state(parent)
        parent = parent.Parent


def _recompute_parent_states(leaf_nodes):
    """The Load path: re-derive every branch that has a leaf under it.

    Load writes the leaves and nothing else, so the branches have to be brought
    back in line afterwards.  Order does not matter, because a branch's state
    is derived from the leaves alone rather than from the other branch boxes.
    (The version this replaced collected ``id(parent)`` ints and sorted them as
    if they were nodes, so Load died with ``AttributeError: 'int' object has no
    attribute 'Name'``.)
    """
    branches = []
    seen = set()
    for leaf in leaf_nodes:
        node = leaf.Parent
        while node is not None:
            if id(node) in seen:
                break
            seen.add(id(node))
            branches.append(node)
            node = node.Parent
    for branch in branches:
        _apply_branch_state(branch)


def _search_matches(leaf_nodes, node_models, query):
    """The leaf UI nodes whose model ``search_text`` contains ``query``."""
    matches = []
    for ui_node in leaf_nodes:
        model = node_models.get(ui_node)
        text = model.search_text if model else "{0} {1}".format(ui_node.Name, ui_node.Text).lower()
        if query in text:
            matches.append(ui_node)
    return matches


def _current_match_index(selected, matches):
    """Where ``selected`` sits in ``matches``, or -1 when it is not there."""
    if selected is None:
        return -1
    for i in range(len(matches)):
        if matches[i] is selected:
            return i
    return -1


def _format_diff(report):
    """The four-count summary the Diff and Restore boxes show."""
    return (
        "same: {0}\nmissing: {1}\ntype changed: {2}\nvalue changed: {3}"
        .format(
            len(report.get("same", [])),
            len(report.get("missing", [])),
            len(report.get("type_changed", [])),
            len(report.get("value_changed", [])),
        )
    )


def _add_button(parent, text, location, size, handler, anchor=None):
    """Build, wire and attach a WinForms button; return the control."""
    button = Button()
    button.Text = text
    button.Location = Point(location[0], location[1])
    button.Size = Size(size[0], size[1])
    if anchor is not None:
        button.Anchor = anchor
    button.Click += handler
    parent.Controls.Add(button)
    return button


# ── The dialog ─────────────────────────────────────────────────────────────


def _build_form_class():
    """Build the dialog class against the currently injected .NET surface.

    The class statement cannot live at module scope -- ``Form`` only exists
    after ``run`` imported it -- and the behaviour must not live in the factory
    either, so the methods are defined once on :class:`_FormMethods` and copied
    onto a fresh ``Form`` subclass here.  The copy keeps a single .NET base,
    exactly as the original in-function class had.
    """
    class SnapshooterForm(Form):
        pass

    for name, value in _FormMethods.__dict__.items():
        if name == "__init__" or not name.startswith("__"):
            setattr(SnapshooterForm, name, value)
    return SnapshooterForm


class _FormMethods(object):
    """Widget wiring and event handlers for the Snapshooter dialog.

    ``_build_form_class`` copies these methods onto the ``Form`` subclass it is
    about to instantiate; nothing here subclasses ``Form`` itself.  The backend
    helpers and the WinForms names are module globals injected by ``run``.
    """

    def __init__(self, project, app, project_name, root_model):
        Form.__init__(self)
        self._project = project
        self._app = app
        self._project_name = project_name
        self._root_model = root_model
        self.Text = "Project_snapshooter"
        self.Width = 760
        self.Height = 560
        self.MinimumSize = Size(640, 420)
        self.StartPosition = FormStartPosition.CenterScreen
        self._checking = False
        self._last_data = None
        self._closed = False
        self._last_search_query = ""
        self._last_search_index = -1
        self._leaf_count = 0
        self._selected_count = 0
        self._all_leaf_nodes = []
        self._node_models = {}
        self.FormClosed += self._on_closed
        self._build_ui()
        self._populate_tree()
        self._update_status()

    # -- layout ------------------------------------------------------------

    def _build_ui(self):
        self.Controls.Add(self._build_title())
        content = self._build_content()
        bottom = self._build_bottom_bar()
        self.Controls.Add(bottom)
        self.Controls.Add(content)

    def _build_title(self):
        title = Label()
        title.Text = "Snapshooter :: {0} :: {1}".format(self._project_name, self._app)
        title.Dock = DockStyle.Top
        title.Height = 34
        title.Font = Font("Segoe UI", 11, FontStyle.Bold)
        title.BackColor = Color.FromArgb(245, 245, 245)
        title.Padding = Padding(10, 8, 0, 0)
        return title

    def _build_content(self):
        content = Panel()
        content.Location = Point(0, 34)
        content.Size = Size(self.ClientSize.Width, self.ClientSize.Height - 116)
        content.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right

        self.tree = TreeView()
        self.tree.CheckBoxes = True
        self.tree.Dock = DockStyle.Fill
        self.tree.Font = Font("Consolas", 9.5, FontStyle.Regular)
        self.tree.FullRowSelect = True
        self.tree.HideSelection = False
        self.tree.ShowLines = True
        self.tree.ShowPlusMinus = True
        self.tree.ShowRootLines = True
        self.tree.AfterCheck += self._on_after_check
        content.Controls.Add(self.tree)
        return content

    def _build_bottom_bar(self):
        right = AnchorStyles.Top | AnchorStyles.Right

        bottom = Panel()
        bottom.Location = Point(0, self.ClientSize.Height - 82)
        bottom.Size = Size(self.ClientSize.Width, 82)
        bottom.Anchor = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        bottom.Height = 82

        self.status = Label()
        self.status.Text = "Selected: 0/0 leaves"
        self.status.Location = Point(10, 8)
        self.status.Size = Size(260, 22)
        bottom.Controls.Add(self.status)

        self.search_box = TextBox()
        self.search_box.Location = Point(280, 6)
        self.search_box.Size = Size(210, 22)
        self.search_box.Anchor = right
        self.search_box.KeyDown += self._on_search_key
        bottom.Controls.Add(self.search_box)

        _add_button(bottom, "Prev", (500, 5), (62, 25), self._on_search_prev, right)
        _add_button(bottom, "Next", (568, 5), (62, 25), self._on_search_next, right)
        self.save_btn = _add_button(bottom, "Save", (10, 42), (82, 28), self._on_save)
        self.load_btn = _add_button(bottom, "Load", (100, 42), (82, 28), self._on_load)
        self.diff_btn = _add_button(bottom, "Diff", (190, 42), (82, 28), self._on_diff)
        self.restore_btn = _add_button(bottom, "Restore...", (280, 42), (92, 28), self._on_restore)
        _add_button(bottom, "Close", (650, 42), (82, 28), self._on_close, right)
        return bottom

    # -- tree population ---------------------------------------------------

    def _node_text(self, node):
        return _node_row_text(node)

    def _add_node(self, parent_ui, model):
        ui = TreeNode(self._node_text(model))
        ui.Name = model.path
        self._node_models[ui] = model
        if model.leaf:
            ui.Tag = 1
            self._all_leaf_nodes.append(ui)
        else:
            ui.Tag = 0
        for child in model.children:
            self._add_node(ui, child)
        parent_ui.Nodes.Add(ui)
        return ui

    def _populate_tree(self):
        self._leaf_count = 0
        self._all_leaf_nodes = []
        self._node_models = {}
        self.tree.BeginUpdate()
        try:
            self.tree.Nodes.Clear()
            root_ui = TreeNode(self._node_text(self._root_model))
            root_ui.Name = self._root_model.path
            root_ui.Tag = 0
            self._node_models[root_ui] = self._root_model
            for child in self._root_model.children:
                self._add_node(root_ui, child)
            self.tree.Nodes.Add(root_ui)
            self._leaf_count = len(self._all_leaf_nodes)
            root_ui.Expand()
            self.tree.SelectedNode = root_ui
            root_ui.EnsureVisible()
        finally:
            self.tree.EndUpdate()

    # -- check cascade -----------------------------------------------------

    def _on_after_check(self, sender, args):
        if self._checking:
            return
        self._checking = True
        try:
            node = args.Node
            delta = _set_checked_cascade(node, node.Checked)
            if node.Tag == 1:
                # The clicked leaf's own box: WinForms flipped it before this
                # event, so the cascade sees it as already at its new state and
                # does not count it.  Without this the status label kept the
                # old number whenever a single leaf was clicked.
                delta += 1 if node.Checked else -1
            self._selected_count += delta
            _update_parent_state(node)
        finally:
            self._checking = False
        self._update_status()

    def _update_status(self):
        self.status.Text = "Selected: {0}/{1} leaves".format(
            self._selected_count, self._leaf_count)

    # -- search ------------------------------------------------------------

    def _select_search_match(self, direction):
        query = self.search_box.Text.strip().lower()
        if not query:
            return
        matches = _search_matches(self._all_leaf_nodes, self._node_models, query)
        if not matches:
            self._last_search_query = query
            self._last_search_index = -1
            MessageBox.Show("No matching variable path.", "Search",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return
        if query != self._last_search_query:
            index = 0 if direction >= 0 else len(matches) - 1
        else:
            current_index = _current_match_index(self.tree.SelectedNode, matches)
            if current_index < 0:
                current_index = self._last_search_index
            index = (current_index + direction) % len(matches)
        node = matches[index]
        self._last_search_query = query
        self._last_search_index = index
        self.tree.SelectedNode = node
        node.EnsureVisible()

    def _on_search_prev(self, sender, args):
        self._select_search_match(-1)

    def _on_search_next(self, sender, args):
        self._select_search_match(1)

    def _on_search_key(self, sender, args):
        if args.KeyCode == Keys.Enter:
            self._select_search_match(1)
            args.Handled = True
            args.SuppressKeyPress = True
        elif args.KeyCode == Keys.F3:
            if args.Shift:
                self._select_search_match(-1)
            else:
                self._select_search_match(1)
            args.Handled = True
            args.SuppressKeyPress = True

    # -- save / load / diff / restore --------------------------------------

    def _on_save(self, sender, args):
        paths = _checked_paths(_leaf_nodes(self.tree.Nodes))
        if not paths:
            MessageBox.Show("Select at least one leaf variable.", "Save",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        default_label = _snapshot_default_label(_first_checked_name(self.tree.Nodes))
        default_path = _default_preset_path(self._project, default_label or "preset")
        dialog = SaveFileDialog()
        dialog.Filter = "JSON presets (*.json)|*.json|All files (*.*)|*.*"
        dialog.FileName = os.path.basename(default_path)
        directory = os.path.dirname(default_path)
        if os.path.isdir(directory):
            dialog.InitialDirectory = directory
        if dialog.ShowDialog(self) != DialogResult.OK:
            return
        label = os.path.splitext(os.path.basename(dialog.FileName))[0]
        data = take(paths=paths, app=self._app, label=label, project=self._project)
        save(data, dialog.FileName)
        self._last_data = data
        MessageBox.Show("Saved {0} variables.".format(len(_vars_from_data(data))),
                        "Save", MessageBoxButtons.OK, MessageBoxIcon.Information)

    def _load_dialog(self):
        dialog = OpenFileDialog()
        dialog.Filter = "JSON presets (*.json)|*.json|All files (*.*)|*.*"
        directory = os.path.dirname(_default_preset_path(self._project, "preset"))
        if os.path.isdir(directory):
            dialog.InitialDirectory = directory
        if dialog.ShowDialog(self) != DialogResult.OK:
            return None
        return load(dialog.FileName)

    def _on_load(self, sender, args):
        data = self._load_dialog()
        if data is None:
            return
        self._last_data = data
        paths = set(v.get("path", "") for v in _vars_from_data(data))
        self._checking = True
        self.tree.BeginUpdate()
        try:
            selected = 0
            for node in self._all_leaf_nodes:
                checked = str(node.Name) in paths
                node.Checked = checked
                if checked:
                    selected += 1
            self._selected_count = selected
            _recompute_parent_states(self._all_leaf_nodes)
        finally:
            self.tree.EndUpdate()
            self._checking = False
        self._update_status()
        MessageBox.Show("Loaded {0} variables.".format(selected), "Load",
                        MessageBoxButtons.OK, MessageBoxIcon.Information)

    def _on_diff(self, sender, args):
        data = self._last_data or self._load_dialog()
        if data is None:
            return
        current = take([v.get("path", "") for v in _vars_from_data(data)], project=self._project)
        report = compare(data, current=current)
        MessageBox.Show(_format_diff(report), "Diff",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information if report.get("identical") else MessageBoxIcon.Warning)
        self._last_data = data

    def _on_restore(self, sender, args):
        data = self._last_data or self._load_dialog()
        if data is None:
            return
        try:
            ensure_snapshot_import_allowed()
        except SnapshotOnlineError as exc:
            MessageBox.Show(str(exc), "Restore blocked", MessageBoxButtons.OK,
                            MessageBoxIcon.Warning)
            return
        current = take([v.get("path", "") for v in _vars_from_data(data)], project=self._project)
        report = compare(data, current=current)
        answer = MessageBox.Show(
            _format_diff(report) + "\n\nWrite matching variables to PLC?",
            "Restore",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
        )
        if answer != DialogResult.Yes:
            return
        result = restore(data, apply=True, project=self._project)
        MessageBox.Show(
            "Written: {0}\nSkipped: {1}".format(result.get("written"), result.get("skipped")),
            "Restore",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information,
        )
        self._last_data = data

    # -- close -------------------------------------------------------------

    def _on_close(self, sender, args):
        self.Close()

    def _on_closed(self, sender, args):
        self._closed = True
