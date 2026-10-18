using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Docs;

namespace Cts.Analysis.Rules
{
    // A program, function block or function without the description cts
    // docs shows for it (a comment on, after or above its header), and an
    // input, output or in-out without a comment on its line or above it.
    // Attribute lines between a comment and what it documents do not count.
    internal sealed class CTS0073 : Rule
    {
        static readonly Regex Attribute = new Regex(@"^\s*\{.*\}\s*$");
        static readonly HashSet<string> InterfaceScopes = new HashSet<string> { "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT" };

        internal CTS0073() : base("CTS0073", "Missing public POU documentation", Analysis.Severity.Style, "Code quality", "Public POUs and interface parameters should explain their contract.",
            Analysis.Kinds.Program, Analysis.Kinds.FunctionBlock, Analysis.Kinds.Function)
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.DeclarationSection;
            if (section.IsEmpty) yield break;
            var lines = section.Lines().ToList();
            var comments = StText.Comments(section.Raw);
            // The part of line index not covered by comments, null when no comment touches it.
            string Uncommented(int index)
            {
                var start = lines[index].Item2 - section.Base;
                var text = lines[index].Item3.ToCharArray();
                var touched = false;
                foreach (var comment in comments.Where(comment => comment.Start < start + text.Length && comment.End > start))
                {
                    touched = true;
                    for (var i = Math.Max(0, comment.Start - start); i < Math.Min(text.Length, comment.End - start); i++) text[i] = ' ';
                }
                return touched ? new string(text) : null;
            }
            bool DocumentedAbove(int index)
            {
                for (var cursor = index - 1; cursor >= 0; cursor--)
                {
                    var stripped = lines[cursor].Item3.Trim();
                    if (stripped.Length == 0 || Attribute.IsMatch(stripped)) continue;
                    return Uncommented(cursor)?.Trim().Length == 0;
                }
                return false;
            }

            var header = unit.Header;
            if (header.Success && ProjectDocs.Description(unit.Text, unit.DeclarationStart + header.Index).Length == 0)
            {
                var line = lines.Last(item => item.Item2 <= section.At(header.Index));
                var name = header.Groups["name"].Value;
                yield return Finding.In(unit, "public POU '" + name + "' has no documentation comment",
                    line.Item2 + line.Item3.Length - line.Item3.TrimStart().Length, line.Item2 + line.Item3.Length, name, line.Item3.Trim());
            }
            foreach (var member in unit.Members().Where(member => InterfaceScopes.Contains(member.Scope) && member.Line >= 1 && member.Line <= lines.Count))
            {
                if (Uncommented(member.Line - 1) != null || DocumentedAbove(member.Line - 1)) continue;
                yield return Finding.In(unit, "interface parameter '" + member.Name + "' has no documentation comment",
                    unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
            }
        }
    }
}
