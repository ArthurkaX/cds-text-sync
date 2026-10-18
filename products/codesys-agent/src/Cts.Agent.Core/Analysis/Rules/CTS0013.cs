using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A local or global variable no analysed implementation names and no XML
    // of the view (a device's I/O mapping, a screen) reaches by its path.
    // Interface members (inputs, outputs, in-outs) have their own rules;
    // spare/dummy names are meant to be unused.
    internal sealed class CTS0013 : Rule
    {
        static readonly Regex Placeholder = new Regex(@"^(?:spare|dummy|reserved|unused|padding|filler)$", RegexOptions.IgnoreCase);
        static readonly Regex NonAlphanumeric = new Regex(@"[^A-Za-z0-9]+");
        static readonly HashSet<string> Candidates = new HashSet<string> { "VAR", "VAR_TEMP", "VAR_STAT", "VAR_GLOBAL" };

        internal CTS0013() : base("CTS0013", "Declared symbol not referenced", Analysis.Severity.Suspicious, "Dead code", "Declared variables with no explicit reference in analyzed ST.")
        {
            Requires = new[] { Needs.Declarations, Needs.StText, Needs.VisuXml };
        }

        internal override bool PerUnit => false;

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            HashSet<string> everywhere = null;
            var visible = new HashSet<string>(context.Units.Select(unit => unit.Id));
            foreach (var unit in context.Units)
            {
                HashSet<string> own = null;
                foreach (var member in unit.Members())
                {
                    var scope = (member.Scope ?? "").ToUpperInvariant();
                    if (string.IsNullOrEmpty(member.Name) || !Candidates.Contains(scope) || IsPlaceholder(member.Name)) continue;
                    bool used;
                    if (scope == "VAR_GLOBAL") used = (everywhere ?? (everywhere = Tokens(context.Units))).Contains(member.Name.ToLowerInvariant());
                    else used = (own ?? (own = Tokens(new[] { unit }.Concat(context.Snapshot.OwnedBy(unit.QualifiedName).Where(u => visible.Contains(u.Id)))))).Contains(member.Name.ToLowerInvariant());
                    if (used || context.External.IsReferenced(Snapshot.LastSegment(unit.QualifiedName), member.Name)) continue;
                    yield return Finding.In(unit, "declared symbol '" + member.Name + "' has no explicit reference in the analyzed Structured Text",
                        unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
                }
            }
        }

        static bool IsPlaceholder(string name) => NonAlphanumeric.Split(name).Any(part => part.Length > 0 && Placeholder.IsMatch(part));

        static HashSet<string> Tokens(IEnumerable<Unit> units) =>
            new HashSet<string>(units.Where(unit => !string.IsNullOrEmpty(unit.Implementation))
                .SelectMany(unit => StText.Name.Matches(unit.Body.Text).Cast<Match>().Select(m => m.Groups["name"].Value.ToLowerInvariant())), StringComparer.Ordinal);
    }
}
