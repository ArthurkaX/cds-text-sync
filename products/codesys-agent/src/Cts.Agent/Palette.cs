// The dark palette the agent's windows share; a window's own accents stay
// in its file.
using System.Drawing;

namespace Cts.Agent
{
    internal static class Palette
    {
        internal static readonly Color Back = Color.FromArgb(30, 33, 38);
        internal static readonly Color Bar = Color.FromArgb(38, 42, 48);
        internal static readonly Color Ink = Color.FromArgb(230, 232, 235);
        internal static readonly Color Muted = Color.FromArgb(150, 160, 172);
        internal static readonly Color Faint = Color.FromArgb(96, 104, 114);
        internal static readonly Color Good = Color.FromArgb(63, 185, 80);
        internal static readonly Color Bad = Color.FromArgb(248, 81, 73);
    }
}
