using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Linq;
using System.Windows.Forms;
using static Cts.Agent.Palette;

namespace Cts.Agent
{
    internal sealed partial class FsmView
    {
        // The GRAFCET chart of one machine on a canvas: the wheel zooms at the
        // pointer, a drag (left or middle button) pans, a click without a drag
        // picks the step or the transition under it.
        sealed class Chart : Control
        {
            static readonly Color Paper = Color.FromArgb(24, 26, 30);
            static readonly Color StepFill = Color.FromArgb(44, 48, 56);
            static readonly Color Stroke = Color.FromArgb(200, 205, 212);
            static readonly Color Divider = Color.FromArgb(90, 96, 105);
            static readonly Color Link = Color.FromArgb(150, 160, 172);
            static readonly Color Guard = Color.FromArgb(110, 170, 255);
            static readonly Color Priority = Color.FromArgb(248, 113, 104);
            static readonly Color ChipFill = Color.FromArgb(60, 36, 38);
            static readonly Color Jump = Color.FromArgb(230, 160, 80);
            static readonly Color Chosen = Color.FromArgb(240, 200, 90);
            //: Pixels a press may move and still be a click.
            const int Slop = 4;
            const float MinScale = 0.1f;
            const float MaxScale = 4f;

            readonly Font _label = new Font("Consolas", 13f, GraphicsUnit.Pixel);
            readonly Font _guard = new Font("Consolas", 12f, GraphicsUnit.Pixel);
            readonly Font _small = new Font("Consolas", 11f, GraphicsUnit.Pixel);
            FsmStep _step;
            int _transition = -1;
            float _scale = 1f;
            //: Where the chart's (0, 0) falls on the control.
            PointF _origin;
            //: The user moved or zoomed: a resize keeps the view instead of fitting again.
            bool _moved;
            Point _press;
            PointF _pressOrigin;
            bool _pressing;
            bool _dragging;

            public event Action<FsmCode> Picked;
            public FsmMachine Machine { get; private set; }

            public Chart()
            {
                DoubleBuffered = true;
                BackColor = Paper;
                SetStyle(ControlStyles.Selectable, true);
            }

            public void Display(FsmMachine machine)
            {
                Machine = machine;
                _step = null;
                _transition = -1;
                Fit();
            }

            // The whole chart in view and centred, never larger than it is.
            public void Fit()
            {
                _moved = false;
                var layout = Machine?.Layout;
                if (layout == null || layout.Width == 0 || layout.Height == 0)
                {
                    Invalidate();
                    return;
                }
                var room = ClientSize;
                var fit = Math.Min((room.Width - 8) / (float)layout.Width, (room.Height - 8) / (float)layout.Height);
                _scale = Math.Max(MinScale, Math.Min(1f, fit));
                _origin = new PointF((room.Width - layout.Width * _scale) / 2, Math.Max(4, (room.Height - layout.Height * _scale) / 2));
                Invalidate();
            }

            public void ZoomAtCentre(float factor)
            {
                ZoomAt(new PointF(ClientSize.Width / 2f, ClientSize.Height / 2f), factor);
            }

            // The point under *at* stays where it is.
            void ZoomAt(PointF at, float factor)
            {
                var scale = Math.Max(MinScale, Math.Min(MaxScale, _scale * factor));
                var x = (at.X - _origin.X) / _scale;
                var y = (at.Y - _origin.Y) / _scale;
                _scale = scale;
                _origin = new PointF(at.X - x * scale, at.Y - y * scale);
                _moved = true;
                Invalidate();
            }

            protected override void OnResize(EventArgs e)
            {
                base.OnResize(e);
                if (!_moved) Fit();
            }

            protected override void OnMouseWheel(MouseEventArgs e)
            {
                base.OnMouseWheel(e);
                ZoomAt(e.Location, e.Delta > 0 ? 1.15f : 1 / 1.15f);
                if (e is HandledMouseEventArgs handled) handled.Handled = true;
            }

            protected override void OnMouseDown(MouseEventArgs e)
            {
                base.OnMouseDown(e);
                Focus();
                if (e.Button != MouseButtons.Left && e.Button != MouseButtons.Middle) return;
                _pressing = true;
                _dragging = e.Button == MouseButtons.Middle;
                _press = e.Location;
                _pressOrigin = _origin;
                Capture = true;
            }

            protected override void OnMouseMove(MouseEventArgs e)
            {
                base.OnMouseMove(e);
                if (!_pressing)
                {
                    Cursor = Hit(e.Location) ? Cursors.Hand : Cursors.Default;
                    return;
                }
                var dx = e.X - _press.X;
                var dy = e.Y - _press.Y;
                if (!_dragging && Math.Abs(dx) <= Slop && Math.Abs(dy) <= Slop) return;
                _dragging = true;
                Cursor = Cursors.SizeAll;
                _origin = new PointF(_pressOrigin.X + dx, _pressOrigin.Y + dy);
                _moved = true;
                Invalidate();
            }

            protected override void OnMouseUp(MouseEventArgs e)
            {
                base.OnMouseUp(e);
                if (!_pressing) return;
                _pressing = false;
                Capture = false;
                var dragged = _dragging;
                _dragging = false;
                Cursor = Hit(e.Location) ? Cursors.Hand : Cursors.Default;
                if (dragged || e.Button != MouseButtons.Left || Machine == null) return;
                Pick(e.Location);
            }

            // The chart point under a control point.
            Point ToChart(Point at)
            {
                return new Point((int)((at.X - _origin.X) / _scale), (int)((at.Y - _origin.Y) / _scale));
            }

            bool Hit(Point at)
            {
                if (Machine == null) return false;
                var point = ToChart(at);
                return FsmMap.StepAt(Machine.Layout, point.X, point.Y) != null
                    || FsmMap.TransitionAt(Machine.Layout, point.X, point.Y, 6) >= 0;
            }

            void Pick(Point at)
            {
                var point = ToChart(at);
                var layout = Machine.Layout;
                _step = FsmMap.StepAt(layout, point.X, point.Y);
                _transition = _step == null ? FsmMap.TransitionAt(layout, point.X, point.Y, 6) : -1;
                Invalidate();
                if (_step != null) Picked?.Invoke(Machine.States.FirstOrDefault(state => state.Title == _step.FullLabel));
                else Picked?.Invoke(_transition >= 0 && _transition < Machine.Transitions.Count ? Machine.Transitions[_transition] : null);
            }

            protected override void OnPaint(PaintEventArgs e)
            {
                base.OnPaint(e);
                var layout = Machine?.Layout;
                if (layout == null) return;
                var g = e.Graphics;
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
                g.TranslateTransform(_origin.X, _origin.Y);
                g.ScaleTransform(_scale, _scale);
                if (layout.AnyBox != null) DrawAny(g, layout.AnyBox);
                foreach (var chip in layout.Chips) DrawChip(g, chip, layout);
                foreach (var step in layout.Steps) DrawStep(g, step, layout);
                foreach (var link in layout.Links.Where(link => link.Transition != _transition)) DrawLink(g, link, layout, false);
                foreach (var link in layout.Links.Where(link => link.Transition == _transition && _transition >= 0)) DrawLink(g, link, layout, true);
            }

            void DrawAny(Graphics g, int[] box)
            {
                using (var fill = new SolidBrush(ChipFill)) g.FillRectangle(fill, box[0], box[1], box[2], box[3]);
                using (var pen = new Pen(Priority, 2)) g.DrawRectangle(pen, box[0], box[1], box[2], box[3]);
                Centre(g, "any", _label, Priority, box[0], box[1], box[2], box[3]);
                Write(g, "priority - written outside the CASE", _small, Muted, box[0], box[1] - 18);
            }

            void DrawChip(Graphics g, FsmStep chip, FsmLayout layout)
            {
                using (var fill = new SolidBrush(ChipFill)) g.FillRectangle(fill, chip.X, chip.Y, chip.W, chip.H);
                using (var pen = new Pen(Priority, 1) { DashPattern = new[] { 5f, 3f } }) g.DrawRectangle(pen, chip.X, chip.Y, chip.W, chip.H);
                Cell(g, chip, layout);
            }

            void DrawStep(Graphics g, FsmStep step, FsmLayout layout)
            {
                var picked = step == _step;
                using (var fill = new SolidBrush(StepFill)) g.FillRectangle(fill, step.X, step.Y, step.W, step.H);
                using (var pen = new Pen(picked ? Chosen : Stroke, picked ? 2 : 1))
                {
                    g.DrawRectangle(pen, step.X, step.Y, step.W, step.H);
                    if (step.Initial) g.DrawRectangle(pen, step.X + 3, step.Y + 3, step.W - 6, step.H - 6);
                }
                Cell(g, step, layout);
                if (step.Priority) Arrow(g, step.X - 4, step.Y + step.H / 2, "right", Priority);
                if (step.Inbound.Count > 0)
                    Write(g, string.Join(", ", step.Inbound), _small, Jump, step.InboundX, step.Y + (step.H - layout.TextH) / 2);
            }

            // The number cell and the label, as a step and a chip share them.
            void Cell(Graphics g, FsmStep box, FsmLayout layout)
            {
                var divider = box.X + layout.NumW;
                using (var pen = new Pen(Divider, 1)) g.DrawLine(pen, divider, box.Y, divider, box.Y + box.H);
                Centre(g, box.Number.ToString(), _label, Ink, box.X, box.Y, layout.NumW, box.H);
                Write(g, box.Label, _label, Ink, divider + 10, box.Y + (box.H - layout.TextH) / 2);
            }

            void DrawLink(Graphics g, FsmLink link, FsmLayout layout, bool picked)
            {
                var colour = picked ? Chosen : link.Kind == "global" ? Priority : link.Kind == "jump" ? Jump : Link;
                if (link.Points.Count > 1)
                    using (var pen = new Pen(colour, picked ? 3 : 2))
                        g.DrawLines(pen, link.Points.Select(point => new Point(point[0], point[1])).ToArray());
                if (link.Bar != null)
                    using (var pen = new Pen(colour, 3))
                    {
                        if (link.Bar.Way == "h") g.DrawLine(pen, link.Bar.X - layout.BarHalf, link.Bar.Y, link.Bar.X + layout.BarHalf, link.Bar.Y);
                        else g.DrawLine(pen, link.Bar.X, link.Bar.Y - 9, link.Bar.X, link.Bar.Y + 9);
                    }
                if (link.Arrow != null) Arrow(g, link.Arrow.X, link.Arrow.Y, link.Arrow.Way, colour);
                if (link.GuardAt != null) Write(g, link.GuardText, _guard, picked ? Chosen : Guard, link.GuardAt[0], link.GuardAt[1]);
                if (link.NoteAt != null && !string.IsNullOrEmpty(link.NoteText)) Write(g, link.NoteText, _guard, Jump, link.NoteAt[0], link.NoteAt[1]);
            }

            static void Arrow(Graphics g, int x, int y, string way, Color colour)
            {
                using (var fill = new SolidBrush(colour))
                    g.FillPolygon(fill, FsmMap.Arrowhead(x, y, way).Select(point => new Point(point[0], point[1])).ToArray());
            }

            static void Write(Graphics g, string text, Font font, Color colour, int x, int y)
            {
                using (var brush = new SolidBrush(colour)) g.DrawString(text ?? "", font, brush, x, y);
            }

            static void Centre(Graphics g, string text, Font font, Color colour, int x, int y, int w, int h)
            {
                using (var brush = new SolidBrush(colour))
                using (var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                    g.DrawString(text, font, brush, new RectangleF(x, y, w, h), format);
            }

            protected override void Dispose(bool disposing)
            {
                if (disposing)
                {
                    _label.Dispose();
                    _guard.Dispose();
                    _small.Dispose();
                }
                base.Dispose(disposing);
            }
        }
    }
}
