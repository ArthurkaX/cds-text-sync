using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A ';' alone on its line where it ends nothing, or ";;".
    internal sealed class CTS0023 : Rule
    {
        static readonly Regex Standalone = new Regex(@"^[ \t]*;[ \t]*\r?$", RegexOptions.Multiline);
        static readonly Regex Duplicate = new Regex(@";[ \t]*;");
        static readonly Regex EmptyBlockHeader = new Regex(@"(?:\b(?:THEN|ELSE|DO|OF|REPEAT)|:)$", RegexOptions.IgnoreCase);

        internal CTS0023() : base("CTS0023", "Empty statement", Analysis.Severity.Style, "Style", "Standalone or duplicated semicolons that produce empty statements.", "CALLABLE")
        {
            Merge = "identical";
            Options["merge"] = true;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            List<StText.Comment> comments = null;
            var reported = new HashSet<int>();
            foreach (Match match in Standalone.Matches(text))
            {
                var lineEnd = text.IndexOf('\n', match.Index);
                if (lineEnd < 0) lineEnd = text.Length;
                comments = comments ?? StText.Comments(section.Raw);
                // A comment on the line documents the semicolon.
                if (comments.Any(comment => comment.Start < lineEnd && comment.End > match.Index)) continue;
                if (StText.HasIntentionalNoopComment(section.Raw, match.Index) || !EndsNothing(text, match.Index)) continue;
                var offset = section.At(match.Index + match.Value.IndexOf(';'));
                reported.Add(offset);
                yield return Finding.In(unit, "standalone empty statement has no effect", offset, offset + 1, ";", ";");
            }
            foreach (Match match in Duplicate.Matches(text))
            {
                var offset = section.At(match.Index + match.Length - 1);
                if (reported.Contains(offset)) continue;
                yield return Finding.In(unit, "duplicate semicolon creates an empty statement", offset, offset + 1, ";", match.Value);
            }
        }

        // A ';' on its own line still ends a statement that runs over several
        // lines; it is empty right after another ';', after a branch header
        // (whatever lines its condition takes) or after a CASE label.
        static bool EndsNothing(string text, int lineStart)
        {
            var semicolon = lineStart == 0 ? -1 : text.LastIndexOf(';', lineStart - 1);
            var before = text.Substring(semicolon + 1, lineStart - semicolon - 1).Trim();
            return before.Length == 0 || EmptyBlockHeader.IsMatch(before);
        }
    }
}
