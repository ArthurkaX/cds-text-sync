using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A function block's output no code outside the block reads: through
    // instance.Output, an output mapping (Output => target) or a screen's XML.
    // Every instance discarding it on purpose (Output => ) is a reading too.
    // A block with no instance at all is unused as a whole (CTS0100), not
    // output by output.
    internal sealed class CTS0094 : Rule
    {
        static readonly Regex DottedAccess = new Regex(@"\b(?<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)+)\b", RegexOptions.IgnoreCase);
        static readonly Regex Call = new Regex(@"\b(?<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*\(", RegexOptions.IgnoreCase);
        static readonly Regex OutputMapping = new Regex(@"\b(?<output>[A-Za-z_]\w*)\s*=>\s*(?<target>[^,;)\r\n]*)", RegexOptions.IgnoreCase);

        internal CTS0094() : base("CTS0094", "Unused function-block output", Analysis.Severity.Suspicious, "Interfaces", "A function-block output has no external consumer in the project view.")
        {
            Requires = new[] { Needs.Declarations, Needs.StText, Needs.VisuXml };
        }

        internal override bool PerUnit => false;

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            var reads = new Dictionary<string, HashSet<string>>();
            var ignored = new Dictionary<string, HashSet<string>>();
            foreach (var unit in context.Units.Where(unit => !unit.Body.IsEmpty)) Index(unit, reads, ignored);
            var visible = new HashSet<string>(context.Units.Select(unit => unit.Id));
            foreach (var owner in context.Units.Where(unit => unit.Kind == Analysis.Kinds.FunctionBlock))
            {
                var outputs = owner.Members("VAR_OUTPUT").ToList();
                if (outputs.Count == 0) continue;
                var own = new HashSet<string>(new[] { owner.Id }.Concat(context.Snapshot.OwnedBy(owner.QualifiedName).Where(u => visible.Contains(u.Id)).Select(u => u.Id)));
                var instances = Instances(context, owner, own);
                if (instances.Count == 0) continue;
                bool Outside(Dictionary<string, HashSet<string>> index, string instance, string output) =>
                    index.TryGetValue(instance + "\n" + output.ToLowerInvariant(), out var sources) && sources.Any(source => !own.Contains(source));
                foreach (var member in outputs)
                {
                    if (member.Name.Length == 0 || instances.Any(i => Outside(reads, i, member.Name)) || instances.All(i => Outside(ignored, i, member.Name))
                        || instances.Any(i => context.External.IsReferenced(i, member.Name))) continue;
                    yield return Finding.In(owner, "function-block output '" + member.Name + "' has no external read in Structured Text or visualization XML",
                        owner.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
                }
            }
        }

        // instance.output reads and Output => target mappings, by
        // "instance\noutput" (lower case), with the units they are in.
        static void Index(Unit unit, Dictionary<string, HashSet<string>> reads, Dictionary<string, HashSet<string>> ignored)
        {
            var text = unit.Body.Text;
            foreach (Match match in DottedAccess.Matches(text))
            {
                var parts = Path(match.Groups["path"].Value).Split('.');
                Add(reads, string.Join(".", parts.Take(parts.Length - 1)) + "\n" + parts[parts.Length - 1], unit.Id);
            }
            foreach (Match call in Call.Matches(text))
            {
                var path = Path(call.Groups["path"].Value);
                var end = text.IndexOf(';', call.Index);
                if (end < 0) end = text.Length;
                // Only up to the statement's end: a search to the text's end
                // from every call reads a long body once per call.
                var start = call.Index + call.Length;
                for (var mapping = OutputMapping.Match(text, start, Math.Max(0, end - start)); mapping.Success; mapping = mapping.NextMatch())
                {
                    Add(mapping.Groups["target"].Value.Trim().Length > 0 ? reads : ignored, path + "\n" + mapping.Groups["output"].Value.ToLowerInvariant(), unit.Id);
                }
            }
        }

        static string Path(string text) => string.Join(".", text.Split('.').Select(part => part.Trim().ToLowerInvariant()));

        static void Add(Dictionary<string, HashSet<string>> index, string key, string unit)
        {
            if (!index.TryGetValue(key, out var set)) index[key] = set = new HashSet<string>();
            set.Add(unit);
        }

        // The lower-case paths code outside the block reaches its instances
        // by: a local name, GVL.name, and the bare GVL name when only one GVL
        // has an instance by that name.
        static HashSet<string> Instances(RuleContext context, Unit owner, HashSet<string> own)
        {
            var names = new HashSet<string> { owner.QualifiedName.ToLowerInvariant(), Snapshot.LastSegment(owner.QualifiedName).ToLowerInvariant() };
            var instances = new Dictionary<string, string>();
            foreach (var unit in context.Units.Where(unit => !own.Contains(unit.Id)))
                foreach (var member in unit.Members())
                {
                    var type = (member.Type ?? "").Trim().ToLowerInvariant();
                    if (member.Name.Length == 0 || !(names.Contains(type) || names.Contains(Snapshot.LastSegment(type)))) continue;
                    var global = unit.Kind == Analysis.Kinds.Gvl || unit.Kind == Analysis.Kinds.GvlPersistent;
                    var path = global ? unit.QualifiedName + "." + member.Name : member.Name;
                    instances[path.ToLowerInvariant()] = path;
                    if (!global) continue;
                    var simple = member.Name.ToLowerInvariant();
                    if (!instances.TryGetValue(simple, out var previous)) instances[simple] = path;
                    else if (previous != path) instances.Remove(simple);
                }
            return new HashSet<string>(instances.Keys);
        }
    }
}
