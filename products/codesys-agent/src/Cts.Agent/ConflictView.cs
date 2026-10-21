// The conflict window (ConflictReview): digit 1 or 2 of the quick window
// found objects both sides changed in the same lines.  Each is a row on the
// left; the one chosen shows on the right side by side, the side the run
// overwrites on the left and the side it carries on the right, the lines that
// differ marked.  Disk wins, IDE wins or Merge by hand settles it and goes on
// to the next open one; Force at the top makes the carried side win
// everywhere (the row's Shift run).  Apply, once every row is settled, runs
// the row's command with the choices and shows its verdict; F5 lists what is
// still in conflict (an edit meanwhile).
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed class ConflictView : ToolWindow
    {
        static readonly Color Differs = Color.FromArgb(88, 72, 30);

        readonly string _command;
        readonly string[] _forced;
        //: The side the row's command carries: the disk for an import, the IDE for an export.
        readonly bool _carriesDisk;
        readonly ListBox _list;
        readonly Label _about;
        readonly RichTextBox _left;
        readonly RichTextBox _right;
        readonly Button _apply;
        readonly Button[] _choices;
        List<ConflictItem> _items;
        bool _given;
        bool _busy;

        // *items* from the quick window's dry run; *command* "import" or
        // "export", *forced* its Shift run.
        public ConflictView(string title, List<ConflictItem> items, string command, string[] forced, Action<string[], bool, Action<bool, string>> cts)
            : base(title, new Size(1180, 680), cts)
        {
            _items = items;
            _given = true;
            _command = command;
            _forced = forced;
            _carriesDisk = command == "import";
            var force = FlatButton(_carriesDisk ? "&Force: the disk wins everywhere" : "&Force: the IDE wins everywhere", () => Run(_forced));
            force.Margin = new Padding(4, 5, 4, 5);
            var top = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 36, BackColor = Bar, WrapContents = false };
            top.Controls.Add(force);
            top.Controls.Add(new Label { Text = "what each side held goes on refs/cts/overwritten first", AutoSize = true, ForeColor = Muted, Font = Mono, Margin = new Padding(8, 10, 0, 0) });
            _list = RowList(20, DrawRow);
            _list.SelectedIndexChanged += (s, e) => Preview();
            var left = new Panel { Dock = DockStyle.Left, Width = 300 };
            left.Controls.Add(_list);
            _about = new Label { Dock = DockStyle.Fill, ForeColor = Ink, Font = Mono, TextAlign = ContentAlignment.MiddleLeft, AutoEllipsis = true };
            _left = CodePane();
            _right = CodePane();
            var panes = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 4, BackColor = Back };
            panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            panes.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));
            panes.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
            panes.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            panes.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            panes.Controls.Add(_about, 0, 0);
            panes.SetColumnSpan(_about, 2);
            panes.Controls.Add(Caption(_carriesDisk ? "IDE now (overwritten)" : "Disk now (overwritten)"), 0, 1);
            panes.Controls.Add(Caption(_carriesDisk ? "Disk (carried)" : "IDE (carried)"), 1, 1);
            panes.Controls.Add(_left, 0, 2);
            panes.Controls.Add(_right, 1, 2);
            _choices = new[]
            {
                Choice("&Disk wins", ConflictSide.Disk),
                Choice("&IDE wins", ConflictSide.Ide),
                Choice("&Merge by hand...", ConflictSide.Hand),
            };
            var choices = new FlowLayoutPanel { Dock = DockStyle.Fill, BackColor = Bar, WrapContents = false };
            choices.Controls.AddRange(_choices);
            panes.Controls.Add(choices, 0, 3);
            panes.SetColumnSpan(choices, 2);
            _apply = FlatButton("&Apply", () => Run(ConflictReview.Args(_command, _items)));
            _apply.Margin = new Padding(4, 5, 4, 5);
            var cancel = FlatButton("Cancel", Close);
            cancel.Margin = new Padding(4, 5, 4, 5);
            var bar = new FlowLayoutPanel { Dock = DockStyle.Right, AutoSize = true, BackColor = Bar, WrapContents = false };
            bar.Controls.AddRange(new Control[] { _apply, cancel });
            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 36, BackColor = Bar, Padding = new Padding(8, 0, 0, 0) };
            bottom.Controls.Add(Status);
            bottom.Controls.Add(bar);
            Controls.Add(panes);
            Controls.Add(left);
            Controls.Add(top);
            Controls.Add(bottom);
        }

        Label Caption(string text)
        {
            return new Label { Text = text, Dock = DockStyle.Fill, ForeColor = Muted, Font = Mono, TextAlign = ContentAlignment.MiddleLeft };
        }

        Button Choice(string text, ConflictSide side)
        {
            var button = FlatButton(text, () => Settle(side));
            button.Margin = new Padding(4, 5, 4, 5);
            return button;
        }

        // ---- the list, the panes and the choices

        // The items as they are: from the quick window first, after that from a dry run (F5, or an Apply that left some).
        protected override void Reload()
        {
            if (_given)
            {
                _given = false;
                Fill();
                return;
            }
            if (_busy) return;
            Busy("reading the conflicts again ...");
            RunCts(ConflictReview.DryRun, true, (ok, said) =>
            {
                Idle();
                if (!ok) { Say(said, Bad); return; }
                try { _items = ConflictReview.Parse(said); }
                catch (JsonException e) { Say("cts import --dry-run answered no list: " + e.Message, Bad); return; }
                Fill();
            });
        }

        void Fill()
        {
            _list.BeginUpdate();
            _list.Items.Clear();
            foreach (var item in _items) _list.Items.Add(item.Name);
            _list.EndUpdate();
            if (_items.Count == 0)
            {
                Preview();
                Say("no object is changed on both sides in the same lines now", Good);
                return;
            }
            _list.SelectedIndex = 0;
            Say(_items.Count + " object(s) changed in the IDE and on disk in the same lines: choose the side that wins each", Muted);
        }

        ConflictItem Current => _list.SelectedIndex >= 0 && _list.SelectedIndex < _items.Count ? _items[_list.SelectedIndex] : null;

        void Preview()
        {
            var item = Current;
            foreach (var button in _choices) button.Enabled = item != null && !_busy;
            _apply.Enabled = !_busy && _items.Count > 0 && ConflictReview.Args(_command, _items) != null;
            if (item == null)
            {
                _about.Text = "";
                _left.Text = "";
                _right.Text = "";
                return;
            }
            _about.Text = item.Name + " — " + item.Path + ": both changed the same lines";
            var overwritten = _carriesDisk ? item.Ide : item.Disk;
            var carried = _carriesDisk ? item.Disk : item.Ide;
            CodeText.Show(_left, overwritten);
            CodeText.Show(_right, carried);
            var diff = FmtReview.Changed(overwritten, carried);
            Mark(_left, diff.Left);
            Mark(_right, diff.Right);
            var first = diff.Right.Concat(diff.Left).DefaultIfEmpty(0).Min();
            ScrollNear(_left, first);
            ScrollNear(_right, first);
        }

        static void Mark(RichTextBox box, IEnumerable<int> lines)
        {
            var text = box.Lines;
            foreach (var line in lines)
            {
                var start = box.GetFirstCharIndexFromLine(line);
                if (start < 0) continue;
                box.Select(start, text[line].Length + 1);
                box.SelectionBackColor = Differs;
            }
            box.Select(0, 0);
        }

        static void ScrollNear(RichTextBox box, int line)
        {
            var start = box.GetFirstCharIndexFromLine(Math.Max(0, line - 3));
            if (start < 0) return;
            box.Select(start, 0);
            box.ScrollToCaret();
        }

        // The side chosen for the row shown; on to the next one still open.
        void Settle(ConflictSide side)
        {
            var item = Current;
            if (item == null || _busy) return;
            item.Side = side;
            _list.Invalidate();
            var next = ConflictReview.NextOpen(_items, _list.SelectedIndex);
            if (next >= 0) _list.SelectedIndex = next;
            else
            {
                Preview();
                Say("every object has its side: Apply runs cts " + _command + " with them", Good);
            }
        }

        void DrawRow(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0 || e.Index >= _items.Count) return;
            var item = _items[e.Index];
            var selected = (e.State & DrawItemState.Selected) != 0;
            using (var fill = new SolidBrush(selected ? Bar : Back))
                e.Graphics.FillRectangle(fill, e.Bounds);
            var open = item.Side == ConflictSide.Open;
            var mark = ConflictReview.Mark(item);
            var markWidth = TextRenderer.MeasureText(mark, Mono).Width;
            var labelBox = new Rectangle(e.Bounds.X + 6, e.Bounds.Y, e.Bounds.Width - markWidth - 12, e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, (open ? "● " : "✔ ") + item.Name, Mono, labelBox, open ? Ink : Muted, TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter);
            TextRenderer.DrawText(e.Graphics, mark, Mono, new Rectangle(e.Bounds.Right - markWidth - 4, e.Bounds.Y, markWidth, e.Bounds.Height),
                open ? Bad : Good, TextFormatFlags.VerticalCenter);
        }

        // ---- the run

        void Run(string[] args)
        {
            if (_busy || args == null) return;
            Busy("cts " + ProcessArgs.Join(args) + " ...");
            RunCts(args, false, (ok, line) =>
            {
                if (ok)
                {
                    _items = new List<ConflictItem>();
                    _list.Items.Clear();
                }
                Idle();
                // A run left in conflict (an edit meanwhile) keeps the rows: F5 lists what is left.
                Say(ok ? line : line + "   (F5 lists the conflicts again)", ok ? Good : Bad);
            });
        }

        void Busy(string what)
        {
            _busy = true;
            Preview();
            Say(what, Muted);
        }

        void Idle()
        {
            _busy = false;
            Preview();
        }
    }
}
