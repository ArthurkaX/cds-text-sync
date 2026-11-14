using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace Cts.Visu
{
    // An element's data-cds-action, data-open-dialog and data-cds-input: its configured inputs and input actions.
    internal static partial class SvgSketch
    {
        static ElementSpec AddDialogActions(ElementSpec spec, XElement element)
        {
            var dialog = (string)element.Attribute("data-open-dialog");
            if (dialog == null) return spec;
            if (spec.Type != "button" && spec.Type != "rectangle")
            {
                throw new VisuException(
                    "data-open-dialog is only supported on a button or a simple rectangle/circle/ellipse element in this version");
            }
            var values = new Dictionary<string, object>(
                StringComparer.Ordinal) { ["dialog"] = dialog, ["modal"] = BooleanString((string)element.Attribute("data-dialog-modal"), true),
                                          ["centered"] = BooleanString((string)element.Attribute("data-dialog-centered"), true), ["position_x"] = "",
                                          ["position_y"] = "" };
            var parameters = AttributeMap(element, "data-dialog-param-");
            if (parameters.Count > 0) values["params"] = parameters;
            AddInputAction(spec, Action("OnMouseClick", "open_dialog", values));
            var snippet = (string)element.Attribute("data-dialog-st");
            if (!string.IsNullOrEmpty(snippet))
                AddInputAction(spec, Action("OnMouseClick", "st_snippet", new Dictionary<string, object> { ["snippet"] = snippet }));
            return spec;
        }

        // A click opens the IDE's Write Variable input on the variable the element shows, the form
        // most input fields of exported projects have.
        static ElementSpec AddWriteInput(ElementSpec spec, XElement element)
        {
            var input = (string)element.Attribute("data-cds-input");
            if (input == null) return spec;
            if (spec.Type != "textfield" && spec.Type != "rectangle")
                throw new VisuException("data-cds-input is only supported on a textfield or a plain rectangle/circle/ellipse");
            var word = input.Trim().ToLowerInvariant();
            if (!new[] { "numpad", "keypad", "edit", "default" }.Contains(word))
                throw new VisuException("data-cds-input=\"" + input + "\": use numpad, keypad, edit or default");
            if (!(spec.Params.TryGetValue("text_var", out var shown) && shown is string variable && variable.Length > 0))
                throw new VisuException("data-cds-input writes the variable the element shows: give it a data-text-var");
            AddInputAction(spec, Action("OnMouseClick", "write_variable", new Dictionary<string, object>(StringComparer.Ordinal)
            {
                ["input_type"] = word, ["min"] = (string)element.Attribute("data-input-min") ?? "",
                ["max"] = (string)element.Attribute("data-input-max") ?? "",
            }));
            return spec;
        }

        // Each Write Variable input's data-cds-input word as the IDE's InputType, from
        // *inputTypes* (VisuSettings.InputTypes of the screen's application): the InputTypes set.
        internal static List<string> ResolveInputTypes(IDictionary<string, object> parameters, IDictionary<string, string> inputTypes)
        {
            var resolved = new List<string>();
            if (!(parameters.TryGetValue("input_actions", out var raw) && raw is IList<object> actions)) return resolved;
            foreach (var action in actions.OfType<IDictionary<string, object>>().Where(action => Equals(action["type"], "write_variable")))
            {
                var values = (IDictionary<string, object>)action["values"];
                var word = (string)values["input_type"];
                if (!inputTypes.TryGetValue(word, out var inputType))
                    throw new VisuException("data-cds-input=\"" + word + "\" opens the " + word + " the application's Visualization Manager names, and no manager "
                        + "on disk names one: use data-cds-input=\"default\" (the manager's dialog for the variable's type), or add the manager in the IDE and cts sync");
                values["input_type"] = inputType;
                resolved.Add(inputType);
            }
            return resolved;
        }

        static void AddInputAction(ElementSpec spec, object action)
        {
            var actions = spec.Params.TryGetValue("input_actions", out var existing) ? existing as IList<object> : null;
            if (actions == null) actions = new List<object>();
            actions.Add(action);
            spec.Params["input_actions"] = actions;
        }

        static Tuple<IList<object>, IList<object>> ParseActions(string raw)
        {
            var configured = new List<object>();
            var inputActions = new List<object>();
            foreach (var part in (raw ?? "")
                         .Split(new[] { "||" }, StringSplitOptions.RemoveEmptyEntries)
                         .Select(item => item.Trim())
                         .Where(item => item.Length > 0))
            {
                var colon = part.IndexOf(':');
                if (colon > 0 && part.Substring(0, colon).Trim().ToLowerInvariant().StartsWith("on", StringComparison.Ordinal))
                {
                    inputActions.Add(ParseEventAction(part.Substring(0, colon).Trim(), part.Substring(colon + 1).Trim()));
                }
                else
                {
                    configured.Add(ParseComplexAction(part));
                }
            }
            return Tuple.Create((IList<object>)configured, (IList<object>)inputActions);
        }

        static object ParseComplexAction(string text)
        {
            var lower = text.ToLowerInvariant();
            if (lower.StartsWith("tap:", StringComparison.Ordinal) || lower.StartsWith("tap ", StringComparison.Ordinal))
            {
                return Action(null, "tap", new Dictionary<string, object> { ["variable"] = text.Substring(4).Trim() });
            }
            if (lower.StartsWith("toggle:", StringComparison.Ordinal) || lower.StartsWith("toggle ", StringComparison.Ordinal))
            {
                return Action(null, "toggle", new Dictionary<string, object> { ["variable"] = text.Substring(7).Trim(), ["toggle_on"] = "False" });
            }
            throw new VisuException("Unsupported data-cds-action complex action: " + text);
        }

        static object ParseEventAction(string eventName, string body)
        {
            var lower = body.ToLowerInvariant();
            if (lower.StartsWith("st ", StringComparison.Ordinal) || lower.StartsWith("st:", StringComparison.Ordinal))
            {
                return Action(eventName, "st_snippet", new Dictionary<string, object> { ["snippet"] = body.Substring(3).Trim() });
            }
            if (lower.StartsWith("toggle ", StringComparison.Ordinal) || lower.StartsWith("toggle:", StringComparison.Ordinal))
            {
                return Action(eventName, "toggle_variable", new Dictionary<string, object> { ["variable"] = body.Substring(7).Trim() });
            }
            if (lower.StartsWith("screen ", StringComparison.Ordinal) || lower.StartsWith("screen:", StringComparison.Ordinal))
            {
                return Action(eventName, "change_screen", new Dictionary<string, object> { ["screen"] = body.Substring(7).Trim() });
            }
            throw new VisuException("Unsupported data-cds-action event action: " + eventName + ": " + body);
        }

        static IDictionary<string, object> Action(string eventName, string type, IDictionary<string, object> values)
        {
            var action = new Dictionary<string, object>(StringComparer.Ordinal) { ["type"] = type, ["values"] = values };
            if (eventName != null) action["event"] = eventName;
            return action;
        }

        static Sketch.GradientSpec ParseGradient(XElement element, IDictionary<string, string> theme)
        {
            var fill = ((string)element.Attribute("fill") ?? "").Trim();
            var match = Regex.Match(fill, @"^url\(#([^)]+)\)$");
            if (!match.Success) return null;
            var definition = element.Document.Root.Descendants().FirstOrDefault(
                candidate => candidate.Attribute("id")?.Value == match.Groups[1].Value
                             && (candidate.Name.LocalName == "linearGradient" || candidate.Name.LocalName == "radialGradient"));
            if (definition == null) return null;
            var stops = definition.Elements()
                            .Where(candidate => candidate.Name.LocalName == "stop")
                            .Select(stop => new { Offset = Percent((string)stop.Attribute("offset"), 0),
                                                  Color = Resolve(ApplyOpacity((string)stop.Attribute("stop-color") ?? "#000000",
                                                                               (string)stop.Attribute("stop-opacity")),
                                                                  theme) })
                            .OrderBy(stop => stop.Offset)
                            .ToList();
            if (stops.Count == 0) return null;
            var radial = definition.Name.LocalName == "radialGradient";
            var angle = 0;
            if (!radial)
            {
                var x1 = Percent((string)definition.Attribute("x1"), 0);
                var y1 = Percent((string)definition.Attribute("y1"), 0);
                var x2 = Percent((string)definition.Attribute("x2"), 100);
                var y2 = Percent((string)definition.Attribute("y2"), 0);
                angle = ((int)Math.Round(Math.Atan2(y2 - y1, x2 - x1) * 180 / Math.PI) % 360 + 360) % 360;
            }
            return new Sketch.GradientSpec { Color1 = stops.First().Color,
                                             Color2 = stops.Last().Color,
                                             Angle = angle,
                                             CenterX = radial ? (int)Math.Round(Percent((string)definition.Attribute("cx"), 50)) : 50,
                                             CenterY = radial ? (int)Math.Round(Percent((string)definition.Attribute("cy"), 50)) : 50,
                                             Type = radial ? "radial"
                                                           : ((string)element.Attribute("data-cds-gradient-type") == "axial" ? "axial" : "linear") };
        }
    }
}
