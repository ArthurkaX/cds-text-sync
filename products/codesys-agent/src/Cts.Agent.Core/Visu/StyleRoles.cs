using System;
using System.Collections.Generic;

namespace Cts.Visu
{
    internal static class StyleRoles
    {
        internal static string NormalizeScheme(string value)
        {
            var normalized = (value ?? "light").Trim().ToLowerInvariant();
            return normalized == "dark" ? "dark" : "light";
        }

        internal sealed class Role
        {
            internal string Name { get; set; }
            internal string[] Anchors { get; set; }
            internal string Light { get; set; }
        }

        internal static readonly Role[] Definitions = {
            RoleOf("screen", "#F4F5F7"),
            RoleOf("surface", "#F5F5F5", "Element-Background-Color"),
            RoleOf("screen.background", "#F5F5F5", "Element-Background-Color"),
            RoleOf("screen.surface", "#FFFFFF", "BasicElement-Fill-Color"),
            RoleOf("panel", "#FFFFFF", "BasicElement-Fill-Color"),
            RoleOf("card", "#EDEFF2", "BasicElement-Fill-Color"),
            RoleOf("fill", "#FFFFFF", "BasicElement-Fill-Color"),
            RoleOf("custom.fill", "#FFFFFF", "BasicElement-Fill-Color"),
            RoleOf("frame", "#000000", "BasicElement-Frame-Color"),
            RoleOf("custom.frame", "#D5D9DF", "BasicElement-Frame-Color"),
            RoleOf("panel.frame", "#D5D9DF", "BasicElement-Frame-Color"),
            RoleOf("border", "#000000", "BasicElement-Frame-Color"),
            RoleOf("divider", "#D5D9DF", "BasicElement-Frame-Color"),
            RoleOf("text", "#1F1F1F", "Font-Default-Color"),
            RoleOf("on.surface", "#1F1F1F", "Font-Default-Color"),
            RoleOf("custom.text", "#1F1F1F", "Font-Default-Color"),
            RoleOf("panel.header.text", "#1F1F1F", "Font-Default-Color"),
            RoleOf("text.bright", "#FFFFFF", "Font-Default-BrightColor"),
            RoleOf("text.muted", "#666666", "Element-Control-Color", "Element-Meter-LabelFontColor"),
            RoleOf("panel.header", "#EAEAEA", "Element-Background-Color"),
            RoleOf("field.fill", "#FFFFFF", "Element-Fill-Color"),
            RoleOf("field.frame", "#BEBEBE", "Element-Frame-Color"),
            RoleOf("field.text", "#1F1F1F", "Font-Default-Color"),
            RoleOf("accent", "#007ACC", "Element-Control-HighlightColor", "Dialog-HeaderColor"),
            RoleOf("primary", "#007ACC", "Element-Control-HighlightColor", "Dialog-HeaderColor"),
            RoleOf("element.active", "#007ACC", "Element-Control-HighlightColor", "Dialog-HeaderColor"),
            RoleOf("focus", "#007ACC", "Element-Control-HighlightColor", "Dialog-HeaderColor"),
            RoleOf("secondary", "#6A6A6A", "Element-Frame-Color"),
            RoleOf("button.fill", "#007ACC", "Element-Control-HighlightColor", "Dialog-HeaderColor"),
            RoleOf("button.text", "#FFFFFF", "Element-Button-FontColor"),
            RoleOf("success", "#3F9142", "Element-Control-Color_Green"),
            RoleOf("warning", "#C8860D", "Element-Control-Color_Yellow"),
            RoleOf("error", "#C0392B", "Element-Alarm-Frame-Color", "BasicElement-Alarm-Frame-Color"),
            RoleOf("alarm.fill", "#C0392B", "BasicElement-Alarm-Fill-Color"),
            RoleOf("alarm.frame", "#8E2B20", "BasicElement-Alarm-Frame-Color"),
            RoleOf("muted", "#7A7A7A", "Element-Frame-Color"),
            RoleOf("hover", "#E9F3FF"),
            RoleOf("disabled", "#A6A6A6"),
            RoleOf("water", "#2E7FB8"),
            RoleOf("water.dim", "#1B5B87"),
            RoleOf("metal", "#9AA3AD"),
        };

        internal static readonly IDictionary<string, string> Dark = new Dictionary<string, string>(StringComparer.Ordinal) {
            ["screen"] = "#10141A",
            ["surface"] = "#171C24",
            ["screen.background"] = "#10141A",
            ["screen.surface"] = "#171C24",
            ["panel"] = "#171C24",
            ["card"] = "#1E242D",
            ["fill"] = "#171C24",
            ["custom.fill"] = "#171C24",
            ["frame"] = "#2A3038",
            ["custom.frame"] = "#2A3038",
            ["panel.frame"] = "#2A3038",
            ["border"] = "#2A3038",
            ["divider"] = "#2A3038",
            ["text"] = "#E6E9ED",
            ["on.surface"] = "#E6E9ED",
            ["custom.text"] = "#E6E9ED",
            ["panel.header.text"] = "#E6E9ED",
            ["text.bright"] = "#FFFFFF",
            ["text.muted"] = "#9AA6B2",
            ["panel.header"] = "#1E242D",
            ["field.fill"] = "#0E1218",
            ["field.frame"] = "#39424E",
            ["field.text"] = "#E6E9ED",
            ["button.fill"] = "#232A35",
            ["button.text"] = "#E6E9ED",
            ["accent"] = "#4DA3FF",
            ["primary"] = "#4DA3FF",
            ["element.active"] = "#4DA3FF",
            ["focus"] = "#4DA3FF",
            ["secondary"] = "#6E7681",
            ["success"] = "#4CAF50",
            ["warning"] = "#E0A030",
            ["error"] = "#E05A4A",
            ["alarm.fill"] = "#B03A2E",
            ["alarm.frame"] = "#E05A4A",
            ["muted"] = "#9AA6B2",
            ["hover"] = "#24303D",
            ["disabled"] = "#4A525C",
            ["water"] = "#3C93D4",
            ["water.dim"] = "#1B5B87",
            ["metal"] = "#6E7681",
        };

        internal static readonly ISet<string> Curated = new HashSet<string>(
            StringComparer.Ordinal) { "screen",  "panel", "card",       "divider",     "panel.frame", "custom.fill", "custom.frame", "success",
                                      "warning", "error", "alarm.fill", "alarm.frame", "water",       "water.dim",   "metal" };

        internal static IDictionary<string, string> Palette(string scheme)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var role in Definitions)
            {
                values[role.Name] = scheme == "dark" && Dark.ContainsKey(role.Name) ? Dark[role.Name] : role.Light;
            }
            if (scheme == "dark")
            {
                foreach (var role in Dark)
                    values[role.Key] = role.Value;
            }
            return values;
        }

        static Role RoleOf(string name, string fallback, params string[] anchors)
        {
            return new Role { Name = name, Light = fallback, Anchors = anchors };
        }
    }
}
