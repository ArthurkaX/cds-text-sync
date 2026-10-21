// What the quick window's tool windows (format, FSM, analysis) share: the dark
// frame, the monospace font, the status line, cts run on their behalf and the
// way back to the window's thread when it answers.  Escape closes, F5 and
// opening read again.
using System;
using System.Drawing;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal abstract class ToolWindow : Form
    {
        //: Runs cts with these arguments; whole: the answer is stdout, else the verdict line.
        readonly Action<string[], bool, Action<bool, string>> _cts;
        protected readonly Font Mono = new Font("Consolas", 9.5f);
        protected readonly Label Status;

        protected ToolWindow(string title, Size size, Action<string[], bool, Action<bool, string>> cts)
        {
            _cts = cts;
            Text = title;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            KeyPreview = true;
            BackColor = Back;
            ForeColor = Ink;
            ClientSize = size;
            Status = new Label { Dock = DockStyle.Fill, ForeColor = Muted, Font = Mono, TextAlign = ContentAlignment.MiddleLeft, AutoEllipsis = true };
            Load += (s, e) => Reload();
            FormClosed += (s, e) => Mono.Dispose();
        }

        protected abstract void Reload();

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            switch (keyData)
            {
                case Keys.Escape: Close(); return true;
                case Keys.F5: Reload(); return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        //: Runs cts; done comes back on the window's thread, unless the window closed first.
        protected void RunCts(string[] args, bool whole, Action<bool, string> done)
        {
            _cts(args, whole, (ok, said) => Later(() => done(ok, said)));
        }

        protected void Later(Action action) => WindowThread.Later(this, action);

        protected void Say(string text, Color color)
        {
            Status.Text = text;
            Status.ForeColor = color;
        }

        protected TextBox FilterBox(DockStyle dock)
        {
            return new TextBox { Dock = dock, BackColor = Bar, ForeColor = Ink, BorderStyle = BorderStyle.FixedSingle, Font = Mono };
        }

        protected ListBox RowList(int rowHeight, DrawItemEventHandler draw)
        {
            var list = new ListBox
            {
                Dock = DockStyle.Fill,
                DrawMode = DrawMode.OwnerDrawFixed,
                ItemHeight = rowHeight,
                BorderStyle = BorderStyle.None,
                BackColor = Back,
                ForeColor = Ink,
                Font = Mono,
                IntegralHeight = false,
            };
            list.DrawItem += draw;
            return list;
        }

        // *inner* in a one-pixel frame of the rule colour, a few pixels from its neighbours.
        protected static Panel Framed(Control inner)
        {
            var frame = new Panel { Dock = DockStyle.Fill, Padding = new Padding(1), BackColor = Rule, Margin = new Padding(4) };
            inner.Dock = DockStyle.Fill;
            frame.Controls.Add(inner);
            return frame;
        }

        // The title strip above a pane.
        protected Label Caption(string text)
        {
            return new Label { Text = text, Dock = DockStyle.Fill, BackColor = Bar, ForeColor = Ink, Font = Mono, TextAlign = ContentAlignment.MiddleLeft,
                Margin = new Padding(4, 4, 4, 0), Padding = new Padding(6, 0, 0, 0) };
        }

        protected RichTextBox CodePane()
        {
            return new RichTextBox
            {
                Dock = DockStyle.Fill,
                ReadOnly = true,
                WordWrap = false,
                DetectUrls = false,
                BorderStyle = BorderStyle.None,
                BackColor = Well,
                ForeColor = Ink,
                Font = Mono,
                ScrollBars = RichTextBoxScrollBars.Both,
            };
        }

        protected Button FlatButton(string text, Action click)
        {
            var button = new Button { Text = text, AutoSize = true, FlatStyle = FlatStyle.Flat, BackColor = Bar, ForeColor = Ink };
            button.FlatAppearance.BorderColor = Muted;
            button.Click += (s, e) => click();
            return button;
        }
    }
}
