using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace Cts.Agent
{
    // The GRAFCET drawing of one machine as an SVG file: the geometry the FSM
    // window draws (FsmGrafcet), on white for a document or a review, with
    // the machine's name above it.  Hovering a step or a transition in a
    // browser shows its line.
    internal static class FsmSvg
    {
        //: Room above the drawing for the caption.
        const int CaptionH = 30;
        //: Font sizes whose characters are no wider than the geometry's 7 pixels in a common monospace font.
        const int LabelSize = 12, GuardSize = 11, SmallSize = 10;
        const string Font = "Consolas, 'DejaVu Sans Mono', 'Courier New', monospace";
        const string Paper = "#ffffff", Ink = "#1f2328", Muted = "#6e7781", StepFill = "#f6f8fa", Divider = "#afb8c1";
        const string Line = "#57606a", Guard = "#0550ae", Priority = "#cf222e", ChipFill = "#ffebe9", Jump = "#bc4c00";
        static readonly Regex Unsafe = new Regex(@"[^A-Za-z0-9_.\-]+");

        // The file *machine* of the object *label* is drawn in, in *folder*;
        // *taken* holds the names already written by this run.
        internal static string Write(string folder, string label, IDictionary<string, object> machine, ISet<string> taken)
        {
            var selector = Convert.ToString(machine["selector"]);
            var stem = Unsafe.Replace(label + "." + selector, "_").Trim('_', '.');
            var name = stem + ".svg";
            for (var n = 2; !taken.Add(name); n++) name = stem + "-" + n + ".svg";
            Directory.CreateDirectory(folder);
            File.WriteAllText(Path.Combine(folder, name), Render(FsmMap.Read(machine), label + ": " + selector), new UTF8Encoding(false));
            return name;
        }

        internal static string Render(FsmMachine machine, string caption)
        {
            var layout = machine.Layout;
            var width = Math.Max(layout.Width, 24 + caption.Length * 9);
            var svg = new StringBuilder();
            svg.Append("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"").Append(width).Append("\" height=\"").Append(layout.Height + CaptionH)
                .Append("\" viewBox=\"0 0 ").Append(width).Append(' ').Append(layout.Height + CaptionH).Append("\" font-family=\"").Append(Font).Append("\">\n");
            svg.Append("<title>").Append(Escape(caption)).Append("</title>\n");
            svg.Append("<rect width=\"100%\" height=\"100%\" fill=\"").Append(Paper).Append("\"/>\n");
            Text(svg, caption, 14, Ink, 12, 20, "bold");
            svg.Append("<g transform=\"translate(0,").Append(CaptionH).Append(")\">\n");
            if (layout.AnyBox != null)
            {
                var box = layout.AnyBox;
                Rect(svg, box[0], box[1], box[2], box[3], ChipFill, Priority, 2, null);
                Centre(svg, "any", LabelSize, Priority, box[0], box[1], box[2], box[3]);
                Text(svg, "priority - written outside the CASE", SmallSize, Muted, box[0], box[1] - 6, null);
            }
            foreach (var chip in layout.Chips)
            {
                Rect(svg, chip.X, chip.Y, chip.W, chip.H, ChipFill, Priority, 1, "5 3");
                Cell(svg, chip, layout);
            }
            foreach (var step in layout.Steps)
            {
                var state = machine.States.FirstOrDefault(code => code.Title == step.FullLabel);
                svg.Append("<g><title>").Append(Escape(step.FullLabel + (state != null ? ", line " + state.Line : ""))).Append("</title>\n");
                Rect(svg, step.X, step.Y, step.W, step.H, StepFill, Ink, 1, null);
                if (step.Initial) Rect(svg, step.X + 3, step.Y + 3, step.W - 6, step.H - 6, "none", Ink, 1, null);
                Cell(svg, step, layout);
                if (step.Priority) Arrow(svg, step.X - 4, step.Y + step.H / 2, "right", Priority);
                if (step.Inbound.Count > 0) Text(svg, string.Join(", ", step.Inbound), SmallSize, Jump, step.InboundX, step.Y + step.H / 2 + 4, null);
                svg.Append("</g>\n");
            }
            foreach (var link in layout.Links) Link(svg, link, layout, link.Transition >= 0 && link.Transition < machine.Transitions.Count ? machine.Transitions[link.Transition] : null);
            svg.Append("</g>\n</svg>\n");
            return svg.ToString();
        }

        // The number cell and the label, as a step and a chip share them.
        static void Cell(StringBuilder svg, FsmStep box, FsmLayout layout)
        {
            var divider = box.X + layout.NumW;
            svg.Append("<line x1=\"").Append(divider).Append("\" y1=\"").Append(box.Y).Append("\" x2=\"").Append(divider).Append("\" y2=\"").Append(box.Y + box.H)
                .Append("\" stroke=\"").Append(Divider).Append("\"/>\n");
            Centre(svg, box.Number.ToString(CultureInfo.InvariantCulture), LabelSize, Ink, box.X, box.Y, layout.NumW, box.H);
            Text(svg, box.Label, LabelSize, Ink, divider + 10, box.Y + box.H / 2 + 4, null);
        }

        static void Link(StringBuilder svg, FsmLink link, FsmLayout layout, FsmCode transition)
        {
            var colour = link.Kind == "global" ? Priority : link.Kind == "jump" ? Jump : Line;
            svg.Append("<g>");
            if (transition != null)
                svg.Append("<title>").Append(Escape(transition.Title + (transition.Guard.Length > 0 ? " when " + StText.Squeezed(transition.Guard) : "") + ", line " + transition.Line)).Append("</title>");
            svg.Append('\n');
            if (link.Points.Count > 1)
                svg.Append("<polyline points=\"").Append(string.Join(" ", link.Points.Select(point => point[0] + "," + point[1])))
                    .Append("\" fill=\"none\" stroke=\"").Append(colour).Append("\" stroke-width=\"2\" stroke-linejoin=\"round\"/>\n");
            if (link.Bar != null)
            {
                var bar = link.Bar;
                var ends = bar.Way == "h" ? new[] { bar.X - layout.BarHalf, bar.Y, bar.X + layout.BarHalf, bar.Y } : new[] { bar.X, bar.Y - 9, bar.X, bar.Y + 9 };
                svg.Append("<line x1=\"").Append(ends[0]).Append("\" y1=\"").Append(ends[1]).Append("\" x2=\"").Append(ends[2]).Append("\" y2=\"").Append(ends[3])
                    .Append("\" stroke=\"").Append(colour).Append("\" stroke-width=\"3\"/>\n");
            }
            if (link.Arrow != null) Arrow(svg, link.Arrow.X, link.Arrow.Y, link.Arrow.Way, colour);
            if (link.GuardAt != null) Text(svg, link.GuardText, GuardSize, Guard, link.GuardAt[0], link.GuardAt[1] + 11, null);
            if (link.NoteAt != null && !string.IsNullOrEmpty(link.NoteText)) Text(svg, link.NoteText, GuardSize, Jump, link.NoteAt[0], link.NoteAt[1] + 11, null);
            svg.Append("</g>\n");
        }

        static void Rect(StringBuilder svg, int x, int y, int w, int h, string fill, string stroke, int width, string dash)
        {
            svg.Append("<rect x=\"").Append(x).Append("\" y=\"").Append(y).Append("\" width=\"").Append(w).Append("\" height=\"").Append(h)
                .Append("\" fill=\"").Append(fill).Append("\" stroke=\"").Append(stroke).Append("\" stroke-width=\"").Append(width).Append('"');
            if (dash != null) svg.Append(" stroke-dasharray=\"").Append(dash).Append('"');
            svg.Append("/>\n");
        }

        static void Arrow(StringBuilder svg, int x, int y, string way, string colour)
        {
            svg.Append("<polygon points=\"").Append(string.Join(" ", FsmMap.Arrowhead(x, y, way).Select(point => point[0] + "," + point[1])))
                .Append("\" fill=\"").Append(colour).Append("\"/>\n");
        }

        // *text* with its baseline at *y*.
        static void Text(StringBuilder svg, string text, int size, string colour, int x, int y, string weight)
        {
            svg.Append("<text x=\"").Append(x).Append("\" y=\"").Append(y).Append("\" font-size=\"").Append(size).Append("\" fill=\"").Append(colour).Append('"');
            if (weight != null) svg.Append(" font-weight=\"").Append(weight).Append('"');
            svg.Append(" xml:space=\"preserve\">").Append(Escape(text)).Append("</text>\n");
        }

        static void Centre(StringBuilder svg, string text, int size, string colour, int x, int y, int w, int h)
        {
            svg.Append("<text x=\"").Append(x + w / 2).Append("\" y=\"").Append(y + h / 2 + size / 3).Append("\" font-size=\"").Append(size)
                .Append("\" fill=\"").Append(colour).Append("\" text-anchor=\"middle\">").Append(Escape(text)).Append("</text>\n");
        }

        static string Escape(string text)
        {
            var escaped = new StringBuilder();
            foreach (var c in text ?? "")
            {
                if (c == '&') escaped.Append("&amp;");
                else if (c == '<') escaped.Append("&lt;");
                else if (c == '>') escaped.Append("&gt;");
                else if (c == '"') escaped.Append("&quot;");
                else if (c < ' ' && c != '\t') escaped.Append(' ');
                else escaped.Append(c);
            }
            return escaped.ToString();
        }
    }
}
