#if DEBUG
// The steps of `widget.drive`, the Debug build's pipe method that works the
// quick window as a person would, for tests of the window itself:
//
//   "open" "close"            Alt+Q on a closed window / closing it
//   "1" .. "9", "0", "+"      a key typed on the window (the row with that key)
//   "enter" "esc" "left" "right" "up" "down" "space" "backspace" "f4"
//   "pgup" "pgdn" "ctrl+c"    those keys
//   "type:TEXT"               TEXT typed into the line a row asks for
//   "copy"                    a click on the Report link of a failure
//   "wait:MS"                 MS milliseconds
//   "idle"                    until no run goes and the window stays the same
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Agent
{
    public enum DriveKind { Open, Close, Char, Key, Type, Copy, Wait, Idle }

    public sealed class DriveStep
    {
        public DriveKind Kind { get; set; }
        //: The key's name for Key, the character for Char, the text for Type.
        public string Text { get; set; }
        public int Milliseconds { get; set; }
    }

    public static class WidgetDrive
    {
        static readonly string[] Keys = { "enter", "esc", "left", "right", "up", "down", "space", "backspace", "f4", "pgup", "pgdn", "ctrl+c" };

        public static List<DriveStep> Parse(IEnumerable<object> steps)
        {
            if (steps == null) throw new ArgumentException("steps: a list of strings is required");
            return steps.Select(step => Step(Convert.ToString(step, CultureInfo.InvariantCulture) ?? "")).ToList();
        }

        static DriveStep Step(string step)
        {
            if (step.StartsWith("type:", StringComparison.Ordinal)) return new DriveStep { Kind = DriveKind.Type, Text = step.Substring(5) };
            if (step.StartsWith("wait:", StringComparison.Ordinal))
            {
                if (!int.TryParse(step.Substring(5), NumberStyles.None, CultureInfo.InvariantCulture, out var ms))
                    throw new ArgumentException("wait:MS takes milliseconds: " + step);
                return new DriveStep { Kind = DriveKind.Wait, Milliseconds = ms };
            }
            var name = step.ToLowerInvariant();
            switch (name)
            {
                case "open": return new DriveStep { Kind = DriveKind.Open };
                case "close": return new DriveStep { Kind = DriveKind.Close };
                case "copy": return new DriveStep { Kind = DriveKind.Copy };
                case "idle": return new DriveStep { Kind = DriveKind.Idle };
            }
            if (Keys.Contains(name)) return new DriveStep { Kind = DriveKind.Key, Text = name };
            if (step.Length == 1 && !char.IsWhiteSpace(step[0])) return new DriveStep { Kind = DriveKind.Char, Text = step };
            throw new ArgumentException("unknown step " + step + ": open, close, a key (1, a, enter, esc, ...), type:TEXT, copy, wait:MS or idle");
        }
    }
}
#endif
