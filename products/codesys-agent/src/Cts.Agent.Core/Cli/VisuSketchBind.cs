using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Visu;

namespace Cts.Cli
{
    internal static partial class VisuSketchCommands
    {
        static IDictionary<string, object> Bind(string path, string source, Sketch sketch, CliOptions options)
        {
            var index = options.Number("elem", -1);
            if (index < 0 || index >= sketch.Elements.Count)
                throw new CliFailure("visu bind", "element out of range",
                                     "--elem " + index + " out of range: sketch has " + sketch.Elements.Count + " element(s)", null, 1);
            var element = sketch.Elements[index];
            var type = element.Type;
            var changes = new List<string>();
            var tags = SketchEditor.SourceTags(source);
            if (tags.Count != sketch.Elements.Count)
                throw new CliFailure("visu bind", "invalid SVG", "internal: sketch element count does not match its source tags", null, 1);
            var tag = tags[index];
            var edited = tag.Value;
            if (Has(options, "clear"))
            {
                foreach (var name in Attributes)
                    edited = SketchEditor.RemoveAttribute(edited, name);
                changes.Add("cleared all bindings");
            }
            else
            {
                SetBinding(options, "var", "data-var", type, new[] { "lamp", "combobox", "image-switcher" }, ref edited, changes);
                SetBinding(options, "color", "data-color", type, new[] { "lamp" }, ref edited, changes);
                SetBinding(options, "text_var", "data-text-var", type, new[] { "textfield", "rectangle" }, ref edited, changes);
                SetBinding(options, "color_var", "data-color-var", type, new[] { "rectangle" }, ref edited, changes);
                SetBinding(options, "tap", "data-cds-tap", type, new[] { "button" }, ref edited, changes, "tap:");
                SetBinding(options, "toggle", "data-cds-tap", type, new[] { "button" }, ref edited, changes, "toggle:");
                var action = options.Text("action");
                if (action != null)
                {
                    CheckType("action", type, new[] { "button", "rectangle" });
                    var existing = SketchEditor.ReadAttribute(edited, "data-cds-action");
                    var merged = string.IsNullOrEmpty(existing) ? action : existing + " || " + action;
                    edited = SketchEditor.SetAttribute(edited, "data-cds-action", merged);
                    changes.Add("data-cds-action=" + merged);
                }
            }
            if (changes.Count == 0) throw new CliFailure("visu bind", "nothing to do", "nothing to do: pass a binding option or --clear", null, 1);
            source = source.Substring(0, tag.Index) + edited + source.Substring(tag.Index + tag.Length);
            try
            {
                Sketch.Parse(source);
            }
            catch (Exception error)
            {
                throw new CliFailure("visu bind", "invalid edit", "edit produced invalid SVG: " + error.Message, null, 1);
            }
            File.WriteAllText(path, source, new System.Text.UTF8Encoding(false));
            return new Dictionary<string, object> { ["path"] = path, ["index"] = index, ["type"] = type, ["changes"] = changes };
        }
        static void SetBinding(CliOptions options, string key, string attribute, string type, string[] allowed, ref string tag, IList<string> changes,
                               string prefix = "")
        {
            var value = options.Text(key);
            if (value == null) return;
            CheckType(key.Replace('_', '-'), type, allowed);
            tag = SketchEditor.SetAttribute(tag, attribute, prefix + value);
            changes.Add(attribute + "=" + prefix + value);
        }
        static void CheckType(string flag, string type, string[] allowed)
        {
            if (!allowed.Contains(type, StringComparer.Ordinal))
                throw new CliFailure("visu bind", "binding type mismatch",
                                     "--" + flag + " applies to " + string.Join("/", allowed) + " element(s), not '" + type + "'", null, 1);
        }
    }
}
