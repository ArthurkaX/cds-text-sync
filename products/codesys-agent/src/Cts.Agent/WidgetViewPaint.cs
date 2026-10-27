using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    // The window drawn by hand: header, rows, footer and the Report link.
    internal sealed partial class WidgetView
    {
        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
            PaintHeader(g);
            for (var i = 0; i < _items.Count; i++) PaintRow(g, _items[i], HeaderHeight + i * RowHeight, i == _selected);
            PaintFooter(g);
            using (var pen = new Pen(Edge))
            using (var path = Rounded(new Rectangle(0, 0, Width - 1, Height - 1), Radius))
                g.DrawPath(pen, path);
        }

        void PaintHeader(Graphics g)
        {
            PaintBranchMark(g, new Point(Side + 1, 15));
            TextRenderer.DrawText(g, _branch, _title, new Point(Side + 22, 12), Ink, TextFormatFlags.NoPadding);
            var branchWidth = TextRenderer.MeasureText(_branch ?? "", _title, Size.Empty, TextFormatFlags.NoPadding).Width;
            var state = TextRenderer.MeasureText(_state, _small, Size.Empty, TextFormatFlags.NoPadding);
            var stateColor = _tone == WidgetTone.InSync ? Good : _tone == WidgetTone.Both ? Warn : _tone == WidgetTone.Changed ? Ink : Faint;
            TextRenderer.DrawText(g, _state, _small, new Point(Width0 - Side - state.Width, 40), stateColor, TextFormatFlags.NoPadding);
            TextRenderer.DrawText(g, _place, _small, new Rectangle(Side, 38, Width0 - 2 * Side - Math.Max(90, state.Width + 16), 18), Muted,
                TextFormatFlags.NoPadding | TextFormatFlags.PathEllipsis);
            // The connection, as a pill at the right.
            var label = _online ? "online" : "offline";
            var size = TextRenderer.MeasureText(label, _small, Size.Empty, TextFormatFlags.NoPadding);
            var pill = new Rectangle(Width0 - Side - size.Width - 26, 14, size.Width + 26, 22);
            var tone = _online ? Good : Muted;
            using (var fill = new SolidBrush(Color.FromArgb(40, tone)))
            using (var path = Rounded(pill, 11))
                g.FillPath(fill, path);
            using (var dot = new SolidBrush(tone))
                g.FillEllipse(dot, pill.X + 9, pill.Y + 8, 7, 7);
            TextRenderer.DrawText(g, label, _small, new Point(pill.X + 20, pill.Y + 4), tone, TextFormatFlags.NoPadding);
            var commitAt = Side + 22 + branchWidth + 10;
            if (_commit != null && pill.X - 10 > commitAt)
                TextRenderer.DrawText(g, _commit, _small, new Rectangle(commitAt, 17, pill.X - 10 - commitAt, 18), Muted,
                    TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis);
            using (var pen = new Pen(Rule))
                g.DrawLine(pen, 0, HeaderHeight - 1, Width0, HeaderHeight - 1);
        }

        // A git branch, drawn: a trunk, a side branch joining it, three commits.
        static void PaintBranchMark(Graphics g, Point at)
        {
            using (var pen = new Pen(Accent, 1.8f))
            using (var fill = new SolidBrush(Back))
            {
                g.DrawLine(pen, at.X + 4, at.Y + 3, at.X + 4, at.Y + 17);
                g.DrawBezier(pen, at.X + 13, at.Y + 7, at.X + 13, at.Y + 12, at.X + 4, at.Y + 10, at.X + 4, at.Y + 15);
                foreach (var dot in new[] { new Point(at.X + 4, at.Y + 3), new Point(at.X + 4, at.Y + 17), new Point(at.X + 13, at.Y + 5) })
                {
                    g.FillEllipse(fill, dot.X - 3, dot.Y - 3, 6, 6);
                    g.DrawEllipse(pen, dot.X - 3, dot.Y - 3, 6, 6);
                }
            }
        }

        void PaintRow(Graphics g, WidgetItem item, int top, bool selected)
        {
            var blocked = Blocked(item);
            var enabled = blocked == null;
            if (selected)
            {
                using (var fill = new SolidBrush(Hover))
                using (var path = Rounded(new Rectangle(6, top + 3, Width0 - 12, RowHeight - 6), 8))
                    g.FillPath(fill, path);
                using (var bar = new SolidBrush(enabled ? Accent : Warn))
                    g.FillRectangle(bar, 6, top + 12, 3, RowHeight - 24);
            }
            var badge = new Rectangle(Side + 2, top + 9, 26, 26);
            using (var fill = new SolidBrush(selected && enabled ? Accent : Badge))
            using (var path = Rounded(badge, 6))
                g.FillPath(fill, path);
            TextRenderer.DrawText(g, item.Key == '\0' ? "·" : item.Key.ToString(), _key, badge, enabled ? Ink : Faint,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            // A permission at the right: a green check while its key is
            // allowed, a red cross while it is blocked (grey when another
            // entry blocks it).
            var right = Width0 - Side;
            if (item.Toggles != null)
            {
                var box = new Rectangle(right - 18, top + 13, 18, 18);
                using (var fill = new SolidBrush(!item.Current ? Good : enabled ? Bad : Faint))
                using (var path = Rounded(box, 4))
                    g.FillPath(fill, path);
                using (var pen = new Pen(Ink, 2f))
                {
                    if (item.Current)
                    {
                        g.DrawLine(pen, box.X + 5, box.Y + 5, box.X + 13, box.Y + 13);
                        g.DrawLine(pen, box.X + 13, box.Y + 5, box.X + 5, box.Y + 13);
                    }
                    else g.DrawLines(pen, new[] { new Point(box.X + 4, box.Y + 9), new Point(box.X + 8, box.Y + 13), new Point(box.X + 14, box.Y + 5) });
                }
                right = box.X - 10;
            }
            var hint = item.Disabled == null && blocked != null ? "wait" : item.Hint;
            var color = item.Toggles == null && item.Current ? Accent : enabled ? Muted : Warn;
            // The hint takes what the label leaves, the label at least two fifths of the row;
            // a longer hint is cut with an ellipsis.
            var room = right - (Side + 42);
            var label = Math.Min(TextRenderer.MeasureText(item.Label, _body, Size.Empty, TextFormatFlags.NoPadding).Width, room * 2 / 5);
            var width = Math.Min(TextRenderer.MeasureText(hint, _mono, Size.Empty, TextFormatFlags.NoPadding).Width, room - label - 12);
            TextRenderer.DrawText(g, hint, _mono, new Rectangle(right - width, top + 15, width, 20), color, TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis);
            // The label stops short of the hint, cut with an ellipsis.
            TextRenderer.DrawText(g, item.Label, _body, new Rectangle(Side + 42, top + 11, Math.Max(40, room - width - 12), 22),
                enabled || item.Current ? Ink : Faint, TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis);
        }

        // How tall the footer text may grow: FooterLines lines, and no lower
        // than the screen's working area allows below the rows.
        int FooterRoom()
        {
            var line = TextRenderer.MeasureText("X", _mono, Size.Empty, TextFormatFlags.NoPadding).Height;
            var area = Screen.FromControl(this).WorkingArea;
            var below = area.Bottom - Math.Max(area.Top, Top) - HeaderHeight - _items.Count * RowHeight - 24 - 16 - (_asking != null ? AnswerHeight : 0);
            return Math.Max(2 * line, Math.Min(FooterLines * line, below));
        }

        // The wheel and PgUp/PgDn scroll a footer longer than it shows.
        void ScrollFooter(int pixels)
        {
            var scroll = Math.Max(0, Math.Min(_footerScroll + pixels, _footerText - _footerShown));
            if (scroll == _footerScroll) return;
            _footerScroll = scroll;
            Invalidate(FooterRect());
        }

        protected override void OnMouseWheel(MouseEventArgs e)
        {
            var line = TextRenderer.MeasureText("X", _mono, Size.Empty, TextFormatFlags.NoPadding).Height;
            ScrollFooter(-e.Delta / 120 * 3 * line);
        }

        void PaintFooter(Graphics g)
        {
            var area = FooterRect();
            using (var pen = new Pen(Rule))
                g.DrawLine(pen, 0, area.Top, Width0, area.Top);
            var mark = new Rectangle(Side, area.Top + 14, 16, 16);
            var clock = 0;
            if (Running)
            {
                var angle = (int)(_clock.ElapsedMilliseconds * 360 / 900 % 360);
                using (var pen = new Pen(Accent, 2.2f))
                    g.DrawArc(pen, mark, angle, 270);
                double? share;
                var seconds = WidgetMenu.Elapsed(_clock.ElapsedMilliseconds, _last, out share);
                var size = TextRenderer.MeasureText(seconds, _mono, Size.Empty, TextFormatFlags.NoPadding);
                TextRenderer.DrawText(g, seconds, _mono, new Point(Width0 - Side - size.Width, area.Top + 15), Muted, TextFormatFlags.NoPadding);
                clock = ClockWidth();
                // The rule above the footer fills as the run nears the last one's time.
                if (share.HasValue)
                    using (var fill = new SolidBrush(Accent))
                        g.FillRectangle(fill, 0, area.Top - 1, (int)(Width0 * share.Value), 3);
            }
            else if (_ok.HasValue)
            {
                using (var fill = new SolidBrush(_ok.Value ? Good : Bad))
                    g.FillEllipse(fill, mark);
                TextRenderer.DrawText(g, _ok.Value ? "✓" : "✕", _small, mark, Back,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            }
            if (CopyShown) PaintCopy(g);
            var left = _ok.HasValue || Running ? Side + 28 : Side;
            var shown = new Rectangle(left, area.Top + 15, Width0 - left - Side - Math.Max(clock, Reserved()), _footerShown);
            g.SetClip(shown);
            TextRenderer.DrawText(g, _footer, _mono, new Rectangle(shown.Left, shown.Top - _footerScroll, shown.Width, _footerText),
                _footerColor, TextFormatFlags.WordBreak | TextFormatFlags.NoPadding);
            g.ResetClip();
            // A footer longer than it shows has a thin bar at the right: where the part shown sits in the whole.
            if (_footerText > _footerShown)
                using (var thumb = new SolidBrush(Faint))
                    g.FillRectangle(thumb, Width0 - 7, shown.Top + _footerScroll * _footerShown / _footerText, 3, Math.Max(12, _footerShown * _footerShown / _footerText));
            if (_asking == null) return;
            using (var fill = new SolidBrush(Badge))
            using (var pen = new Pen(Accent))
            using (var path = Rounded(AnswerRect(), 6))
            {
                g.FillPath(fill, path);
                g.DrawPath(pen, path);
            }
            if (_asking.Picks == null) return;
            var browse = BrowseRect();
            using (var pen = new Pen(Faint))
                g.DrawLine(pen, browse.Left, browse.Top + 6, browse.Left, browse.Bottom - 6);
            var hot = browse.Contains(_mouse);
            TextRenderer.DrawText(g, "...", _mono, browse, hot ? Accent : Muted,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }

        // The Report link: a pill, Accent under the mouse.
        void PaintCopy(Graphics g)
        {
            var link = CopyRect();
            var hot = link.Contains(_mouse);
            using (var pen = new Pen(hot ? Accent : Edge))
            using (var path = Rounded(link, 6))
                g.DrawPath(pen, path);
            TextRenderer.DrawText(g, "Report", _small, link, hot ? Accent : Muted,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }

        // The room the seconds take at the footer's right while a run goes:
        // the widest they read, so the text beside them wraps the same way
        // as it was measured.
        int ClockWidth()
        {
            return TextRenderer.MeasureText("000 s of ~000 s", _mono, Size.Empty, TextFormatFlags.NoPadding).Width + 12;
        }

        static GraphicsPath Rounded(Rectangle box, int radius)
        {
            var d = radius * 2;
            var path = new GraphicsPath();
            path.AddArc(box.X, box.Y, d, d, 180, 90);
            path.AddArc(box.Right - d, box.Y, d, d, 270, 90);
            path.AddArc(box.Right - d, box.Bottom - d, d, d, 0, 90);
            path.AddArc(box.X, box.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }
}
