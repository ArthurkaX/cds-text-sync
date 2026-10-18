using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A variable of a project enum given a value the enum does not declare
    // (in its declaration or by an assignment), and a CASE on one that
    // leaves members out with no ELSE.
    internal sealed class CTS0059 : Rule
    {
        static readonly Regex Assignment = new Regex(@"(?<name>[A-Za-z_]\w*)\s*:=\s*(?<value>[^;]+)", RegexOptions.IgnoreCase);
        static readonly Regex CaseHeader = new Regex(@"\bCASE\s+(?<selector>[A-Za-z_]\w*)\s+OF\b", RegexOptions.IgnoreCase);

        internal CTS0059() : base("CTS0059", "Unsafe enumeration use", Analysis.Severity.Danger, "Correctness", "Enumeration assignments and CASE branches must use declared members.")
        {
            Requires = new[] { Needs.Declarations, Needs.StText, Needs.BlockStructure };
        }

        internal override bool PerUnit => false;

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            var enums = context.Enums;
            if (enums.Count == 0) yield break;
            foreach (var unit in context.Units)
            {
                var seen = context.Snapshot.MembersSeenBy(unit).ToList();
                var variables = new Dictionary<string, Tuple<VarMember, EnumType>>(StringComparer.OrdinalIgnoreCase);
                foreach (var member in seen)
                {
                    var shape = StDeclarations.ClassifyType(member.Type);
                    if (shape.Kind == "ref" && enums.TryGetValue(shape.Name ?? "", out var type)) variables[member.Name] = Tuple.Create(member, type);
                }
                if (variables.Count == 0) continue;
                // An inherited member's initial value is its owner's finding.
                var own = new HashSet<string>(unit.Members().Select(m => m.Name), StringComparer.OrdinalIgnoreCase);
                foreach (var variable in variables.Values.Where(v => own.Contains(v.Item1.Name)))
                {
                    var initial = (variable.Item1.Initial ?? "").Trim();
                    if (initial.Length == 0 || IsDeclared(initial, variable.Item2)) continue;
                    var offset = unit.MemberOffset(variable.Item1);
                    yield return Invalid(unit, variable.Item2, variable.Item1.Name, "member " + initial + " is not declared", initial, offset, offset + variable.Item1.Name.Length, variable.Item1.Name);
                }
                var section = unit.Body;
                if (section.IsEmpty) continue;
                foreach (Match match in Assignment.Matches(section.Text))
                {
                    if (!variables.TryGetValue(match.Groups["name"].Value, out var target)) continue;
                    var value = match.Groups["value"].Value.Trim();
                    var type = target.Item2;
                    string detail;
                    if (IecTypes.IsDecimal(value))
                    {
                        if (type.HasValue(long.Parse(value, System.Globalization.CultureInfo.InvariantCulture))) continue;
                        detail = "numeric value " + value + " is not one of " + string.Join(", ", type.Members.Select(m => m.Value.HasValue ? m.Key + "=" + m.Value.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : m.Key));
                    }
                    else
                    {
                        if (!NamesMember(value, type, seen, context)) continue;
                        detail = "member " + value + " is not declared";
                    }
                    var start = match.Groups["value"].Index;
                    yield return Invalid(unit, type, target.Item1.Name, detail, match.Value.Trim(), section.At(start), section.At(start + match.Groups["value"].Length), value);
                }
                foreach (var block in unit.Tree.Descendants().Where(b => b.Kind == "CASE" && b.End.HasValue))
                {
                    var header = CaseHeader.Match(section.Text, block.Start - section.Base);
                    if (!header.Success || header.Index + header.Length > block.End.Value - section.Base) continue;
                    if (!variables.TryGetValue(header.Groups["selector"].Value, out var selector) || block.Branches.Any(b => b.Label.Trim().ToUpperInvariant() == "ELSE")) continue;
                    var type = selector.Item2;
                    var covered = new HashSet<string>(block.Branches.SelectMany(b => type.Covered(b.Label)));
                    var missing = type.Members.Select(m => m.Key).Where(name => !covered.Contains(name)).ToList();
                    if (missing.Count == 0) continue;
                    var expression = header.Value.Trim();
                    yield return Finding.In(unit, "CASE on enum '" + type.Name + "' does not cover members: " + string.Join(", ", missing) + " and has no ELSE branch",
                        section.At(header.Index), section.At(header.Index + header.Length), expression, expression);
                }
            }
        }

        // A value that names a member of type it does not declare: the type's
        // own T.x or T#x, or a bare name no variable it can see has. Another
        // qualifier (a GVL, an instance) and an expression are not members.
        static bool NamesMember(string value, EnumType type, List<VarMember> seen, RuleContext context)
        {
            var parts = value.Replace(" ", "").Split('.', '#');
            if (!EnumType.QualifiedName.IsMatch(value.Replace(" ", ""))) return false;
            var name = parts.Last().ToLowerInvariant();
            if (type.Has(name)) return false;
            if (parts.Length == 2) return parts[0].Equals(type.Name, StringComparison.OrdinalIgnoreCase);
            return !seen.Any(m => m.Name.Equals(name, StringComparison.OrdinalIgnoreCase)) && !context.Globals.Declares(name);
        }

        // A declaration's initial value: a declared number, or a member name.
        static bool IsDeclared(string value, EnumType type)
        {
            if (IecTypes.IsDecimal(value)) return type.HasValue(long.Parse(value, System.Globalization.CultureInfo.InvariantCulture));
            var typed = EnumType.QualifiedName.Match(value.Replace(" ", ""));
            return typed.Success && type.Has(typed.Groups["name"].Value.ToLowerInvariant());
        }

        static Finding Invalid(Unit unit, EnumType type, string target, string detail, string context, int? offset, int? endOffset, string anchor) =>
            Finding.In(unit, "assignment to enum '" + type.Name + "' variable '" + target + "' is invalid: " + detail, offset, endOffset, anchor, context);
    }
}
