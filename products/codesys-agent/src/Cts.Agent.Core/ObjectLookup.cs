using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    public sealed class ObjectRecord
    {
        public string Guid { get; set; }
        public string Name { get; set; }
        public string Type { get; set; }
        public Guid Parent { get; set; }
    }

    public static class ObjectLookup
    {
        public static IList<Dictionary<string, object>> Match(IEnumerable<ObjectRecord> records, string name, string path, string app = "")
        {
            var all = records.ToDictionary(x => x.Guid, StringComparer.OrdinalIgnoreCase);
            var paths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var partsByGuid = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in all.Values)
            {
                var parts = new List<string> { item.Name ?? "" };
                var parent = item.Parent;
                var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { item.Guid };
                while (parent != Guid.Empty && all.TryGetValue(parent.ToString(), out var p) && seen.Add(p.Guid))
                { parts.Add(p.Name ?? ""); parent = p.Parent; }
                parts.Reverse();
                partsByGuid[item.Guid] = parts.ToArray();
                paths[item.Guid] = String.Join("/", parts);
            }
            var pathParts = String.IsNullOrEmpty(path) ? null : path.Trim('/').Split('/');
            var found = !String.IsNullOrEmpty(path)
                ? all.Values.Where(x => pathParts.Length == partsByGuid[x.Guid].Length && pathParts.SequenceEqual(partsByGuid[x.Guid], StringComparer.OrdinalIgnoreCase))
                : all.Values.Where(x => String.Equals(x.Name, name, StringComparison.OrdinalIgnoreCase));
            if (!String.IsNullOrEmpty(app))
                found = found.Where(x => partsByGuid[x.Guid].Take(partsByGuid[x.Guid].Length - 1).Any(p => String.Equals(p, app, StringComparison.OrdinalIgnoreCase)));
            return found.Select(x => new Dictionary<string, object> { { "guid", x.Guid }, { "name", x.Name ?? "" }, { "path", paths[x.Guid] }, { "type", x.Type ?? "" } }).ToList();
        }
    }
}
