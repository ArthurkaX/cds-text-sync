using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Visu
{
    internal static partial class SketchLinter
    {
        internal const int Grid = 4;
        internal sealed class Finding
        {
            internal string Rule;
            internal string Severity;
            internal int Index;
            internal string Message;
            internal IDictionary<string, string> Fixes = new Dictionary<string, string>();
        }

        sealed class IndexedElement
        {
            internal Sketch.Element Element;
            internal int Index;
        }

        internal static IList<Finding> Find(Sketch sketch)
        {
            var findings = new List<Finding>();
            for (var index = 0; index < sketch.Elements.Count; index++)
            {
                var element = sketch.Elements[index];
                var p = element.Params;
                var x = Int(p, "x");
                var y = Int(p, "y");
                var width = Int(p, "width");
                var height = Int(p, "height");
                if (x < 0 || y < 0 || x + width > sketch.Width || y + height > sketch.Height)
                    findings.Add(new Finding { Rule = "bounds", Severity = "error", Index = index,
                                               Message = ShapeName(element) + " at (" + x + "," + y + ") " + width + "x" + height
                                                         + " extends outside the " + sketch.Width + "x" + sketch.Height + " canvas" });
                else
                {
                    var close = new List<string>();
                    if (x < 8) close.Add("left");
                    if (y < 8) close.Add("top");
                    if (sketch.Width - x - width < 8) close.Add("right");
                    if (sketch.Height - y - height < 8) close.Add("bottom");
                    if (close.Count > 0)
                        findings.Add(new Finding { Rule = "margin", Severity = "info", Index = index,
                                                   Message = ShapeName(element) + " sits within 8px of the " + string.Join("/", close) + " edge" });
                }
                var fixes = new Dictionary<string, string>();
                foreach (var name in new[] { "x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2", "data-width",
                                             "data-height" })
                {
                    var raw = (string)element.Source.Attribute(name);
                    if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var value))
                    {
                        if ((name == "rx" || name == "ry") && element.Source.Name.LocalName == "rect") continue;
                        if (name == "r" || name == "rx" || name == "ry")
                        {
                            var radius = Snap(value * 2) / 2.0;
                            if (radius != value) fixes[name] = ((int)radius).ToString(CultureInfo.InvariantCulture);
                            continue;
                        }
                        if (name == "y" && (element.Type == "label" || element.Type == "textfield"))
                        {
                            var baselineTop = Int(p, "y");
                            var delta = Snap(baselineTop) - baselineTop;
                            if (delta != 0) fixes[name] = ((int)(value + delta)).ToString(CultureInfo.InvariantCulture);
                            continue;
                        }
                        var snapped = Snap(value);
                        if (snapped != (int)value || (double)(int)value != value) fixes[name] = snapped.ToString(CultureInfo.InvariantCulture);
                    }
                }
                if (fixes.Count > 0)
                {
                    var detail
                        = string.Join(", ", fixes.OrderBy(pair => pair.Key, StringComparer.Ordinal)
                                                .Select(pair => pair.Key + "=" + (string)element.Source.Attribute(pair.Key) + "->" + pair.Value));
                    findings.Add(new Finding { Rule = "grid", Severity = "warn", Index = index,
                                               Message = ShapeName(element) + " is off the 4px grid (" + detail + ")", Fixes = fixes });
                }
                var explicitFont = (string)element.Source.Attribute("font-size");
                if (explicitFont != null && double.TryParse(explicitFont, NumberStyles.Float, CultureInfo.InvariantCulture, out var rawFontSize))
                {
                    var fontSize = (int)rawFontSize;
                    if (!new[] { 11, 12, 16, 22, 28 }.Contains(fontSize))
                    {
                        var target = new[] { 11, 12, 16, 22, 28 }.OrderBy(size => Math.Abs(size - fontSize)).ThenBy(size => size).First();
                        findings.Add(new Finding {
            Rule = "font-scale",
            Severity = "warn",
            Index = index,
            Message =
                "font-size " + fontSize + " is outside the type scale 11/12/16/22/28; use a class (.caption/.label/.h2/.h1/.value) or " + target,
            Fixes =
                new Dictionary<string, string> {
                  ["font-size"] = target.ToString(CultureInfo.InvariantCulture),
                },
          });
                    }
                }
                var anchor = (string)element.Source.Attribute("text-anchor");
                if (element.Type == "label" || element.Type == "textfield")
                {
                    if (anchor != null && anchor != "start" && anchor != "middle" && anchor != "end")
                        findings.Add(new Finding { Rule = "text-anchor", Severity = "warn", Index = index,
                                                   Message = "text-anchor=\"" + anchor
                                                             + "\" is not supported and was read as \"start\"; use start, middle or end" });
                    else if (anchor != null && anchor != "start" && element.Source.Attribute("data-width") == null)
                        findings.Add(new Finding { Rule = "text-anchor", Severity = "warn", Index = index,
                                                   Message = "text-anchor=\"" + anchor
                                                             + ("\" without data-width: the box is sized from an estimate of the text, so the "
                                                                + "alignment lands wherever that estimate falls") });
                }
                if (element.Type == "button" && (height < 32 || width < 48))
                    findings.Add(new Finding { Rule = "touch-size", Severity = "warn", Index = index,
                                               Message = "button is " + width + "x" + height + "; minimum comfortable size is 48x32" });
                if (element.Type == "lamp" && (height < 16 || width < 16))
                    findings.Add(new Finding { Rule = "touch-size", Severity = "info", Index = index,
                                               Message = "lamp is " + width + "x" + height + "; below 16px it reads as a dot" });
                if (element.Type == "textfield")
                {
                    var missing = new List<string>();
                    if (string.IsNullOrEmpty((string)element.Source.Attribute("data-width"))) missing.Add("data-width");
                    if (string.IsNullOrEmpty((string)element.Source.Attribute("data-height"))) missing.Add("data-height");
                    if (missing.Count > 0)
                        findings.Add(new Finding { Rule = "unsized-field", Severity = "warn", Index = index,
                                                   Message = element.Type + " has no " + string.Join(" or ", missing)
                                                             + ": the box is sized from the format string, not from the value it will show" });
                }
                if ((element.Type == "label" || element.Type == "textfield" || element.Type == "button" || element.Type == "rectangle")
                    && !string.IsNullOrEmpty(p["text"]))
                {
                    var size = ParseInt(p["font_size"], 12);
                    var needed = Sketch.TextWidth(p["text"], size);
                    if (width > 0 && needed > width)
                        findings.Add(new Finding { Rule = "text-overflow", Severity = "warn", Index = index,
                                                   Message = element.Type + " text \"" + p["text"] + "\" needs about " + needed + "px but the box is "
                                                             + width + "px" });
                }
                if (element.Type == "textfield" && string.IsNullOrWhiteSpace(p["text_var"]))
                    findings.Add(new Finding { Rule = "unbound-field", Severity = "warn", Index = index,
                                               Message = "textfield has no data-text-var; it will show static text only -- `cts visu bind --elem "
                                                         + index + " --text-var NAME`" });
                if (new[] { "label", "textfield", "button" }.Contains(element.Type) && string.IsNullOrWhiteSpace(p["text_var"]))
                {
                    var claim = AssertedState(p["text"]);
                    if (claim != null)
                        findings.Add(
                            new Finding { Rule = "static-state", Severity = "warn", Index = index,
                                          Message
                                          = element.Type + " reports \"" + claim
                                            + ("\" as static text: it is compiled into a Text ID and will read the same whether or not that is "
                                               + "true. Bind it with `cts visu bind --elem ")
                                            + index + " --text-var NAME` (textfield) or `--var NAME` (lamp)" });
                }
                if (element.Type == "lamp" && string.IsNullOrWhiteSpace(p["var"]))
                    findings.Add(new Finding { Rule = "unbound-lamp", Severity = "info", Index = index,
                                               Message = "lamp has no data-var; it will stay in its off state -- `cts visu bind --elem " + index
                                                         + " --var NAME`" });
                if (element.Type == "button" && string.IsNullOrWhiteSpace(p["text"]) && string.IsNullOrWhiteSpace(p["text_id"]))
                    findings.Add(
                        new Finding { Rule = "empty-button", Severity = "warn", Index = index, Message = "button has no caption; set data-text" });
                var hasConfiguredInputs = element.SpecParams.ContainsKey("configured_inputs");
                var hasInputActions = element.SpecParams.ContainsKey("input_actions");
                if (element.Type == "button" && string.IsNullOrWhiteSpace(p["tap_var"]) && !hasConfiguredInputs && !hasInputActions)
                    findings.Add(new Finding { Rule = "inert-button", Severity = "warn", Index = index,
                                               Message = "button does nothing when pressed; add data-cds-tap or data-cds-action" });
                var kind = ((string)element.Source.Attribute("data-cds-type") ?? "").Trim().ToLowerInvariant();
                if (kind.Length > 0)
                {
                    var wanted = kind == "textfield"                                                                                ? "text"
                                 : new[] { "button", "lamp", "image-switcher", "combobox", "alarm-banner", "frame" }.Contains(kind) ? "rect"
                                                                                                                                    : null;
                    if (wanted == null)
                        findings.Add(new Finding { Rule = "control-tag", Severity = "warn", Index = index,
                                                   Message = "unknown data-cds-type=\"" + kind + "\"; it will be ignored" });
                    else if (element.Source.Name.LocalName != wanted)
                        findings.Add(new Finding { Rule = "control-tag", Severity = "warn", Index = index,
                                                   Message = "data-cds-type=\"" + kind + "\" only works on <" + wanted + ">, not <"
                                                             + element.Source.Name.LocalName + ">" });
                }
                var classes = ((string)element.Source.Attribute("class") ?? "").Trim();
                if (classes.Length > 0 && new[] { "button", "textfield", "lamp" }.Contains(element.Type))
                    findings.Add(new Finding { Rule = "inert-class", Severity = "info", Index = index,
                                               Message = "class=\"" + classes + "\" has no effect on a " + element.Type
                                                         + "; it takes the native CODESYS control style" });
            }
            AddOverlaps(sketch, findings);
            AddEmptyPanels(sketch, findings);
            AddLonelyCards(sketch, findings);
            AddContainerPadding(sketch, findings);
            AddCrowding(sketch, findings);
            AddScaffoldFinding(sketch, findings);
            findings.Sort((left, right) =>
                          {
                              var severity = SeverityOrder(left.Severity).CompareTo(SeverityOrder(right.Severity));
                              if (severity != 0) return severity;
                              var index = left.Index.CompareTo(right.Index);
                              return index != 0 ? index : string.CompareOrdinal(left.Rule, right.Rule);
                          });
            return findings;
        }

        static void AddScaffoldFinding(Sketch sketch, IList<Finding> findings)
        {
            var texts = new[] { "Process", "Setpoints", "ACCEPT", "REJECT", "Line speed", "Reject threshold", "Running", "Fault", "Start", "Stop" };
            var variables = new[] { "VisuVars.rLineSpeed", "VisuVars.rRejectLimit", "VisuVars.xRunning",
                                    "VisuVars.xFault",     "VisuVars.xStart",       "VisuVars.xStop" };
            var kept = 0;
            var first = -1;
            for (var index = 0; index < sketch.Elements.Count; index++)
            {
                var p = sketch.Elements[index].Params;
                var hits = texts.Contains((p["text"] ?? "").Trim()) ? 1 : 0;
                if (variables.Contains((p["text_var"] ?? "").Trim()) || variables.Contains((p["var"] ?? "").Trim())) hits++;
                if (hits > 0 && first < 0) first = index;
                kept += hits;
            }
            if (kept >= 8)
                findings.Add(new Finding {
                    Rule = "scaffold", Severity = "info", Index = first < 0 ? 0 : first,
                    Message
                    = kept + " of the starter screen's placeholders are still here: replace the placeholder text and variable bindings with your own"
                });
        }

        static int SeverityOrder(string severity) => severity == "error" ? 0 : severity == "warn" ? 1 : severity == "info" ? 2 : 3;

        static string AssertedState(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return null;
            var parts = Regex.Split(text.Trim(), "=|:|\\s[-–—]\\s");
            if (parts.Length < 2) return null;
            if (string.IsNullOrWhiteSpace(parts[0]) || string.IsNullOrWhiteSpace(parts[parts.Length - 1])) return null;
            var tail = parts[parts.Length - 1].Trim().TrimEnd('.', ',', ';', '!');
            var states
                = new[] { "stopped",   "running",      "started", "starting", "stopping", "active",   "inactive", "idle",   "ready",     "fault",
                          "faulted",   "ok",           "error",   "alarm",    "alarming", "on",       "off",      "open",   "closed",    "opened",
                          "enabled",   "disabled",     "online",  "offline",  "normal",   "warning",  "manual",   "auto",   "automatic", "true",
                          "false",     "yes",          "no",      "empty",    "full",     "busy",     "done",     "failed", "passed",    "complete",
                          "connected", "disconnected", "present", "absent",   "armed",    "disarmed", "tripped",  "healthy" };
            return states.Contains(tail.Split((char[])null, StringSplitOptions.RemoveEmptyEntries).LastOrDefault(), StringComparer.OrdinalIgnoreCase)
                       ? tail
                       : null;
        }

        static int Int(Sketch.Element element, string key) => Int(element.Params, key);
        static int Int(IDictionary<string, string> values, string key) => ParseInt(values.TryGetValue(key, out var value) ? value : "0", 0);
        static int ParseInt(string value, int fallback) => int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number)
                                                               ? number
                                                               : fallback;
        static int Snap(double value) => (int)Math.Round(value / Grid, MidpointRounding.ToEven) * Grid;

        internal static IList<string> BuildLines(Sketch sketch, out bool hasErrors, out bool hasFindings)
        {
            var findings = Find(sketch);
            hasErrors = findings.Any(finding => finding.Severity == "error");
            hasFindings = findings.Count > 0;
            return findings.Select(finding => "[" + (finding.Severity == "error" ? "FAIL" : finding.Severity == "warn" ? "WARN" : "INFO")
                + "] " + finding.Rule.PadRight(13) + " #" + finding.Index.ToString().PadRight(3) + " " + finding.Message).ToList();
        }
    }
}
