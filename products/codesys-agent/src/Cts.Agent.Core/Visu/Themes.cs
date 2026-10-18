using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;

namespace Cts.Visu
{
    internal static class Themes
    {
        static readonly IDictionary<string, IDictionary<string, string>> Presets = CreatePresets();

        internal static IDictionary<string, string> Palette(string scheme, string name)
        {
            var colors = StyleRoles.Palette(scheme);
            colors["background"] = colors["screen"];
            colors["field.fill"] = scheme == "dark" ? "#0E1218" : "#FFFFFF";
            if (string.IsNullOrWhiteSpace(name)) return colors;
            var normalized = Normalize(name);
            var jsonColors = ReadJsonColors(normalized);
            if (jsonColors != null)
            {
                MergeResolved(colors, jsonColors, scheme);
                return colors;
            }
            if (Presets.TryGetValue(normalized, out var preset))
            {
                MergeResolved(colors, preset, scheme);
                return colors;
            }
            throw new VisuException("unknown theme '" + name + "'");
        }

        static void MergeResolved(IDictionary<string, string> target, IDictionary<string, string> source, string scheme)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var item in source)
            {
                var key = item.Key.Replace('-', '.');
                if (scheme == "dark" && StyleRoles.Dark.ContainsKey(key)) continue;
                if (scheme == "light" && StyleRoles.Curated.Contains(key)) continue;
                values[key] = item.Value;
            }
            Complete(values);
            foreach (var item in values)
                target[item.Key] = item.Value;
            foreach (var role in StyleRoles.Palette(scheme))
            {
                if (StyleRoles.Curated.Contains(role.Key) || scheme == "dark" && StyleRoles.Dark.ContainsKey(role.Key))
                {
                    target[role.Key] = role.Value;
                }
                else if (!target.ContainsKey(role.Key))
                {
                    target[role.Key] = role.Value;
                }
            }
            foreach (var item in target.ToList())
            {
                if (item.Key.Contains("-")) target[item.Key.Replace('-', '.')] = item.Value;
            }
        }

        static IDictionary<string, string> ReadJsonColors(string name)
        {
            var names = new[] { name, name.Replace("-", "-") };
            foreach (var candidate in names)
            {
                using (var stream = typeof(Themes).GetTypeInfo().Assembly.GetManifestResourceStream("Cts.Visu.Themes." + candidate + ".json"))
                {
                    if (stream == null) continue;
                    using (var reader = new StreamReader(stream))
                    {
                        var json = reader.ReadToEnd();
                        var colorsBlock = Regex.Match(json, @"""colors""\s*:\s*\{([^}]*)\}");
                        if (!colorsBlock.Success) throw new VisuException("Theme '" + name + "' has no style.colors");
                        var colors = new Dictionary<string, string>(StringComparer.Ordinal);
                        foreach (Match match in Regex.Matches(colorsBlock.Groups[1].Value, @"""([^""]+)""\s*:\s*""(#[0-9A-Fa-f]{6,8})"""))
                        {
                            colors[match.Groups[1].Value] = match.Groups[2].Value;
                        }
                        if (colors.Count == 0) throw new VisuException("Theme '" + name + "' has no style.colors");
                        return colors;
                    }
                }
            }
            return null;
        }

        static string Normalize(string name)
        {
            var text = Regex.Replace((name ?? "").Trim().ToLowerInvariant().Replace("<", "").Replace(">", ""), @"[^0-9a-z]+", "-").Trim('-');
            var aliases = new Dictionary<string, string>(StringComparer.Ordinal) { ["flat"] = "flat-style",
                                                                                   ["flat-style-4-9-0-0"] = "flat-style",
                                                                                   ["basic"] = "basic-style",
                                                                                   ["basic-style-4-9-0-0"] = "basic-style",
                                                                                   ["default-4-9-0-0"] = "default",
                                                                                   ["example"] = "example-for-a-style",
                                                                                   ["example-style"] = "example-for-a-style",
                                                                                   ["white"] = "white-style",
                                                                                   ["white-style-4-9-0-0"] = "white-style",
                                                                                   ["style-3"] = "style-3-gradient-linear-1",
                                                                                   ["gradient-linear-1"] = "style-3-gradient-linear-1",
                                                                                   ["style-4"] = "style-4-gradient-linear-2",
                                                                                   ["gradient-linear-2"] = "style-4-gradient-linear-2",
                                                                                   ["style-5"] = "style-5-gradient-axial-1",
                                                                                   ["gradient-axial-1"] = "style-5-gradient-axial-1",
                                                                                   ["style-6"] = "style-6-gradient-axial-2",
                                                                                   ["gradient-axial-2"] = "style-6-gradient-axial-2",
                                                                                   ["style-7"] = "style-7-gradient-double-linear-1",
                                                                                   ["gradient-double-linear-1"] = "style-7-gradient-double-linear-1",
                                                                                   ["style-8"] = "style-8-gradient-double-linear-2",
                                                                                   ["gradient-double-linear-2"] = "style-8-gradient-double-linear-2",
                                                                                   ["light"] = "white-style",
                                                                                   ["dark"] = "flat-style",
                                                                                   ["hi-contrast"] = "style-2" };
            foreach (var alias in aliases.OrderByDescending(item => item.Key.Length))
            {
                if (text == alias.Key || text.StartsWith(alias.Key + "-", StringComparison.Ordinal)) return alias.Value;
            }
            foreach (var preset in Presets.Keys.OrderByDescending(key => key.Length))
            {
                if (text == preset || text.StartsWith(preset + "-", StringComparison.Ordinal)) return preset;
            }
            return text;
        }

        static void Complete(IDictionary<string, string> colors)
        {
            var fallbacks
                = new Dictionary<string, string[]>(StringComparer.Ordinal) { ["screen.background"] = new[] { "background", "surface" },
                                                                             ["screen.surface"] = new[] { "surface", "background" },
                                                                             ["surface"] = new[] { "screen.surface", "background" },
                                                                             ["background"] = new[] { "screen.background", "surface" },
                                                                             ["panel"] = new[] { "panel.header", "surface", "background" },
                                                                             ["panel.frame"] = new[] { "border", "frame" },
                                                                             ["panel.header"] = new[] { "panel", "surface" },
                                                                             ["panel.header.text"] = new[] { "text", "on-surface" },
                                                                             ["divider"] = new[] { "border", "frame" },
                                                                             ["on-surface"] = new[] { "text" },
                                                                             ["text.muted"] = new[] { "muted", "text" },
                                                                             ["custom.fill"] = new[] { "panel", "surface" },
                                                                             ["custom.frame"] = new[] { "frame", "border" },
                                                                             ["custom.text"] = new[] { "text", "on-surface" },
                                                                             ["custom.accent.fill"] = new[] { "accent", "primary", "element.active" },
                                                                             ["custom.accent.text"] = new[] { "on-surface", "text" },
                                                                             ["field.text"] = new[] { "text", "on-surface" },
                                                                             ["button.fill"] = new[] { "primary", "accent", "element.active" },
                                                                             ["focus"] = new[] { "element.active", "accent", "primary" },
                                                                             ["primary"] = new[] { "accent", "element.active" },
                                                                             ["accent"] = new[] { "primary", "element.active" } };
            var changed = true;
            while (changed)
            {
                changed = false;
                foreach (var pair in fallbacks)
                {
                    if (colors.ContainsKey(pair.Key)) continue;
                    foreach (var fallback in pair.Value)
                    {
                        if (!colors.TryGetValue(fallback, out var value)) continue;
                        colors[pair.Key] = value;
                        changed = true;
                        break;
                    }
                }
            }
        }

        static IDictionary<string, IDictionary<string, string>> CreatePresets()
        {
            var styles = new Dictionary<string, IDictionary<string, string>>(StringComparer.Ordinal);
            styles["flat-style"] = Colors("background", "#F2F2F2", "surface", "#FFFFFF", "border", "#C7C7C7", "frame", "#7F7F7F", "primary",
                                          "#007ACC", "accent", "#007ACC", "element.active", "#007ACC");
            styles["basic-style"] = Colors("background", "#DCDCDC", "surface", "#ECECEC", "border", "#8A8A8A", "frame", "#606060", "primary",
                                           "#005A9E", "accent", "#005A9E", "hover", "#D6E8F7", "element.active", "#005A9E");
            styles["default"] = Colors();
            styles["example-for-a-style"] = Colors("primary", "#2E75B6", "accent", "#70AD47", "secondary", "#5B9BD5", "element.active", "#70AD47");
            styles["white-style"] = Colors("background", "#FFFFFF", "surface", "#FFFFFF", "panel", "#FFFFFF", "border", "#D9D9D9", "frame", "#A6A6A6",
                                           "hover", "#F5F5F5");
            styles["style-2"]
                = Colors("background", "#E7E7E7", "surface", "#F2F2F2", "primary", "#336699", "accent", "#336699", "element.active", "#336699");
            styles["style-3-gradient-linear-1"]
                = Colors("background", "#E8EEF5", "surface", "#F7FAFD", "primary", "#2F75B5", "accent", "#5B9BD5", "element.active", "#5B9BD5");
            styles["style-4-gradient-linear-2"]
                = Colors("background", "#ECECEC", "surface", "#FAFAFA", "primary", "#767171", "accent", "#A5A5A5", "element.active", "#767171");
            styles["style-5-gradient-axial-1"]
                = Colors("background", "#E9F0E5", "surface", "#F8FBF6", "primary", "#548235", "accent", "#70AD47", "element.active", "#70AD47");
            styles["style-6-gradient-axial-2"]
                = Colors("background", "#F5EDE7", "surface", "#FFF8F3", "primary", "#A65E2E", "accent", "#C55A11", "element.active", "#C55A11");
            styles["style-7-gradient-double-linear-1"]
                = Colors("background", "#EAEAF3", "surface", "#F7F7FC", "primary", "#5F5FA8", "accent", "#7F7FC5", "element.active", "#7F7FC5");
            styles["style-8-gradient-double-linear-2"]
                = Colors("background", "#E8F2F2", "surface", "#F6FCFC", "primary", "#2F7F7F", "accent", "#4BA3A3", "element.active", "#4BA3A3");
            return styles;
        }

        static IDictionary<string, string> Colors(params string[] pairs)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal) { ["background"] = "#F5F5F5",
                                                                                  ["surface"] = "#FFFFFF",
                                                                                  ["screen.background"] = "#F5F5F5",
                                                                                  ["screen.surface"] = "#FFFFFF",
                                                                                  ["panel.header"] = "#EAEAEA",
                                                                                  ["panel.header.text"] = "#1F1F1F",
                                                                                  ["border"] = "#B8B8B8",
                                                                                  ["frame"] = "#808080",
                                                                                  ["text"] = "#1F1F1F",
                                                                                  ["text.muted"] = "#666666",
                                                                                  ["on-surface"] = "#1F1F1F",
                                                                                  ["custom.fill"] = "#FFFFFF",
                                                                                  ["custom.frame"] = "#808080",
                                                                                  ["custom.text"] = "#1F1F1F",
                                                                                  ["custom.accent.fill"] = "#007ACC",
                                                                                  ["custom.accent.text"] = "#FFFFFF",
                                                                                  ["element.active"] = "#007ACC",
                                                                                  ["focus"] = "#007ACC",
                                                                                  ["primary"] = "#007ACC",
                                                                                  ["secondary"] = "#6A6A6A",
                                                                                  ["accent"] = "#007ACC",
                                                                                  ["muted"] = "#7A7A7A",
                                                                                  ["hover"] = "#E9F3FF",
                                                                                  ["disabled"] = "#A6A6A6" };
            for (var index = 0; index + 1 < pairs.Length; index += 2)
                values[pairs[index]] = pairs[index + 1];
            Complete(values);
            return values;
        }
    }
}
