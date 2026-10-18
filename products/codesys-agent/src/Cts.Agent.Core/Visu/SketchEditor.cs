using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Visu
{
    internal static class SketchEditor
    {
        static readonly Regex StartTag = new Regex("<(?:rect|circle|ellipse|line|text)\\b[^>]*?/?>", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex Definitions = new Regex("<defs\\b.*?</defs\\s*>", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex Comments = new Regex("<!--.*?-->", RegexOptions.Singleline);

        internal static IList<Match> SourceTags(string source)
        {
            var masked = Definitions.Replace(source, match => new string(' ', match.Length));
            masked = Comments.Replace(masked, match => new string(' ', match.Length));
            return StartTag.Matches(masked).Cast<Match>().ToList();
        }

        static Regex AttributePattern(string name) => new Regex("\\s+" + Regex.Escape(name) + "\\s*=\\s*(?<q>[\"'])(?<value>(?:(?!\\k<q>).)*)\\k<q>",
                                                                RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1));

        internal static string RemoveAttribute(string tag, string name) => AttributePattern(name).Replace(tag, "");

        internal static string ReadAttribute(string tag, string name)
        {
            var match = AttributePattern(name).Match(tag);
            if (!match.Success) return "";
            return match.Groups["value"].Value.Replace("&lt;", "<").Replace("&gt;", ">").Replace("&quot;", "\"")
                       .Replace("&apos;", "'").Replace("&amp;", "&");
        }

        internal static string SetAttribute(string tag, string name, string value)
        {
            var regex = AttributePattern(name);
            if (regex.IsMatch(tag)) return regex.Replace(tag, match =>
            {
                var quote = match.Groups["q"].Value;
                return match.Value.Substring(0, match.Groups["value"].Index - match.Index) + Escape(value, quote) + quote;
            }, 1);
            var close = tag.EndsWith("/>", StringComparison.Ordinal) ? tag.Length - 2 : tag.Length - 1;
            return tag.Insert(close, " " + name + "=\"" + Escape(value, "\"") + "\"");
        }

        static string Escape(string value, string quote) =>
            value.Replace("&", "&amp;").Replace("<", "&lt;").Replace(quote, quote == "\"" ? "&quot;" : "&apos;");
    }
}
