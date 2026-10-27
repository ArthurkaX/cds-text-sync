// The FSM window (the quick window's More page, 4; quick window More, `4`):
// the state machines in the IDE's Structured Text, saved or not, as `cts fsm
// --layout --json` finds and lays them out.  The list names each object's
// machines; the one chosen is drawn as a GRAFCET chart (numbered steps, guard
// bars, arrows -- the geometry is FsmGrafcet's), and a click on a step or a
// transition shows the code behind it with its line.  The chart moves like a canvas: the wheel zooms
// at the pointer, a drag anywhere pans; Ctrl+plus/minus zoom, Ctrl+0 fits.
// The splitters between the list, the chart and the code move.  Live, while
// the IDE is logged in, reads the machine's variable in one instance a few
// times a second and marks the step it is in and the transition that led
// there (FsmViewLive.cs).
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed partial class FsmView : ToolWindow
    {

        //: One machine of one object: a row of the list.
        sealed class Row
        {
            public FsmObject Owner;
            public FsmMachine Machine;
            public int Index;
        }

        readonly TextBox _filter;
        readonly ListBox _list;
        readonly Chart _chart;
        readonly Label _heading;
        readonly Label _what;
        readonly RichTextBox _code;
        readonly Button _reload;
        List<FsmObject> _objects = new List<FsmObject>();
        List<Row> _shown = new List<Row>();
        bool _busy;

        public FsmView(string title, Action<string[], bool, Action<bool, string>> cts, Func<IList<string>, IDictionary<string, object>> read)
            : base(title, new Size(1280, 760), cts)
        {
            _read = read;
            _filter = FilterBox(DockStyle.Top);
            _filter.TextChanged += (s, e) => Fill(Selected());
            _list = RowList(18, DrawRow);
            _list.SelectedIndexChanged += (s, e) => Draw(Selected());
            _chart = new Chart { Dock = DockStyle.Fill };
            _chart.Picked += ShowCode;
            _heading = new Label { Dock = DockStyle.Top, Height = 24, ForeColor = Muted, Font = Mono, TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(6, 0, 0, 0) };
            var middle = new Panel { Dock = DockStyle.Fill };
            middle.Controls.Add(_chart);
            middle.Controls.Add(WatchBar());
            middle.Controls.Add(_heading);
            _what = new Label { Dock = DockStyle.Top, ForeColor = Ink, Font = Mono, Padding = new Padding(6, 4, 6, 4) };
            _code = CodePane();
            // Side by side, each splitter dragged: the list | the chart | the code.
            var outer = Split(1280, 280);
            outer.Panel1.Controls.Add(_list);
            outer.Panel1.Controls.Add(_filter);
            var inner = Split(1280 - 280 - 5, 1280 - 280 - 5 - 5 - 400);
            inner.FixedPanel = FixedPanel.Panel2;
            inner.Panel1.Controls.Add(middle);
            inner.Panel2.Controls.Add(_code);
            inner.Panel2.Controls.Add(_what);
            inner.Panel2.Resize += (s, e) => FitWhat();
            outer.Panel2.Controls.Add(inner);
            _reload = FlatButton("&Reload", Reload);
            _reload.Dock = DockStyle.Right;
            _live = FlatButton("&Live", ToggleLive);
            _live.Dock = DockStyle.Right;
            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 34, BackColor = Bar, Padding = new Padding(8, 4, 8, 4) };
            bottom.Controls.Add(Status);
            bottom.Controls.Add(_live);
            bottom.Controls.Add(_reload);
            Controls.Add(outer);
            Controls.Add(bottom);
            FormClosed += (s, e) => { _tick.Dispose(); _chart.Dispose(); };
        }

        // A SplitContainer clamps the distance to its size, and a fixed second
        // panel keeps its width when the container takes its real one: the
        // container is made as wide as it will be.
        static SplitContainer Split(int width, int first)
        {
            return new SplitContainer
            {
                Size = new Size(width, 760),
                Dock = DockStyle.Fill,
                SplitterDistance = first,
                SplitterWidth = 5,
                FixedPanel = FixedPanel.Panel1,
                BackColor = Bar,
                Panel1MinSize = 120,
                Panel2MinSize = 160,
            };
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            switch (keyData)
            {
                case Keys.Control | Keys.Oemplus:
                case Keys.Control | Keys.Add: _chart.ZoomAtCentre(1.2f); return true;
                case Keys.Control | Keys.OemMinus:
                case Keys.Control | Keys.Subtract: _chart.ZoomAtCentre(1 / 1.2f); return true;
                case Keys.Control | Keys.D0:
                case Keys.Control | Keys.NumPad0: _chart.Fit(); return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        // ---- reading through cts

        protected override void Reload()
        {
            if (_busy) return;
            _busy = true;
            _reload.Enabled = false;
            Say("reading the IDE's Structured Text ...", Muted);
            var keep = Selected();
            RunCts(new[] { "fsm", "--layout", "--json" }, true, (ok, said) =>
            {
                _busy = false;
                _reload.Enabled = true;
                if (!ok) { Say(said, Bad); return; }
                try { _objects = FsmMap.Parse(said); }
                catch (JsonException e) { Say("cts fsm answered no list: " + e.Message, Bad); return; }
                var rows = Rows(_objects);
                // Before the list: a machine's warnings, when it is drawn, say more.
                Say(rows.Count == 0 ? "no state machine in the project's Structured Text"
                    : rows.Count + " machine(s) in " + _objects.Count + " object(s)", rows.Count == 0 ? Muted : Good);
                Fill(keep == null ? rows.FirstOrDefault()
                    : rows.FirstOrDefault(row => row.Owner.Guid == keep.Owner.Guid && row.Index == keep.Index) ?? rows.FirstOrDefault());
            });
        }

        static List<Row> Rows(IEnumerable<FsmObject> objects)
        {
            return objects.SelectMany(owner => owner.Machines.Select((machine, i) => new Row { Owner = owner, Machine = machine, Index = i })).ToList();
        }

        // ---- the list

        Row Selected()
        {
            return _list.SelectedIndex >= 0 && _list.SelectedIndex < _shown.Count ? _shown[_list.SelectedIndex] : null;
        }

        void Fill(Row select)
        {
            var filter = _filter.Text.Trim();
            _shown = Rows(_objects).Where(row => filter.Length == 0
                || row.Owner.Label.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0
                || row.Machine.Selector.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0).ToList();
            _list.BeginUpdate();
            _list.Items.Clear();
            foreach (var row in _shown) _list.Items.Add(row.Owner.Label);
            _list.EndUpdate();
            var index = select == null ? -1 : _shown.FindIndex(row => row.Owner == select.Owner && row.Index == select.Index);
            if (index < 0 && _shown.Count > 0) index = 0;
            if (index >= 0) _list.SelectedIndex = index;
            else Draw(null);
        }

        void DrawRow(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0 || e.Index >= _shown.Count) return;
            var row = _shown[e.Index];
            var selected = (e.State & DrawItemState.Selected) != 0;
            using (var fill = new SolidBrush(selected ? Bar : Back))
                e.Graphics.FillRectangle(fill, e.Bounds);
            var mark = row.Machine.Selector + " · " + row.Machine.States.Count;
            var markWidth = Math.Min(e.Bounds.Width / 2, TextRenderer.MeasureText(mark, Mono).Width);
            TextRenderer.DrawText(e.Graphics, row.Owner.Label, Mono, new Rectangle(e.Bounds.X + 6, e.Bounds.Y, e.Bounds.Width - markWidth - 12, e.Bounds.Height),
                Ink, TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter);
            TextRenderer.DrawText(e.Graphics, mark, Mono, new Rectangle(e.Bounds.Right - markWidth - 4, e.Bounds.Y, markWidth, e.Bounds.Height),
                Muted, TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter);
        }

        // ---- the chart and the code behind it

        void Draw(Row row)
        {
            _chart.Display(row?.Machine);
            Watch(row);
            ShowCode(null);
            if (row == null) { _heading.Text = ""; return; }
            var machine = row.Machine;
            _heading.Text = row.Owner.Label + " · CASE " + machine.Selector
                + (machine.Layout.Prefix.Length > 0 ? " · labels without " + machine.Layout.Prefix : "")
                + " · " + machine.States.Count + " steps, " + machine.Transitions.Count + " transitions";
            if (machine.Warnings.Count > 0)
                Say((machine.Warnings.Count == 1 ? "" : machine.Warnings.Count + " warnings, first ") + machine.Warnings[0], Muted);
        }

        void ShowCode(FsmCode code)
        {
            if (code == null)
            {
                _what.Text = "Click a step or a transition for the code behind it.";
                _what.ForeColor = Muted;
                _code.Text = "";
                FitWhat();
                return;
            }
            _what.ForeColor = Ink;
            _what.Text = code.Title + (code.Guard != null ? "\n" + (code.Guard.Length > 0 ? code.Guard : "unconditional") : "")
                + "\nline " + code.Line + " of the implementation";
            CodeText.Show(_code, code.Code);
            FitWhat();
        }

        // The heading as tall as its wrapped text, so a long guard never runs under the code.
        void FitWhat()
        {
            var width = Math.Max(1, _what.Width - _what.Padding.Horizontal);
            var text = TextRenderer.MeasureText(_what.Text, Mono, new Size(width, int.MaxValue), TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl);
            _what.Height = text.Height + _what.Padding.Vertical;
        }
    }
}
