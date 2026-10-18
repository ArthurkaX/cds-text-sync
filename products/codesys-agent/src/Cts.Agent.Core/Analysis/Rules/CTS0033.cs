using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A local initialised with a constant expression that no code can change:
    // never assigned, indexed, dotted into or passed to a call (which could
    // take it VAR_IN_OUT or by address). VAR CONSTANT says so to the reader.
    internal sealed class CTS0033 : Rule
    {
        static readonly Regex Identifier = new Regex(@"\b[A-Za-z_]\w*\b");
        static readonly Regex TypedLiteral = new Regex(@"\b[A-Za-z_]\w*\s*#\s*[A-Za-z0-9_.:-]+", RegexOptions.IgnoreCase);
        static readonly Regex UnsafeType = new Regex(@"\b(?:ARRAY|POINTER|REFERENCE|INTERFACE|VARIANT)\b", RegexOptions.IgnoreCase);
        static readonly Regex At = new Regex(@"\bAT\b", RegexOptions.IgnoreCase);
        static readonly HashSet<string> ConstantWords = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "TRUE", "FALSE", "NULL", "AND", "OR", "XOR", "NOT", "MOD" };
        static readonly HashSet<string> LocalScopes = new HashSet<string> { "VAR", "VAR_TEMP", "VAR_STAT" };

        internal CTS0033() : base("CTS0033", "Variable could be declared CONSTANT", Analysis.Severity.Style, "Style", "Local variables with constant initialization and no possible mutation.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (string.IsNullOrEmpty(unit.Declaration)) yield break;
            var lines = unit.Declaration.Split('\n');
            var visible = new HashSet<string>(context.Units.Select(candidate => candidate.Id));
            var owned = context.Snapshot.OwnedBy(unit.QualifiedName).Where(candidate => visible.Contains(candidate.Id)).ToList();
            foreach (var block in unit.VarBlocks.Where(block => LocalScopes.Contains(block.Scope) && !block.Constant && !block.Retain && !block.Persistent))
                foreach (var member in block.Members)
                {
                    if (member.Name.Length == 0 || UnsafeType.IsMatch(member.Type) || !LooksConstant(member.Initial)) continue;
                    if (member.Line >= 1 && member.Line <= lines.Length && At.IsMatch(lines[member.Line - 1])) continue;
                    var readers = new[] { unit }.Concat(owned.Where(other => other.Members().All(hiding => !hiding.Name.Equals(member.Name, StringComparison.OrdinalIgnoreCase))));
                    if (readers.Any(reader => MayChange(reader.Body.Text, member.Name))) continue;
                    yield return Finding.In(unit, "variable '" + member.Name + "' is initialized with a constant and is never modified; consider declaring it CONSTANT", unit.MemberOffset(member),
                        anchor: member.Name, context: member.Name + " : " + member.Type + " := " + member.Initial);
                }
        }

        // Literals and operators only: every identifier is TRUE, FALSE, NULL
        // or an operator word once typed literals (INT#5, T#1s) are gone.
        static bool LooksConstant(string expression)
        {
            if (string.IsNullOrWhiteSpace(expression)) return false;
            var clean = TypedLiteral.Replace(StText.Blanked(expression), " ");
            return Identifier.Matches(clean).Cast<Match>().All(token => ConstantWords.Contains(token.Value));
        }

        static bool MayChange(string text, string name)
        {
            foreach (Match match in new Regex(@"\b" + Regex.Escape(name) + @"\b", RegexOptions.IgnoreCase).Matches(text))
            {
                var next = match.Index + match.Length;
                while (next < text.Length && char.IsWhiteSpace(text[next])) next++;
                if (string.CompareOrdinal(text, next, ":=", 0, 2) == 0 || next < text.Length && (text[next] == '[' || text[next] == '.')) return true;
                if (StCalls.InArgument(text, match.Index)) return true;
            }
            return false;
        }
    }
}
