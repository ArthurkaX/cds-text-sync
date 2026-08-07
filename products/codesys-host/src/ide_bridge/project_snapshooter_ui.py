# -*- coding: utf-8 -*-
# ruff: noqa: F821  (backend symbols are injected by run())
"""WinForms frontend for the project snapshot tool."""

def run(backend, app="Application", save_to=""):
    globals().update(backend)
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

    project = _get_active_project()
    _log("=== _run_winforms_interactive START app={0} ===".format(app))
    _ensure_default_snapshot_dir(project)
    project_name = _project_name(project) or "project"
    _log("project_name={0}".format(project_name))
    try:
        _log("calling build_tree (structure only, no PLC read)...")
        t0 = time.time()
        tree = build_tree(app=app, project=project)
        _log("build_tree returned {0} rows in {1:.2f}s".format(len(tree), time.time() - t0))
        rows = tree
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
    root_model = build_tui_tree(rows, app=app)

    class SnapshooterForm(Form):
        def __init__(self):
            Form.__init__(self)
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

        def _build_ui(self):
            title = Label()
            title.Text = "Snapshooter :: {0} :: {1}".format(project_name, app)
            title.Dock = DockStyle.Top
            title.Height = 34
            title.Font = Font("Segoe UI", 11, FontStyle.Bold)
            title.BackColor = Color.FromArgb(245, 245, 245)
            title.Padding = Padding(10, 8, 0, 0)
            self.Controls.Add(title)

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
            self.search_box.Anchor = AnchorStyles.Top | AnchorStyles.Right
            self.search_box.KeyDown += self._on_search_key
            bottom.Controls.Add(self.search_box)

            prev_btn = Button()
            prev_btn.Text = "Prev"
            prev_btn.Location = Point(500, 5)
            prev_btn.Size = Size(62, 25)
            prev_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
            prev_btn.Click += self._on_search_prev
            bottom.Controls.Add(prev_btn)

            next_btn = Button()
            next_btn.Text = "Next"
            next_btn.Location = Point(568, 5)
            next_btn.Size = Size(62, 25)
            next_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
            next_btn.Click += self._on_search_next
            bottom.Controls.Add(next_btn)

            self.save_btn = Button()
            self.save_btn.Text = "Save"
            self.save_btn.Location = Point(10, 42)
            self.save_btn.Size = Size(82, 28)
            self.save_btn.Click += self._on_save
            bottom.Controls.Add(self.save_btn)

            self.load_btn = Button()
            self.load_btn.Text = "Load"
            self.load_btn.Location = Point(100, 42)
            self.load_btn.Size = Size(82, 28)
            self.load_btn.Click += self._on_load
            bottom.Controls.Add(self.load_btn)

            self.diff_btn = Button()
            self.diff_btn.Text = "Diff"
            self.diff_btn.Location = Point(190, 42)
            self.diff_btn.Size = Size(82, 28)
            self.diff_btn.Click += self._on_diff
            bottom.Controls.Add(self.diff_btn)

            self.restore_btn = Button()
            self.restore_btn.Text = "Restore..."
            self.restore_btn.Location = Point(280, 42)
            self.restore_btn.Size = Size(92, 28)
            self.restore_btn.Click += self._on_restore
            bottom.Controls.Add(self.restore_btn)

            close_btn = Button()
            close_btn.Text = "Close"
            close_btn.Location = Point(650, 42)
            close_btn.Size = Size(82, 28)
            close_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
            close_btn.Click += self._on_close
            bottom.Controls.Add(close_btn)

            self.Controls.Add(bottom)
            self.Controls.Add(content)

        def _node_text(self, node):
            if node.leaf:
                name = _text(node.name).ljust(34)
                typ = _text(node.type or "").ljust(12)
                text = "{0} {1} {2}".format(name, typ, node.value or "")
                if node.excluded_from_build:
                    text = text + " [excluded from build]"
                return text
            return "{0}    {1}".format(node.name, _branch_summary(node))

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
                root_ui = TreeNode(self._node_text(root_model))
                root_ui.Name = root_model.path
                root_ui.Tag = 0
                self._node_models[root_ui] = root_model
                for child in root_model.children:
                    self._add_node(root_ui, child)
                self.tree.Nodes.Add(root_ui)
                self._leaf_count = len(self._all_leaf_nodes)
                root_ui.Expand()
                self.tree.SelectedNode = root_ui
                root_ui.EnsureVisible()
            finally:
                self.tree.EndUpdate()

        def _walk_nodes(self, nodes):
            for i in range(nodes.Count):
                node = nodes[i]
                yield node
                for child in self._walk_nodes(node.Nodes):
                    yield child

        def _leaf_nodes(self):
            return [n for n in self._walk_nodes(self.tree.Nodes) if n.Tag == 1]

        def _selected_paths(self):
            return [str(n.Name) for n in self._leaf_nodes() if n.Checked]

        def _first_checked_label(self):
            for node in self._walk_nodes(self.tree.Nodes):
                if node.Checked:
                    return str(node.Name or node.Text or "preset")
            return "preset"

        def _set_children_checked(self, node, checked):
            delta = 0
            for i in range(node.Nodes.Count):
                child = node.Nodes[i]
                if child.Tag == 1:
                    if child.Checked != checked:
                        delta += 1 if checked else -1
                child.Checked = checked
                delta += self._set_children_checked(child, checked)
            return delta

        def _update_parent_state(self, start_node):
            parent = start_node.Parent
            while parent is not None:
                checked_count = 0
                for i in range(parent.Nodes.Count):
                    if parent.Nodes[i].Checked:
                        checked_count += 1
                model = self._node_models.get(parent)
                total = model.leaf_count if model else len(self._leaf_nodes())
                if checked_count == 0:
                    parent.Checked = False
                elif checked_count == total:
                    parent.Checked = True
                else:
                    parent.Checked = False
                parent = parent.Parent

        def _on_after_check(self, sender, args):
            if self._checking:
                return
            self._checking = True
            try:
                delta = self._set_children_checked(args.Node, args.Node.Checked)
                self._selected_count += delta
                self._update_parent_state(args.Node)
            finally:
                self._checking = False
            self._update_status()

        def _update_status(self):
            self.status.Text = "Selected: {0}/{1} leaves".format(
                self._selected_count, self._leaf_count)

        def _search_matches(self, query):
            matches = []
            for ui_node in self._all_leaf_nodes:
                model = self._node_models.get(ui_node)
                text = model.search_text if model else "{0} {1}".format(ui_node.Name, ui_node.Text).lower()
                if query in text:
                    matches.append(ui_node)
            return matches

        def _current_match_index(self, matches):
            current = self.tree.SelectedNode
            if current is None:
                return -1
            for i in range(len(matches)):
                if matches[i] is current:
                    return i
            return -1

        def _select_search_match(self, direction):
            query = self.search_box.Text.strip().lower()
            if not query:
                return
            matches = self._search_matches(query)
            if not matches:
                self._last_search_query = query
                self._last_search_index = -1
                MessageBox.Show("No matching variable path.", "Search",
                                MessageBoxButtons.OK, MessageBoxIcon.Information)
                return
            if query != self._last_search_query:
                index = 0 if direction >= 0 else len(matches) - 1
            else:
                current_index = self._current_match_index(matches)
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

        def _default_path(self, label):
            return _default_preset_path(project, label or "preset")

        def _on_save(self, sender, args):
            paths = self._selected_paths()
            if not paths:
                MessageBox.Show("Select at least one leaf variable.", "Save",
                                MessageBoxButtons.OK, MessageBoxIcon.Warning)
                return
            default_label = _snapshot_default_label(self._first_checked_label())
            default_path = self._default_path(default_label)
            dialog = SaveFileDialog()
            dialog.Filter = "JSON presets (*.json)|*.json|All files (*.*)|*.*"
            dialog.FileName = os.path.basename(default_path)
            directory = os.path.dirname(default_path)
            if os.path.isdir(directory):
                dialog.InitialDirectory = directory
            if dialog.ShowDialog(self) != DialogResult.OK:
                return
            label = os.path.splitext(os.path.basename(dialog.FileName))[0]
            data = take(paths=paths, app=app, label=label, project=project)
            save(data, dialog.FileName)
            self._last_data = data
            MessageBox.Show("Saved {0} variables.".format(len(_vars_from_data(data))),
                            "Save", MessageBoxButtons.OK, MessageBoxIcon.Information)

        def _load_dialog(self):
            dialog = OpenFileDialog()
            dialog.Filter = "JSON presets (*.json)|*.json|All files (*.*)|*.*"
            directory = os.path.dirname(_default_preset_path(project, "preset"))
            if os.path.isdir(directory):
                dialog.InitialDirectory = directory
            if dialog.ShowDialog(self) != DialogResult.OK:
                return None
            return load(dialog.FileName)

        def _format_diff(self, report):
            return (
                "same: {0}\nmissing: {1}\ntype changed: {2}\nvalue changed: {3}"
                .format(
                    len(report.get("same", [])),
                    len(report.get("missing", [])),
                    len(report.get("type_changed", [])),
                    len(report.get("value_changed", [])),
                )
            )

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
                self._recompute_parent_states()
            finally:
                self.tree.EndUpdate()
                self._checking = False
            self._update_status()
            MessageBox.Show("Loaded {0} variables.".format(len(paths)), "Load",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)

        def _recompute_parent_states(self):
            seen = set()
            for leaf in self._all_leaf_nodes:
                parent = leaf.Parent
                while parent is not None and id(parent) not in seen:
                    seen.add(id(parent))
                    parent = parent.Parent
            # Process deepest first by sorting on path depth (Name dots).
            parents = list(seen)
            parents.sort(key=lambda n: str(n.Name).count("."), reverse=True)
            for parent in parents:
                model = self._node_models.get(parent)
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

        def _on_diff(self, sender, args):
            data = self._last_data or self._load_dialog()
            if data is None:
                return
            current = take([v.get("path", "") for v in _vars_from_data(data)], project=project)
            report = compare(data, current=current)
            MessageBox.Show(self._format_diff(report), "Diff",
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
            current = take([v.get("path", "") for v in _vars_from_data(data)], project=project)
            report = compare(data, current=current)
            answer = MessageBox.Show(
                self._format_diff(report) + "\n\nWrite matching variables to PLC?",
                "Restore",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning,
            )
            if answer != DialogResult.Yes:
                return
            result = restore(data, apply=True, project=project)
            MessageBox.Show(
                "Written: {0}\nSkipped: {1}".format(result.get("written"), result.get("skipped")),
                "Restore",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
            )
            self._last_data = data

        def _on_close(self, sender, args):
            self.Close()

        def _on_closed(self, sender, args):
            self._closed = True

    form = SnapshooterForm()
    form.Show()
    while not form._closed:
        Application.DoEvents()
        time.sleep(0.05)
    return form._last_data
