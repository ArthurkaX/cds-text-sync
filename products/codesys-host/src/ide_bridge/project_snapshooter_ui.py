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
    """Check or uncheck ``node``'s descendants; return the selected delta.

    Only *descendant* leaves move the delta -- a leaf has none, which is why
    clicking a single leaf never updates ``_selected_count``.  The grid pins
    that quirk; do not "fix" it here.
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


def _update_parent_state(start_node, node_models, leaf_nodes):
    """Re-derive every ancestor's check state from its direct children."""
    parent = start_node.Parent
    while parent is not None:
        checked_count = 0
        for i in range(parent.Nodes.Count):
            if parent.Nodes[i].Checked:
                checked_count += 1
        model = node_models.get(parent)
        total = model.leaf_count if model else len(leaf_nodes)
        if checked_count == 0:
            parent.Checked = False
        elif checked_count == total:
            parent.Checked = True
        else:
            parent.Checked = False
        parent = parent.Parent


def _recompute_parent_states(leaf_nodes, node_models):
    """Known-broken: collects ``id(parent)`` ints, then sorts them as nodes.

    The Load handler always dies here with ``AttributeError: 'int' object has
    no attribute 'Name'`` on a non-empty tree.  The grid pins that crash; it is
    preserved verbatim on purpose and must not be silently repaired.
    """
    seen = set()
    for leaf in leaf_nodes:
        parent = leaf.Parent
        while parent is not None and id(parent) not in seen:
            seen.add(id(parent))
            parent = parent.Parent
    # Process deepest first by sorting on path depth (Name dots).
    parents = list(seen)
    parents.sort(key=lambda n: str(n.Name).count("."), reverse=True)
    for parent in parents:
        model = node_models.get(parent)
        total = model.leaf_count if model else 0
        if total == 0:
            parent.Checked = False
            continue
        checked_count = 0
        for i in range(parent.Nodes.Count):
            if parent.Nodes[i].Checked:
                checked_count += 1
        # For a branch, checked_count is the number of *direct* children
        # whose Checked box is on. With full parent tri-state that only
        # happens when every descendant leaf is selected.
        parent.Checked = checked_count == parent.Nodes.Count


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
            delta = _set_checked_cascade(args.Node, args.Node.Checked)
            self._selected_count += delta
            _update_parent_state(args.Node, self._node_models, self._all_leaf_nodes)
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
            _recompute_parent_states(self._all_leaf_nodes, self._node_models)
        finally:
            self.tree.EndUpdate()
            self._checking = False
        self._update_status()
        MessageBox.Show("Loaded {0} variables.".format(len(paths)), "Load",
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
