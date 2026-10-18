using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Cts.Sync
{
    // The kinds of the IDE's object types (TypeKinds.json): each type GUID
    // to a kind, the GUIDs ST alone cannot tell apart, and the text file the
    // export writes for a kind (`format` st or csv).
    internal sealed class TypeKinds
    {
        readonly Dictionary<string, string> _kinds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, HashSet<string>> _ambiguous = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        readonly List<IDictionary<string, object>> _projections = new List<IDictionary<string, object>>();

        internal static readonly TypeKinds All = Read();

        static TypeKinds Read()
        {
            var result = new TypeKinds();
            IDictionary<string, object> data;
            using (var stream = typeof(TypeKinds).Assembly.GetManifestResourceStream("Cts.Sync.TypeKinds.json"))
            using (var reader = new StreamReader(stream, Encoding.UTF8)) data = (IDictionary<string, object>)Cts.Agent.Json.Parse(reader.ReadToEnd());
            foreach (var pair in (IDictionary<string, object>)data["guid_aliases"])
                foreach (var guid in (IList<object>)pair.Value) result._kinds[Convert.ToString(guid).Trim().Trim('{', '}')] = pair.Key;
            foreach (var pair in (IDictionary<string, object>)data["ambiguous_text_type_guids"])
                result._ambiguous[pair.Key] = new HashSet<string>(((IList<object>)pair.Value).Select(g => Convert.ToString(g).Trim().Trim('{', '}')), StringComparer.OrdinalIgnoreCase);
            result._projections.AddRange(((IList<object>)data["projections"]).Cast<IDictionary<string, object>>());
            return result;
        }

        internal string Kind(string guid) { string kind; return _kinds.TryGetValue((guid ?? "").Trim().Trim('{', '}'), out kind) ? kind : null; }
        internal string TypeGuid(string kind) => _kinds.FirstOrDefault(pair => string.Equals(pair.Value, kind, StringComparison.OrdinalIgnoreCase)).Key;
        internal bool IsAmbiguous(string kind, string guid) { HashSet<string> values; return _ambiguous.TryGetValue(kind ?? "", out values) && values.Contains((guid ?? "").Trim().Trim('{', '}')); }
        internal IEnumerable<IDictionary<string, object>> Projections => _projections;
    }
}
