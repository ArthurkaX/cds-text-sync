// The analysis window (quick window More, `5`): the findings `cts analyze`
// reports for the sync folder's .st files, the most severe first.  The one
// chosen shows its lines of the file, marked, and its rule's documentation.
// Suppress (with a reason), Fix later and Baseline file the selected findings
// through `cts analyze triage`; Rules lists the catalog, Enter switches one on
// or off for the sync folder (`cts analyze rules --enable|--disable`).  F5
// runs the analysis again, the status line counting its seconds and naming
// the rule it reached.  The analysis reads the disk, not the IDE: what an
// export last wrote.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed class AnalysisView : ToolWindow, IStages
    {
        static readonly Color Warn = Color.FromArgb(230, 160, 80);
        //: Lines shown above and below each line of a finding.
        const int Radius = 5;

        readonly TextBox _filter;
        readonly ComboBox _severity;
        readonly ListBox _list;
        readonly Label _heading;
        readonly RichTextBox _code;
        readonly TextBox _doc;
        //: The finding's lines over the rule's documentation.
        readonly SplitContainer _panes;
        readonly Button _run;
        readonly Button _rules;
        readonly Button[] _triage;
        AnalysisRun _analysis = new AnalysisRun();
        List<AnalysisRule> _catalog = new List<AnalysisRule>();
        List<AnalysisFinding> _findings = new List<AnalysisFinding>();
        List<AnalysisRule> _shownRules = new List<AnalysisRule>();
        //: The list shows the rules instead of the findings.
        bool _rulesMode;
        bool _busy;
        //: The analysis running: its time, the stage cts named last.
        readonly Timer _tick = new Timer { Interval = 1000 };
        readonly Stopwatch _clock = new Stopwatch();
        string _stage;

        public AnalysisView(string title, Action<string[], bool, Action<bool, string>> cts)
            : base(title, new Size(1200, 720), cts)
        {
            _filter = FilterBox(DockStyle.Fill);
            _filter.TextChanged += (s, e) => Fill();
            _severity = new ComboBox { Dock = DockStyle.Right, Width = 120, DropDownStyle = ComboBoxStyle.DropDownList, FlatStyle = FlatStyle.Flat, BackColor = Bar, ForeColor = Ink, Font = Mono };
            _severity.Items.Add("all");
            foreach (var severity in AnalysisReport.Severities) _severity.Items.Add(severity);
            _severity.SelectedIndex = 0;
            _severity.SelectedIndexChanged += (s, e) => Fill();
            var top = new Panel { Dock = DockStyle.Top, Height = 24 };
            top.Controls.Add(_filter);
            top.Controls.Add(_severity);
            _list = RowList(36, DrawRow);
            _list.SelectionMode = SelectionMode.MultiExtended;
            _list.SelectedIndexChanged += (s, e) => ShowChosen();
            _list.DoubleClick += (s, e) => { if (_rulesMode) SwitchRule(); };
            _heading = new Label { Dock = DockStyle.Top, ForeColor = Ink, Font = Mono, Padding = new Padding(6, 4, 6, 4) };
            _code = CodePane();
            _doc = new TextBox
            {
                Dock = DockStyle.Fill,
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                BorderStyle = BorderStyle.None,
                BackColor = Bar,
                ForeColor = Ink,
                Font = Mono,
            };
            // The list | the finding's lines over its rule's documentation; each splitter dragged.
            // A SplitContainer clamps the distance to its size: the size first.
            var outer = new SplitContainer { Size = ClientSize, Dock = DockStyle.Fill, SplitterDistance = 460, SplitterWidth = 5, FixedPanel = FixedPanel.Panel1, BackColor = Bar };
            outer.Panel1.Controls.Add(_list);
            outer.Panel1.Controls.Add(top);
            var right = _panes = new SplitContainer { Size = new Size(ClientSize.Width - 465, ClientSize.Height - 34), Dock = DockStyle.Fill, Orientation = Orientation.Horizontal, SplitterDistance = 400, SplitterWidth = 5, BackColor = Bar };
            right.Panel1.Controls.Add(_code);
            right.Panel1.Controls.Add(_heading);
            right.Panel2.Controls.Add(_doc);
            right.Panel1.Resize += (s, e) => FitHeading();
            outer.Panel2.Controls.Add(right);
            _run = Action("&Run", Reload);
            _rules = Action("Rul&es", ToggleRules);
            _triage = new[]
            {
                Action("&Suppress", () => Triage("suppress")),
                Action("&Fix later", () => Triage("fix-later")),
                Action("&Baseline", () => Triage("baseline")),
            };
            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 34, BackColor = Bar, Padding = new Padding(8, 4, 8, 4) };
            bottom.Controls.Add(Status);
            foreach (var button in _triage.Concat(new[] { _rules, _run })) bottom.Controls.Add(button);
            Controls.Add(outer);
            Controls.Add(bottom);
            _tick.Tick += (s, e) => SayRunning();
            FormClosed += (s, e) => _tick.Dispose();
        }

        Button Action(string text, Action click)
        {
            var button = FlatButton(text, click);
            button.Dock = DockStyle.Right;
            return button;
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            switch (keyData)
            {
                case Keys.Control | Keys.F: _filter.Focus(); return true;
                case Keys.Control | Keys.C when !_filter.Focused: Copy(); return true;
                case Keys.Enter when _rulesMode && _list.Focused:
                case Keys.Space when _rulesMode && _list.Focused: SwitchRule(); return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        // ---- reading through cts

        protected override void Reload()
        {
            if (_busy) return;
            Busy(true);
            _stage = null;
            _clock.Restart();
            _tick.Start();
            SayRunning();
            RunCts(new[] { "analyze", "--json", "--fail-on", "never", "--incomplete", "ignore" }, true, (ok, said) =>
            {
                _tick.Stop();
                if (!ok) { Busy(false); Say(said, Bad); return; }
                try { _analysis = AnalysisReport.Parse(said); }
                catch (JsonException e) { Busy(false); Say("cts analyze answered no report: " + e.Message, Bad); return; }
                ReadRules(null, () => Say(_analysis.Summary, _analysis.Complete ? Good : Warn));
            });
        }

        public void Stage(string stage)
        {
            Later(() => { _stage = stage; if (_tick.Enabled) SayRunning(); });
        }

        void SayRunning()
        {
            Say("analysing the sync folder's Structured Text" + (_stage == null ? "" : " · " + _stage) + " · " + (int)_clock.Elapsed.TotalSeconds + " s", Muted);
        }

        // The catalog with this folder's switches, *change* (`--enable ID`
        // or `--disable ID`) made first; *then* when it is read.
        void ReadRules(string[] change, Action then)
        {
            var args = new List<string> { "analyze", "rules", "--workspace", _analysis.Workspace, "--doc", "--json" };
            if (change != null) args.AddRange(change);
            Busy(true);
            RunCts(args.ToArray(), true, (ok, said) =>
            {
                Busy(false);
                if (!ok) { Say(said, Bad); return; }
                try { _catalog = AnalysisReport.Rules(said); }
                catch (JsonException e) { Say("cts analyze rules answered no list: " + e.Message, Bad); return; }
                Fill();
                then();
            });
        }

        void Triage(string action)
        {
            var chosen = ChosenFindings();
            if (_busy || chosen.Count == 0) return;
            var reason = "";
            if (action == "suppress")
            {
                reason = Ask(chosen.Count == 1 ? "Why is this finding not a problem?" : "Why are these " + chosen.Count + " findings not a problem?");
                if (reason == null) return;
            }
            var file = Path.GetTempFileName();
            File.WriteAllText(file, AnalysisReport.Decisions(chosen, action, reason));
            Busy(true);
            RunCts(new[] { "analyze", "triage", "--workspace", _analysis.Workspace, "--apply", file }, false, (ok, said) =>
            {
                File.Delete(file);
                Busy(false);
                if (!ok) { Say(said, Bad); return; }
                Reload();
            });
        }

        void SwitchRule()
        {
            var rule = _list.SelectedIndex >= 0 && _list.SelectedIndex < _shownRules.Count ? _shownRules[_list.SelectedIndex] : null;
            if (_busy || rule == null) return;
            ReadRules(new[] { rule.Enabled ? "--disable" : "--enable", rule.Id },
                () => Say(rule.Id + (rule.Enabled ? " off" : " on") + " for this sync folder; F5 runs the analysis with it", Good));
        }

        // ---- the list

        void ToggleRules()
        {
            _rulesMode = !_rulesMode;
            _rules.Text = _rulesMode ? "Find&ings" : "Rul&es";
            foreach (var button in _triage) button.Visible = !_rulesMode;
            // A rule has no lines to show: its documentation takes the whole side.
            _panes.Panel2Collapsed = _rulesMode;
            Fill();
        }

        void Fill()
        {
            var severity = _severity.SelectedIndex > 0 ? (string)_severity.SelectedItem : null;
            var filter = _filter.Text.Trim();
            _list.BeginUpdate();
            _list.Items.Clear();
            if (_rulesMode)
            {
                _shownRules = _catalog.Where(rule => (severity == null || rule.Severity == severity)
                    && (filter.Length == 0 || new[] { rule.Id, rule.Title, rule.Summary }.Any(field => field.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0))).ToList();
                foreach (var rule in _shownRules) _list.Items.Add(rule.Id);
            }
            else
            {
                _findings = AnalysisReport.Shown(_analysis.Findings, severity, filter);
                foreach (var finding in _findings) _list.Items.Add(finding.Where);
            }
            _list.EndUpdate();
            if (_list.Items.Count > 0) _list.SelectedIndex = 0;
            else ShowChosen();
        }

        List<AnalysisFinding> ChosenFindings()
        {
            return _rulesMode ? new List<AnalysisFinding>() : _list.SelectedIndices.Cast<int>().Where(i => i < _findings.Count).Select(i => _findings[i]).ToList();
        }

        void DrawRow(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            var selected = (e.State & DrawItemState.Selected) != 0;
            using (var fill = new SolidBrush(selected ? Bar : Back))
                e.Graphics.FillRectangle(fill, e.Bounds);
            string first, second, severity;
            var mark = Muted;
            if (_rulesMode)
            {
                if (e.Index >= _shownRules.Count) return;
                var rule = _shownRules[e.Index];
                first = (rule.Enabled ? "[x] " : "[ ] ") + rule.Id + "  " + rule.Title;
                second = "    " + rule.Summary;
                severity = rule.Severity;
                if (rule.Enabled) mark = Good;
            }
            else
            {
                if (e.Index >= _findings.Count) return;
                var finding = _findings[e.Index];
                // The file and line; the heading shows the whole path.
                first = finding.RuleId + "  " + finding.Where.Substring(finding.Where.LastIndexOfAny(new[] { '/', '\\' }) + 1);
                second = finding.Message;
                severity = finding.Severity;
            }
            using (var stripe = new SolidBrush(Tone(severity)))
                e.Graphics.FillRectangle(stripe, e.Bounds.X, e.Bounds.Y + 3, 3, e.Bounds.Height - 6);
            var half = e.Bounds.Height / 2;
            TextRenderer.DrawText(e.Graphics, first, Mono, new Rectangle(e.Bounds.X + 8, e.Bounds.Y + 1, e.Bounds.Width - 10, half), _rulesMode ? mark : Ink,
                TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter);
            TextRenderer.DrawText(e.Graphics, second, Mono, new Rectangle(e.Bounds.X + 8, e.Bounds.Y + half - 1, e.Bounds.Width - 10, half), Muted,
                TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter);
        }

        static Color Tone(string severity)
        {
            return severity == "danger" ? Bad : severity == "suspicious" ? Warn : Muted;
        }

        // ---- the chosen finding or rule

        void ShowChosen()
        {
            var index = _list.SelectedIndex;
            if (_rulesMode)
            {
                var rule = index >= 0 && index < _shownRules.Count ? _shownRules[index] : null;
                _heading.Text = rule == null ? "" : rule.Id + " · " + rule.Title + " · " + rule.Severity + (rule.Enabled ? " · on" : " · off") + "\nEnter switches it for this sync folder.";
                _code.Text = rule == null ? "" : Doc(rule);
            }
            else
            {
                var finding = index >= 0 && index < _findings.Count ? _findings[index] : null;
                _heading.Text = finding == null ? (_analysis.Findings.Count == 0 ? "" : "No finding matches the filter.")
                    : finding.RuleId + " · " + finding.RuleTitle + " · " + finding.Severity + "\n" + finding.Where + "\n" + finding.Message;
                ShowLines(finding);
                ShowDoc(finding == null ? null : _catalog.FirstOrDefault(rule => rule.Id == finding.RuleId));
            }
            FitHeading();
        }

        void ShowLines(AnalysisFinding finding)
        {
            if (finding == null) { _code.Text = ""; return; }
            var file = Path.Combine(_analysis.View, finding.Path);
            try { CodeText.Show(_code, AnalysisReport.Excerpt(File.ReadAllLines(file), finding.Lines, Radius)); }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is ArgumentException) { _code.Text = file + ": " + e.Message; }
        }

        void ShowDoc(AnalysisRule rule)
        {
            _doc.Text = rule == null ? "" : Doc(rule);
        }

        static string Doc(AnalysisRule rule)
        {
            return (rule.Doc.Length > 0 ? rule.Doc : rule.Summary).Replace("\r\n", "\n").Replace("\n", Environment.NewLine);
        }

        // The heading as tall as its wrapped text.
        void FitHeading()
        {
            var width = Math.Max(1, _heading.Width - _heading.Padding.Horizontal);
            var text = TextRenderer.MeasureText(_heading.Text, Mono, new Size(width, int.MaxValue), TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl);
            _heading.Height = text.Height + _heading.Padding.Vertical;
        }

        // The selected findings as lines to paste: `place [rule] message`.
        void Copy()
        {
            var lines = ChosenFindings().Select(f => f.Where + " [" + f.RuleId + "] " + f.Message).ToList();
            if (lines.Count == 0) return;
            Clipboard.SetText(string.Join(Environment.NewLine, lines));
            Say(lines.Count + " finding(s) copied", Good);
        }

        // A line of text the user types in a small dialog; null when cancelled or left empty.
        string Ask(string question)
        {
            using (var dialog = new Form
            {
                Text = "Suppress",
                FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterParent,
                MinimizeBox = false,
                MaximizeBox = false,
                ShowInTaskbar = false,
                BackColor = Back,
                ForeColor = Ink,
                ClientSize = new Size(520, 96),
            })
            {
                var label = new Label { Text = question, Location = new Point(10, 10), AutoSize = true, Font = Mono };
                var reason = new TextBox { Location = new Point(10, 34), Width = 500, BackColor = Bar, ForeColor = Ink, BorderStyle = BorderStyle.FixedSingle, Font = Mono };
                var ok = new Button { Text = "Suppress", DialogResult = DialogResult.OK, Location = new Point(344, 64), FlatStyle = FlatStyle.Flat, BackColor = Bar, ForeColor = Ink };
                var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Location = new Point(430, 64), FlatStyle = FlatStyle.Flat, BackColor = Bar, ForeColor = Ink };
                dialog.Controls.AddRange(new Control[] { label, reason, ok, cancel });
                dialog.AcceptButton = ok;
                dialog.CancelButton = cancel;
                return dialog.ShowDialog(this) == DialogResult.OK && reason.Text.Trim().Length > 0 ? reason.Text.Trim() : null;
            }
        }

        void Busy(bool busy)
        {
            _busy = busy;
            _run.Enabled = !busy;
            _rules.Enabled = !busy;
            foreach (var button in _triage) button.Enabled = !busy;
        }
    }
}
