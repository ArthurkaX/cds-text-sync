namespace Cts.Visu
{
    // Text and attribute values the visu writers put into XML, SVG and HTML.
    internal static class Markup
    {
        internal static string Escape(string text)
            => (text ?? "").Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
    }
}
