using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // A project enum: member names lower-cased, in declaration order, with
    // their values.
    internal sealed class EnumType
    {
        static readonly Regex LabelSeparator = new Regex(@"\s*,\s*");
        internal static readonly Regex QualifiedName = new Regex(@"^(?:(?<type>[A-Za-z_]\w*)[.#])?(?<name>[A-Za-z_]\w*)$");

        internal string Name;
        internal readonly List<KeyValuePair<string, long?>> Members = new List<KeyValuePair<string, long?>>();
        internal bool Has(string name) => Members.Any(m => m.Key == name);
        internal bool HasValue(long value) => Members.Any(m => m.Value == value);

        internal static Dictionary<string, EnumType> Read(Snapshot snapshot)
        {
            var enums = new Dictionary<string, EnumType>(System.StringComparer.OrdinalIgnoreCase);
            foreach (var dut in snapshot.Units.Select(unit => unit.Dut).Where(dut => dut != null && dut.Kind == "enum" && dut.Fields.Count > 0))
            {
                var found = new EnumType { Name = dut.Name };
                foreach (var field in dut.Fields)
                {
                    var key = field.Name.ToLowerInvariant();
                    var at = found.Members.FindIndex(m => m.Key == key);
                    if (at >= 0) found.Members[at] = new KeyValuePair<string, long?>(key, field.Value);
                    else found.Members.Add(new KeyValuePair<string, long?>(key, field.Value));
                }
                enums[dut.Name] = found;
            }
            return enums;
        }

        internal static IEnumerable<string> Labels(string labels) => LabelSeparator.Split(labels).Select(label => label.Trim()).Where(label => label.Length > 0);

        // The members a CASE arm's labels name: a member (bare, T.x or T#x)
        // or a number one has as its value.
        internal IEnumerable<string> Covered(string labels)
        {
            foreach (var label in Labels(labels))
            {
                if (IecTypes.IsDecimal(label))
                {
                    var value = long.Parse(label, System.Globalization.CultureInfo.InvariantCulture);
                    foreach (var member in Members.Where(m => m.Value == value)) yield return member.Key;
                    continue;
                }
                var match = QualifiedName.Match(label);
                if (match.Success && Has(match.Groups["name"].Value.ToLowerInvariant())) yield return match.Groups["name"].Value.ToLowerInvariant();
            }
        }

        // Whether a CASE's labels are every member of one enum (bare or
        // qualified by it), nothing else: such a CASE leaves no value of its
        // selector out.
        internal static bool Covers(Block block, Dictionary<string, EnumType> enums)
        {
            var labels = block.Branches.SelectMany(branch => Labels(branch.Label)).Select(label => QualifiedName.Match(label.Replace(" ", ""))).ToList();
            if (labels.Count == 0 || labels.Any(label => !label.Success)) return false;
            var qualifiers = labels.Where(label => label.Groups["type"].Success).Select(label => label.Groups["type"].Value).Distinct(System.StringComparer.OrdinalIgnoreCase).ToList();
            var names = new HashSet<string>(labels.Select(label => label.Groups["name"].Value.ToLowerInvariant()));
            var candidates = qualifiers.Count == 1 ? (enums.TryGetValue(qualifiers[0], out var named) ? new[] { named } : new EnumType[0])
                : qualifiers.Count == 0 ? enums.Values.ToArray() : new EnumType[0];
            return candidates.Count(type => type.Members.Count == names.Count && names.All(type.Has)) == 1;
        }
    }
}
