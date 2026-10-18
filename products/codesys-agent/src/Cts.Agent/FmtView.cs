// The format window (the quick window's More page, 1): the IDE's Structured Text
// objects as `cts fmt --json` lays them out, the one chosen side by side as
// the IDE has it and as the formatter would write it, the lines that differ
// marked on both sides.  Apply writes that object (`cts fmt --guid G --write
// --if-timestamp T`, so an object edited since it was read is refused) and
// goes on to the next one to fix; Skip goes on without writing.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed class FmtView : ToolWindow
    {
        static readonly Color Gone = Color.FromArgb(80, 38, 40);
        static readonly Color Added = Color.FromArgb(30, 68, 42);

        const int EM_GETFIRSTVISIBLELINE = 0x00CE;
        const int EM_LINESCROLL = 0x00B6;

        readonly TextBox _filter;
        readonly ListBox _list;
        readonly RichTextBox _before;
        readonly RichTextBox _after;
        readonly Button _apply;
        readonly Button _skip;
        readonly Button _reload;
        List<FmtItem> _items = new List<FmtItem>();
        List<FmtItem> _shown = new List<FmtItem>();
        FmtItem _current;
        FmtDiff _diff;
        bool _busy;
        bool _scrolling;
        //: The change the panes were last brought to.
        int _at = -1;

        public FmtView(string title, Action<string[], bool, Action<bool, string>> cts)
            : base(title, new Size(1180, 680), cts)
        {
            _filter = FilterBox(DockStyle.Top);
            _filter.TextChanged += (s, e) => Fill(_current);
            _list = RowList(18, DrawRow);
            _list.SelectedIndexChanged += (s, e) => Preview(_list.SelectedIndex >= 0 ? _shown[_list.SelectedIndex] : null);
            var left = new Panel { Dock = DockStyle.Left, Width = 320 };
            left.Controls.Add(_list);
            left.Controls.Add(_filter);
            _before = CodePane();
            _after = CodePane();
            _before.VScroll += (s, e) => Follow(_before, _after);
            _after.VScroll += (s, e) => Follow(_after, _before);
            var panes = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2, BackColor = Back };
            panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            panes.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
            panes.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            panes.Controls.Add(Caption("In the IDE now"), 0, 0);
            panes.Controls.Add(Caption("Formatted"), 1, 0);
            panes.Controls.Add(_before, 0, 1);
            panes.Controls.Add(_after, 1, 1);
            _apply = Action("&Apply", Apply);
            _skip = Action("&Skip", () => Next(_current));
            _reload = Action("&Reload", Reload);
            var bar = new FlowLayoutPanel { Dock = DockStyle.Right, AutoSize = true, BackColor = Bar, WrapContents = false };
            bar.Controls.AddRange(new Control[] { Action("&Previous change", () => Jump(false)), Action("&Next change", () => Jump(true)), _apply, _skip, _reload });
            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 36, BackColor = Bar, Padding = new Padding(8, 0, 0, 0) };
            bottom.Controls.Add(Status);
            bottom.Controls.Add(bar);
            Controls.Add(panes);
            Controls.Add(left);
            Controls.Add(bottom);
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            switch (keyData)
            {
                case Keys.F8: Jump(true); return true;
                case Keys.Shift | Keys.F8: Jump(false); return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        Label Caption(string text)
        {
            return new Label { Text = text, Dock = DockStyle.Fill, ForeColor = Muted, Font = Mono, TextAlign = ContentAlignment.MiddleLeft };
        }

        Button Action(string text, Action run)
        {
            var button = FlatButton(text, run);
            button.Margin = new Padding(4, 5, 4, 5);
            return button;
        }

        // ---- reading and writing through cts

        protected override void Reload()
        {
            if (_busy) return;
            Busy("reading the IDE's Structured Text ...");
            var keep = _current?.Guid;
            RunCts(new[] { "fmt", "--json" }, true, (ok, said) =>
            {
                Idle();
                if (!ok) { Say(said, Bad); return; }
                try { _items = FmtReview.Parse(said); }
                catch (JsonException e) { Say("cts fmt answered no list: " + e.Message, Bad); return; }
                var kept = _items.FirstOrDefault(item => item.Guid == keep);
                Fill(kept ?? Pick(FmtReview.NextToFix(_items, -1)));
                var toFix = _items.Count(item => item.Lines > 0);
                Say(toFix == 0 ? _items.Count + " objects, nothing to fix"
                    : toFix + " of " + _items.Count + " objects to fix, " + _items.Sum(item => item.Lines) + " line(s)", toFix == 0 ? Good : Muted);
            });
        }

        void Apply()
        {
            var item = _current;
            if (_busy || item == null || item.Lines == 0) return;
            Busy("writing " + item.Label + " ...");
            RunCts(new[] { "fmt", "--guid", item.Guid, "--write", "--if-timestamp", item.Timestamp.ToString(CultureInfo.InvariantCulture) },
                false, (ok, line) =>
                {
                    Idle();
                    if (!ok) { Say(line, Bad); return; }
                    FmtReview.Written(item);
                    _list.Invalidate();
                    Say("written: " + item.Label, Good);
                    Next(item);
                });
        }

        // The next object to fix after *item* among those shown.
        void Next(FmtItem item)
        {
            var at = item == null ? -1 : _shown.IndexOf(item);
            var next = FmtReview.NextToFix(_shown, at);
            if (next < 0) { Say("no object further down to fix", Good); Preview(item); return; }
            _list.SelectedIndex = next;
        }

        FmtItem Pick(int index)
        {
            return index >= 0 ? _items[index] : _items.FirstOrDefault();
        }

        // ---- the list and the panes

        void Fill(FmtItem select)
        {
            var filter = _filter.Text.Trim();
            _shown = _items.Where(item => filter.Length == 0 || item.Label.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0).ToList();
            _list.BeginUpdate();
            _list.Items.Clear();
            foreach (var item in _shown) _list.Items.Add(item.Label);
            _list.EndUpdate();
            var index = select == null ? -1 : _shown.IndexOf(select);
            if (index >= 0) _list.SelectedIndex = index;
            else Preview(null);
        }

        void Preview(FmtItem item)
        {
            _current = item;
            _apply.Enabled = !_busy && item != null && item.Lines > 0;
            if (item == null || item.Lines == 0)
            {
                _diff = null;
                _before.Text = "";
                _after.Text = "";
                if (item != null) Say(item.Label + ": the formatter leaves it as it is", Good);
                return;
            }
            CodeText.Show(_before, item.Before);
            CodeText.Show(_after, item.After);
            _diff = FmtReview.Changed(item.Before, item.After);
            Mark(_before, _diff.Left, Gone);
            Mark(_after, _diff.Right, Added);
            _at = -1;
            Jump(true);
        }

        static void Mark(RichTextBox box, IEnumerable<int> lines, Color color)
        {
            var text = box.Lines;
            foreach (var line in lines)
            {
                var start = box.GetFirstCharIndexFromLine(line);
                if (start < 0) continue;
                box.Select(start, text[line].Length + 1);
                box.SelectionBackColor = color;
            }
            box.Select(0, 0);
        }

        // The next (or previous) run of changed lines, near the top of both
        // panes: those the formatter writes, or, when it only drops lines,
        // those it drops.
        void Jump(bool forward)
        {
            if (_diff == null) return;
            var right = _diff.Right.Count > 0;
            var lines = right ? _diff.Right : _diff.Left;
            var line = FmtReview.NextChange(lines, _at, forward);
            if (line < 0) return;
            _at = line;
            var pane = right ? _after : _before;
            ScrollTo(pane, Math.Max(0, line - 3));
            Follow(pane, right ? _before : _after);
            var runs = FmtReview.Runs(lines);
            Say(_current.Label + ": change " + (runs.IndexOf(line) + 1) + " of " + runs.Count + ", " + _current.Lines + " line(s)", Muted);
        }

        // The other pane follows *from*: the formatted side's line maps to
        // the line beside it before the formatter.
        void Follow(RichTextBox from, RichTextBox to)
        {
            if (_scrolling || _diff == null) return;
            _scrolling = true;
            try
            {
                var top = FirstVisible(from);
                var map = _diff.LeftOf;
                var target = from == _after
                    ? (top < map.Length ? map[top] : top)
                    : Math.Max(0, Array.FindIndex(map, left => left >= top));
                ScrollTo(to, target);
            }
            finally { _scrolling = false; }
        }

        static int FirstVisible(RichTextBox box)
        {
            return (int)Win32.SendMessage(box.Handle, EM_GETFIRSTVISIBLELINE, IntPtr.Zero, IntPtr.Zero);
        }

        static void ScrollTo(RichTextBox box, int line)
        {
            Win32.SendMessage(box.Handle, EM_LINESCROLL, IntPtr.Zero, (IntPtr)(line - FirstVisible(box)));
        }

        void DrawRow(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0 || e.Index >= _shown.Count) return;
            var item = _shown[e.Index];
            var selected = (e.State & DrawItemState.Selected) != 0;
            using (var fill = new SolidBrush(selected ? Bar : Back))
                e.Graphics.FillRectangle(fill, e.Bounds);
            var mark = item.Lines > 0 ? item.Lines + " to fix" : "OK";
            var markWidth = TextRenderer.MeasureText(mark, Mono).Width;
            var labelBox = new Rectangle(e.Bounds.X + 6, e.Bounds.Y, e.Bounds.Width - markWidth - 12, e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, item.Label, Mono, labelBox, Ink, TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter);
            TextRenderer.DrawText(e.Graphics, mark, Mono, new Rectangle(e.Bounds.Right - markWidth - 4, e.Bounds.Y, markWidth, e.Bounds.Height),
                item.Lines > 0 ? Muted : Good, TextFormatFlags.VerticalCenter);
        }

        // ---- the status line

        void Busy(string what)
        {
            _busy = true;
            _apply.Enabled = _skip.Enabled = _reload.Enabled = false;
            Say(what, Muted);
        }

        void Idle()
        {
            _busy = false;
            _skip.Enabled = _reload.Enabled = true;
            _apply.Enabled = _current != null && _current.Lines > 0;
        }
    }
}
