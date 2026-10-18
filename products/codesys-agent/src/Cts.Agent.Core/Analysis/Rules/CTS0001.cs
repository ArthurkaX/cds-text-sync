using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A comment whose content still reads as executable ST: an assignment or
    // a call ending in ';', a keyword that is never English (RETURN, END_IF,
    // ...) or a keyword pair (IF..THEN, CASE..OF, ...). A comment of three
    // lines or more is code only when a third of its lines read so: prose
    // that quotes a statement is documentation. The anchor is the normalised
    // comment, so moving or reindenting it keeps the fingerprint.
    internal sealed class CTS0001 : Rule
    {
        static readonly Regex Assign = new Regex(@"\b[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?\s*:=\s*[^;\n]*;", RegexOptions.IgnoreCase);
        static readonly Regex DocumentationExample = new Regex(@"\b(?:example|e\.g\.|syntax|format|formula|pseudocode)\s*:", RegexOptions.IgnoreCase);
        static readonly Regex Call = new Regex(@"\b[A-Za-z_]\w*\s*\([^;\n]*\)\s*;");
        static readonly Regex Strong = new Regex(@"\b(ELSE|RETURN|EXIT|END_IF|END_FOR|END_WHILE|END_CASE|END_REPEAT)\b");
        static readonly Regex[][] Paired =
        {
            new[] { new Regex(@"\bIF\b"), new Regex(@"\bTHEN\b") },
            new[] { new Regex(@"\bFOR\b"), new Regex(@"\b(?:TO|DO)\b") },
            new[] { new Regex(@"\bWHILE\b"), new Regex(@"\bDO\b") },
            new[] { new Regex(@"\bCASE\b"), new Regex(@"\bOF\b") },
            new[] { new Regex(@"\bREPEAT\b"), new Regex(@"\bUNTIL\b") },
            new[] { new Regex(@"\bELSIF\b"), new Regex(@"\bTHEN\b") },
        };

        internal CTS0001() : base("CTS0001", "Commented-out code", Analysis.Severity.Suspicious, "Code quality", "ST statements that survive inside comments.", "CALLABLE")
        {
            Merge = "adjacent";
            Options["min_tokens"] = 4;
            Options["merge"] = true;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var minTokens = context.Option<int>("min_tokens");
            foreach (var comment in StText.Comments(unit.Text ?? ""))
            {
                if (!LooksLikeCode(comment.Content, minTokens)) continue;
                yield return Finding.In(unit, "commented-out code: " + Trim(comment.Content), comment.Start, comment.Start + comment.Content.Length,
                    Fingerprints.NormalizeContext(comment.Content), Trim(comment.Content));
            }
        }

        static bool LooksLikeCode(string content, int minTokens)
        {
            content = content.Trim();
            if (content.Length == 0 || DocumentationExample.IsMatch(content)) return false;
            if (StText.Unspaced(content).Length < minTokens || !ReadsAsCode(content)) return false;
            var lines = content.Split('\n').Select(line => line.Trim()).Where(line => line.Length > 0).ToList();
            return lines.Count < 3 || lines.Count(ReadsAsCode) * 3 >= lines.Count;
        }

        static bool ReadsAsCode(string text) =>
            Assign.IsMatch(text) || Call.IsMatch(text) || Strong.IsMatch(text) || Paired.Any(pair => pair[0].IsMatch(text) && pair[1].IsMatch(text));

        static string Trim(string content)
        {
            var collapsed = StText.Squeezed(content);
            return collapsed.Length > 60 ? collapsed.Substring(0, 59) + "…" : collapsed;
        }
    }
}
