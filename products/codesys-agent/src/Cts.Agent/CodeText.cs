// Structured Text shown coloured in a read-only RichTextBox of the dark
// windows (the format window, the FSM map), in the box's own font.
using System.Windows.Forms;

namespace Cts.Agent
{
    internal static class CodeText
    {
        static readonly StPalette Dark = new StPalette
        {
            Ink = 0xE6E8EB,
            Keyword = 0x569CD6,
            Type = 0x4EC9B0,
            Comment = 0x6A9955,
            Pragma = 0x9AA0A6,
            Text = 0xCE9178,
            Number = 0xB5CEA8,
        };

        internal static void Show(RichTextBox box, string text)
        {
            box.Rtf = StHighlight.Rtf(text, box.Font.Name, box.Font.SizeInPoints, Dark);
        }
    }
}
