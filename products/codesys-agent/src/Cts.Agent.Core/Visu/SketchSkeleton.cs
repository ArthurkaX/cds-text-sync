using System;
using System.Collections.Generic;

namespace Cts.Visu
{
    internal static class SketchSkeleton
    {
        internal static IList<string> CheckCanvas(int width, int height)
        {
            var warnings = new List<string>();
            if (width < 480 || height < 320)
            {
                warnings.Add(
                    "Canvas " + width + "x" + height
                    + (" is below 480x320, the smallest size the layout blocks fit at -- expect the skeleton to overlap itself. Run `cts visu lint` "
                       + "and lay it out by hand."));
            }
            var offGrid = new List<string>();
            if (width % 4 != 0) offGrid.Add("--w");
            if (height % 4 != 0) offGrid.Add("--h");
            if (offGrid.Count > 0)
            {
                var joined = string.Join(" and ", offGrid);
                var isAre = offGrid.Count == 1 ? "is" : "are";
                var multiple = offGrid.Count == 1 ? "a multiple" : "multiples";
                warnings.Add(joined + " " + isAre + " not " + multiple
                             + (" of 4, so the halves the layout computes land off the 4px grid `cts visu lint` enforces. Run it with --fix, or "
                                + "round the canvas."));
            }
            return warnings;
        }
        internal static string Compose(int width, int height, string name, string scheme)
        {
            const int margin = 24;
            const int gutter = 16;
            const int pad = 16;
            const int ruleY = 72;
            const int actionHeight = 48;
            const int preferredSideWidth = 296;
            const int cardHeight = 56;
            const int fieldHeight = 32;
            const int lampSize = 20;
            const int preferredButtonWidth = 160;
            var title = string.IsNullOrWhiteSpace(name) ? "Screen title" : name;
            var contentWidth = width - margin * 2;
            var bodyY = ruleY + gutter;
            var actionY = Snap4(height - margin - actionHeight);
            var footerRuleY = actionY - gutter;
            var bodyHeight = footerRuleY - 8 - bodyY;
            var sideWidth = Math.Min(preferredSideWidth, Snap4(contentWidth / 2));
            var mainWidth = contentWidth - gutter - sideWidth;
            var sideX = margin + mainWidth + gutter;
            var lines = new List<string>();
            var schemeAttribute = scheme == "dark" ? " data-cds-scheme=\"dark\"" : "";
            lines.Add("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + width + "\" height=\"" + height + "\"" + schemeAttribute + ">");
            lines.Add("");
            lines.Add("  <!-- ============================================================");
            lines.Add("       HMI sketch. Edit this file, then, pointing each at this file:");
            lines.Add("         cts visu lint      check the design (and snap it with fix)");
            lines.Add("         cts visu preview   render a PNG next to it, and look at it");
            lines.Add("         cts visu from-svg  compile it into the CODESYS project");
            lines.Add("");
            lines.Add("       COLOURS: never write one. Put class=\"...\" on the element and");
            lines.Add("       the active CODESYS style picks the colour.");
            lines.Add("         surfaces  panel  card  divider");
            lines.Add("         type      h1 (22)  h2 (16)  value (28)  label (12)  caption (11)");
            lines.Add("         emphasis  muted  inverse");
            lines.Add("         status    ok  warn  alarm");
            lines.Add("         P&ID      pipe-water  metal");
            lines.Add("       Buttons, textfields and lamps take NO class: they inherit the");
            lines.Add("       native CODESYS control style.");
            if (schemeAttribute.Length > 0)
            {
                lines.Add("");
                lines.Add("       This screen is DARK (data-cds-scheme on the root element).");
                lines.Add("       Nothing else changes: the same classes resolve to the dark");
                lines.Add("       palette, so you still never write a colour. Lamps keep their");
                lines.Add("       indicator colours by design; an indicator that changed");
                lines.Add("       meaning with the scheme would be a safety problem.");
            }
            lines.Add("");
            lines.Add("       LAYOUT: 24px page margin, 16px between blocks, 16px panel");
            lines.Add("       padding, coordinates on a 4px grid. Keep to it and the screen");
            lines.Add("       stays aligned; lint knows how to snap what drifts.");
            lines.Add("       The background is painted for you, so never add a full-screen rect.");
            lines.Add("       ============================================================ -->");
            lines.Add("");
            lines.Add("  <!-- header: title, secondary caption, rule -->");
            lines.Add("  <text class=\"h1\" x=\"" + margin + "\" y=\"" + (margin + 22) + "\">" + Markup.Escape(title) + "</text>");
            var captionWidth = Math.Min(160, Snap4(contentWidth / 3));
            lines.Add("  <text class=\"caption\" x=\"" + (width - margin - captionWidth) + "\" y=\"40\" data-width=\"" + captionWidth
                      + "\" text-anchor=\"middle\">Line 1 / Shift A</text>");
            lines.Add("  <line class=\"divider\" x1=\"" + margin + "\" y1=\"" + ruleY + "\" x2=\"" + (width - margin) + "\" y2=\"" + ruleY + "\"/>");
            lines.Add("");
            lines.Add("  <!-- main panel: put the process graphic / trend / table here -->");
            lines.Add("  <rect class=\"panel\" x=\"" + margin + "\" y=\"" + bodyY + "\" width=\"" + mainWidth + "\" height=\"" + bodyHeight + "\"/>");
            lines.Add("  <text class=\"h2\" x=\"" + (margin + pad) + "\" y=\"" + (bodyY + pad + 16) + "\">Process</text>");
            var cardY = bodyY + bodyHeight - pad - cardHeight;
            var innerWidth = mainWidth - 2 * pad;
            var cardWidth = Snap4((innerWidth - gutter) / 2);
            var labels = new[] { "ACCEPT", "REJECT" };
            var statuses = new[] { "ok", "warn" };
            var kpiCount = KpiFits(margin + pad, cardWidth, labels[0]) ? 2 : 1;
            if (kpiCount == 1) cardWidth = innerWidth;
            lines.Add("  <!-- KPI cards: accent bar + label + live value -->");
            for (var index = 0; index < kpiCount; index++)
            {
                var cardX = margin + pad + index * (cardWidth + gutter);
                lines.Add("  <rect class=\"card\" x=\"" + cardX + "\" y=\"" + cardY + "\" width=\"" + cardWidth + "\" height=\"" + cardHeight
                          + "\" rx=\"4\"/>");
                lines.Add("  <rect class=\"" + statuses[index] + "\" x=\"" + cardX + "\" y=\"" + cardY + "\" width=\"8\" height=\"" + cardHeight
                          + "\"/>");
                lines.Add("  <text class=\"label\" x=\"" + (cardX + 24) + "\" y=\"" + (cardY + 24) + "\">" + labels[index] + "</text>");
                var valueBox = KpiValueBox(cardX, cardWidth, labels[index]);
                lines.Add("  <text class=\"value\" x=\"" + valueBox.Item1 + "\" y=\"" + (cardY + 28) + "\" data-width=\"" + valueBox.Item2
                          + "\" data-height=\"40\" text-anchor=\"middle\">0</text>");
            }
            lines.Add("");
            lines.Add("  <!-- side panel: setpoints and state -->");
            lines.Add("  <rect class=\"panel\" x=\"" + sideX + "\" y=\"" + bodyY + "\" width=\"" + sideWidth + "\" height=\"" + bodyHeight + "\"/>");
            lines.Add("  <text class=\"h2\" x=\"" + (sideX + pad) + "\" y=\"" + (bodyY + pad + 16) + "\">Setpoints</text>");
            var fields = new[] { Tuple.Create("Line speed", "VisuVars.rLineSpeed", "%3.1f m/min"),
                                 Tuple.Create("Reject threshold", "VisuVars.rRejectLimit", "%3.1f %%") };
            lines.Add("  <!-- textfield: data-width/data-height give it a box, the text content");
            lines.Add("       is the format string, data-text-var is what it displays.");
            lines.Add("       Its y is a BASELINE like any text, so the box top is y minus the");
            lines.Add("       font size. Leave 24px between a label baseline and its field. -->");
            for (var index = 0; index < fields.Length; index++)
            {
                var top = bodyY + 48 + index * 72;
                if (top + 24 + fieldHeight + pad > bodyY + bodyHeight) break;
                lines.Add("  <text class=\"label\" x=\"" + (sideX + pad) + "\" y=\"" + (top + 12) + "\">" + fields[index].Item1 + "</text>");
                lines.Add("  <text data-cds-type=\"textfield\" x=\"" + (sideX + pad) + "\" y=\"" + (top + 36) + "\" data-width=\""
                          + (sideWidth - 2 * pad) + "\" data-height=\"" + fieldHeight + "\"");
                lines.Add("        data-text-var=\"" + fields[index].Item2 + "\" font-size=\"12\">" + fields[index].Item3 + "</text>");
            }
            lines.Add("");
            var lampTop = bodyY + 192;
            if (lampTop + 32 + 2 * 32 <= bodyY + bodyHeight)
            {
                lines.Add("  <line class=\"divider\" x1=\"" + (sideX + pad) + "\" y1=\"" + lampTop + "\" x2=\"" + (sideX + sideWidth - pad)
                          + "\" y2=\"" + lampTop + "\"/>");
                lines.Add("  <!-- lamp: data-var drives it, data-color is the ON colour -->");
                var lampRows = new[] { Tuple.Create("green", "VisuVars.xRunning", "Running"), Tuple.Create("red", "VisuVars.xFault", "Fault") };
                for (var index = 0; index < lampRows.Length; index++)
                {
                    var lampY = lampTop + 16 + index * 32;
                    lines.Add("  <rect data-cds-type=\"lamp\" x=\"" + (sideX + pad) + "\" y=\"" + lampY + "\" width=\"" + lampSize + "\" height=\""
                              + lampSize + "\"");
                    lines.Add("        data-color=\"" + lampRows[index].Item1 + "\" data-var=\"" + lampRows[index].Item2 + "\"/>");
                    lines.Add("  <text class=\"label\" x=\"" + (sideX + pad + lampSize + 12) + "\" y=\"" + (lampY + 16) + "\">"
                              + lampRows[index].Item3 + "</text>");
                }
                lines.Add("");
            }
            lines.Add("  <!-- action row: buttons left, status banner right -->");
            lines.Add("  <line class=\"divider\" x1=\"" + margin + "\" y1=\"" + footerRuleY + "\" x2=\"" + (width - margin) + "\" y2=\"" + footerRuleY
                      + "\"/>");
            var buttonWidth = Math.Min(preferredButtonWidth, Snap4((mainWidth - gutter) / 2));
            var buttonLabels = new[] { "Start", "Stop" };
            var buttonVariables = new[] { "VisuVars.xStart", "VisuVars.xStop" };
            for (var index = 0; index < buttonLabels.Length; index++)
            {
                lines.Add("  <rect data-cds-type=\"button\" x=\"" + (margin + index * (buttonWidth + gutter)) + "\" y=\"" + actionY + "\" width=\""
                          + buttonWidth + "\" height=\"" + actionHeight + "\"");
                lines.Add("        data-text=\"" + buttonLabels[index] + "\" data-cds-tap=\"" + buttonVariables[index] + "\"/>");
            }
            lines.Add("  <rect class=\"alarm\" x=\"" + sideX + "\" y=\"" + actionY + "\" width=\"" + sideWidth + "\" height=\"" + actionHeight
                      + "\" rx=\"4\"/>");
            lines.Add("  <text class=\"inverse\" x=\"" + sideX + "\" y=\"" + (actionY + 24) + "\" data-width=\"" + sideWidth
                      + "\" data-height=\"16\" text-anchor=\"middle\">2 active alarms</text>");
            lines.Add("</svg>");
            return string.Join("\n", lines) + "\n";
        }
        static int Snap4(int value) => value / SketchLinter.Grid * SketchLinter.Grid;
        static int Snap4Up(int value) => (value + SketchLinter.Grid - 1) / SketchLinter.Grid * SketchLinter.Grid;
        static Tuple<int, int> KpiValueBox(int cardX, int cardWidth, string label)
        {
            var x = Snap4Up(cardX + 24 + Sketch.TextWidth(label, 12) + 16);
            return Tuple.Create(x, Snap4(cardX + cardWidth - 16 - x));
        }
        static bool KpiFits(int cardX, int cardWidth, string label) => KpiValueBox(cardX, cardWidth, label).Item2 >= 48;
    }
}
