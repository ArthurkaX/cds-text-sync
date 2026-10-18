using System;
using System.Collections.Generic;
using System.Linq;

// The key chord that opens the quick window: Alt+Q unless the user chose
// another, `quick_key` in their defaults.json (`cts config set quick_key
// Ctrl+Shift+Q`), the same in every project.  The spelling is cts's:
// modifiers Ctrl, Alt and Shift in that order, then a letter, a digit or
// F1-F12; a letter or a digit needs a modifier.  The chord matches exactly,
// so Ctrl+Alt+Q (AltGr+Q on many layouts) is not Alt+Q.
//
// Pure: the agent's keyboard hook asks Matches; the rules are unit tests.
namespace Cts.Agent
{
    public sealed class QuickKey
    {
        public const string DefaultText = "Alt+Q";

        static readonly string[] Modifiers = { "Ctrl", "Alt", "Shift" };

        //: The virtual-key code: 'A'-'Z', '0'-'9', or 0x70-0x7B for F1-F12.
        public int VirtualKey { get; private set; }
        public bool Ctrl { get; private set; }
        public bool Alt { get; private set; }
        public bool Shift { get; private set; }
        //: The chord as cts spells it, "Ctrl+Shift+Q".
        public string Text { get; private set; }

        public static readonly QuickKey Default = Parse(DefaultText);

        // The chord *text* names, or null when it is not one.
        public static QuickKey Parse(string text)
        {
            var parts = (text ?? "").Split('+').Select(part => part.Trim()).ToList();
            var key = parts[parts.Count - 1].ToUpperInvariant();
            var held = new HashSet<string>();
            foreach (var part in parts.Take(parts.Count - 1))
            {
                var name = Modifiers.FirstOrDefault(m => string.Equals(m, part, StringComparison.OrdinalIgnoreCase))
                    ?? (string.Equals(part, "Control", StringComparison.OrdinalIgnoreCase) ? "Ctrl" : null);
                if (name == null || !held.Add(name)) return null;
            }
            int vk, f;
            if (key.Length == 1 && (key[0] >= 'A' && key[0] <= 'Z' || key[0] >= '0' && key[0] <= '9'))
            {
                if (held.Count == 0) return null;
                vk = key[0];
            }
            else if (key.Length > 1 && key[0] == 'F' && int.TryParse(key.Substring(1), out f) && f >= 1 && f <= 12
                && key.Substring(1) == f.ToString(System.Globalization.CultureInfo.InvariantCulture))
                vk = 0x70 + f - 1;
            else
                return null;
            return new QuickKey
            {
                VirtualKey = vk,
                Ctrl = held.Contains("Ctrl"),
                Alt = held.Contains("Alt"),
                Shift = held.Contains("Shift"),
                Text = string.Join("+", Modifiers.Where(held.Contains).Concat(new[] { key })),
            };
        }

        // The chord a defaults.json (*json*, its text) names: its quick_key,
        // or Alt+Q when the file, the key or its value is not usable.
        public static QuickKey FromDefaults(string json)
        {
            object data;
            try { data = Json.Parse(json ?? ""); }
            catch (JsonException) { return Default; }
            var settings = data as IDictionary<string, object>;
            var text = settings != null && settings.ContainsKey("quick_key") ? settings["quick_key"] as string : null;
            return Parse(text) ?? Default;
        }

        // Is *vk* pressed with exactly these modifiers this chord?
        public bool Matches(int vk, bool ctrl, bool alt, bool shift)
        {
            return vk == VirtualKey && ctrl == Ctrl && alt == Alt && shift == Shift;
        }
    }
}
