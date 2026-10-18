// The agent's activity, live, in a window over the IDE (the quick window's
// More page, 2): every line the agent logs -- the requests it answered, with their
// time when they took one, the IDE's events, the quick window's cts runs --
// and at the bottom what it is answering right now.  The lines are the agent
// log's; the window keeps the last ones of this IDE only, so with two or three
// IDEs open each has its own.
using System;
using System.Drawing;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed class ActivityView : Form
    {
        static readonly Color Accent = Color.FromArgb(96, 165, 250);
        static readonly Color Warn = Color.FromArgb(210, 153, 34);

        const int MaxRows = 2000;
        //: A request shorter than this is not worth naming as running.
        const long ShownAfterMs = 300;

        readonly FileLog _log;
        readonly Router _router;
        readonly ListBox _list;
        readonly Label _now;
        readonly Timer _tick = new Timer { Interval = 250 };
        readonly Font _mono = new Font("Consolas", 9.5f);
        readonly Action<string> _sink;

        public ActivityView(FileLog log, Router router, string title)
        {
            _log = log;
            _router = router;
            Text = title;
            FormBorderStyle = FormBorderStyle.SizableToolWindow;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            KeyPreview = true;
            BackColor = Back;
            ClientSize = new Size(760, 340);
            _list = new ListBox
            {
                Dock = DockStyle.Fill,
                DrawMode = DrawMode.OwnerDrawFixed,
                ItemHeight = 18,
                BorderStyle = BorderStyle.None,
                BackColor = Back,
                ForeColor = Ink,
                Font = _mono,
                IntegralHeight = false,
                SelectionMode = SelectionMode.MultiExtended,
                HorizontalScrollbar = true,
            };
            _list.DrawItem += DrawLine;
            _now = new Label
            {
                Dock = DockStyle.Bottom,
                Height = 24,
                BackColor = Bar,
                ForeColor = Muted,
                Font = _mono,
                TextAlign = ContentAlignment.MiddleLeft,
                Padding = new Padding(8, 0, 0, 0),
                Text = "idle",
            };
            Controls.Add(_list);
            Controls.Add(_now);
            _sink = line => WindowThread.Later(this, () => Append(line));
            Load += (s, e) =>
            {
                _log.Written += _sink;
                _list.BeginUpdate();
                foreach (var line in _log.Recent()) _list.Items.Add(line);
                _list.EndUpdate();
                _list.TopIndex = Math.Max(0, _list.Items.Count - 1);
                _tick.Start();
            };
            _tick.Tick += (s, e) => ShowRunning();
            FormClosed += (s, e) =>
            {
                _log.Written -= _sink;
                _tick.Dispose();
            };
        }

        void Append(string line)
        {
            var visible = Math.Max(1, _list.ClientSize.Height / _list.ItemHeight);
            var following = _list.TopIndex + visible >= _list.Items.Count;
            _list.Items.Add(line);
            while (_list.Items.Count > MaxRows) _list.Items.RemoveAt(0);
            if (following) _list.TopIndex = Math.Max(0, _list.Items.Count - visible);
        }

        void ShowRunning()
        {
            var running = _router.Running().Where(run => run.Value >= ShownAfterMs).ToList();
            _now.ForeColor = running.Count == 0 ? Muted : Accent;
            _now.Text = running.Count == 0 ? "idle"
                : "running: " + string.Join(", ", running.Select(run => run.Key + " " + run.Value / 1000 + " s"));
        }

        void DrawLine(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            var selected = (e.State & DrawItemState.Selected) != 0;
            using (var fill = new SolidBrush(selected ? Bar : Back))
                e.Graphics.FillRectangle(fill, e.Bounds);
            var line = (string)_list.Items[e.Index];
            // "yyyy-MM-dd HH:mm:ss.fff text": the time in faint, the text by kind.
            var time = line.Length > 24 ? line.Substring(11, 12) : "";
            var text = line.Length > 24 ? line.Substring(24) : line;
            TextRenderer.DrawText(e.Graphics, time, _mono, new Point(e.Bounds.X + 6, e.Bounds.Y + 1), Faint, TextFormatFlags.NoPadding);
            TextRenderer.DrawText(e.Graphics, text, _mono, new Point(e.Bounds.X + 110, e.Bounds.Y + 1), Tone(text), TextFormatFlags.NoPadding);
        }

        // What kind of line it is, by the agent log's own wording.
        static Color Tone(string text)
        {
            if (text.StartsWith("agent ", StringComparison.Ordinal))
                return Regex.IsMatch(text, @" ok( \d+\.\d s)?$") ? Ink : Bad;
            if (text.StartsWith("widget:", StringComparison.Ordinal)) return Accent;
            if (text.StartsWith("====", StringComparison.Ordinal)) return Warn;
            if (text.StartsWith("handler ", StringComparison.Ordinal) || text.Contains(" failed")) return Bad;
            return Muted;
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == Keys.Escape) { Close(); return true; }
            if (keyData == (Keys.Control | Keys.C) && _list.SelectedItems.Count > 0)
            {
                Clipboard.SetText(string.Join(Environment.NewLine, _list.SelectedItems.Cast<string>()));
                return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) _mono.Dispose();
            base.Dispose(disposing);
        }
    }
}
