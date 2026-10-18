using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Analysis
{
    // The analyzer's state in <sync folder>/.cts-analyze, never inside the
    // view: baseline.json (machine written, one entry per line),
    // suppressions.json (each entry with its reason) and session.json (the
    // fix-later decisions). Each file is written whole through a temp file.
    internal static class AnalyzeState
    {
        const int StateSchema = 1;

        internal static List<IDictionary<string, object>> Baseline(string stateDir)
        {
            var data = ReadObject(Path.Combine(stateDir, "baseline.json"));
            if (data == null) return new List<IDictionary<string, object>>();
            if (data.TryGetValue("fingerprint_schema", out var schema) && schema != null && !Equals(Convert.ToInt64(schema, CultureInfo.InvariantCulture), (long)Analysis.Fingerprints.Schema))
                throw new AnalyzeException("baseline fingerprint schema " + schema + " is unsupported; run 'cts analyze baseline update'");
            if (data.TryGetValue("entries", out var entries) && entries != null && !(entries is IList<object>)) throw new AnalyzeException(Path.Combine(stateDir, "baseline.json") + ": entries is not a list");
            return ((entries as IList<object>) ?? new List<object>()).OfType<IDictionary<string, object>>().ToList();
        }

        internal static string BaselineCreated(string stateDir) => ReadObject(Path.Combine(stateDir, "baseline.json")) is IDictionary<string, object> data && data.TryGetValue("created", out var created) ? created as string : null;

        internal static HashSet<string> Fingerprints(IEnumerable<IDictionary<string, object>> entries) =>
            new HashSet<string>(entries.Select(entry => entry.TryGetValue("fingerprint", out var fp) ? fp as string : null).Where(fp => !string.IsNullOrEmpty(fp)));

        internal static void WriteBaseline(string stateDir, IEnumerable<IDictionary<string, object>> entries, string created)
        {
            var now = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'", CultureInfo.InvariantCulture);
            var sorted = entries.OrderBy(e => Text(e, "fingerprint"), StringComparer.Ordinal).ThenBy(e => Text(e, "rule_id"), StringComparer.Ordinal).ToList();
            var lines = new List<string>
            {
                "{", "  \"schema_version\": " + StateSchema + ",", "  \"fingerprint_schema\": " + Analysis.Fingerprints.Schema + ",",
                "  \"created\": " + Analysis.Fingerprints.Quote(created ?? now) + ",", "  \"updated\": " + Analysis.Fingerprints.Quote(now) + ",", "  \"entries\": [",
            };
            for (var i = 0; i < sorted.Count; i++)
                lines.Add("    {" + string.Join(", ", sorted[i].OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => Analysis.Fingerprints.Quote(p.Key) + ": " + Analysis.Fingerprints.Quote(Convert.ToString(p.Value, CultureInfo.InvariantCulture) ?? ""))) + "}" + (i < sorted.Count - 1 ? "," : ""));
            lines.Add("  ]");
            lines.Add("}");
            Write(Path.Combine(stateDir, "baseline.json"), string.Join("\n", lines) + "\n");
        }

        // Suppressions in force: a past "until" date ends one.
        internal static List<IDictionary<string, object>> Suppressions(string stateDir)
        {
            var path = Path.Combine(stateDir, "suppressions.json");
            if (!File.Exists(path)) return new List<IDictionary<string, object>>();
            object data;
            try { data = Json.Parse(File.ReadAllText(path)); }
            catch (JsonException error) { throw new AnalyzeException("cannot parse " + path + ": " + error.Message); }
            var list = data as IList<object> ?? throw new AnalyzeException(path + ": not a list");
            var entries = new List<IDictionary<string, object>>();
            for (var i = 0; i < list.Count; i++)
            {
                var entry = list[i] as IDictionary<string, object>;
                if (entry == null || Text(entry, "fingerprint").Length == 0) throw new AnalyzeException(path + ": entry " + i + " needs a fingerprint");
                if (Text(entry, "reason").Trim().Length == 0) throw new AnalyzeException(path + ": entry " + i + " needs a non-empty reason");
                entries.Add(entry);
            }
            return entries;
        }

        internal static bool Expired(IDictionary<string, object> entry) =>
            DateTime.TryParseExact(Text(entry, "until").Trim(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var until) && until < DateTime.Today;

        internal static void WriteSuppressions(string stateDir, IEnumerable<IDictionary<string, object>> entries) =>
            Write(Path.Combine(stateDir, "suppressions.json"), Json.Pretty(entries.Select(e => (object)new SortedDictionary<string, object>(e, StringComparer.Ordinal)).ToList()) + "\n");

        internal static List<object> Session(string stateDir) =>
            ReadObject(Path.Combine(stateDir, "session.json")) is IDictionary<string, object> data && data.TryGetValue("decisions", out var decisions) && decisions is IList<object> list ? list.ToList() : new List<object>();

        internal static void WriteSession(string stateDir, List<object> decisions) =>
            Write(Path.Combine(stateDir, "session.json"), Json.Pretty(new SortedDictionary<string, object>(StringComparer.Ordinal) { ["decisions"] = decisions, ["schema_version"] = StateSchema }) + "\n");

        static IDictionary<string, object> ReadObject(string path)
        {
            if (!File.Exists(path)) return null;
            try { return Json.Parse(File.ReadAllText(path)) as IDictionary<string, object> ?? throw new AnalyzeException(path + ": not an object"); }
            catch (JsonException error) { throw new AnalyzeException("cannot read " + path + ": " + error.Message); }
        }

        static void Write(string path, string text)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var temp = path + ".tmp";
            File.WriteAllText(temp, text, new UTF8Encoding(false));
            SafeFile.Replace(temp, path);
        }

        // Applies triage decisions (a JSON list of {fingerprint, action:
        // suppress|fix-later|baseline, reason, note}) after checking every one
        // against this run's findings; nothing is written when one is wrong.
        internal static Dictionary<string, object> Triage(string stateDir, AnalysisResult result, string decisionsPath)
        {
            if (string.IsNullOrEmpty(decisionsPath)) throw new AnalyzeException("no decisions file given (--apply <file>)");
            IList<object> raw;
            try { raw = Json.Parse(File.ReadAllText(decisionsPath)) as IList<object> ?? throw new AnalyzeException("decisions file must be a JSON list"); }
            catch (Exception error) when (error is IOException || error is JsonException || error is UnauthorizedAccessException) { throw new AnalyzeException("cannot read decisions file " + decisionsPath + ": " + error.Message); }
            var current = result.Findings.ToDictionary(f => f.Fingerprint, f => f);
            var decisions = new List<IDictionary<string, object>>();
            for (var i = 0; i < raw.Count; i++)
            {
                var item = raw[i] as IDictionary<string, object> ?? throw new AnalyzeException("decisions[" + i + "]: not an object");
                var action = Text(item, "action").Trim();
                if (!new[] { "suppress", "fix-later", "baseline" }.Contains(action)) throw new AnalyzeException("decisions[" + i + "]: action must be one of suppress,fix-later,baseline, got '" + action + "'");
                var fingerprint = Text(item, "fingerprint").Trim();
                if (fingerprint.Length == 0) throw new AnalyzeException("decisions[" + i + "]: missing fingerprint");
                if (action == "suppress" && Text(item, "reason").Trim().Length == 0) throw new AnalyzeException("decisions[" + i + "]: suppress needs a non-empty reason");
                if (!current.ContainsKey(fingerprint)) throw new AnalyzeException("decision " + fingerprint + " does not match any finding in this run");
                decisions.Add(item);
            }
            var suppressions = Suppressions(stateDir);
            var baseline = Baseline(stateDir);
            var session = Session(stateDir);
            var suppressed = new HashSet<string>(suppressions.Select(e => Text(e, "fingerprint")));
            var baselined = Fingerprints(baseline);
            var later = new HashSet<string>(session.OfType<IDictionary<string, object>>().Select(d => Text(d, "fingerprint")));
            foreach (var decision in decisions)
            {
                var fingerprint = Text(decision, "fingerprint").Trim();
                var finding = current[fingerprint];
                switch (Text(decision, "action").Trim())
                {
                    case "suppress":
                        if (suppressed.Add(fingerprint))
                            suppressions.Add(new Dictionary<string, object> { ["fingerprint"] = fingerprint, ["rule_id"] = finding.RuleId, ["unit_id"] = finding.UnitId ?? "", ["reason"] = Text(decision, "reason").Trim() });
                        break;
                    case "baseline":
                        if (baselined.Add(fingerprint))
                            baseline.Add(new Dictionary<string, object> { ["fingerprint"] = fingerprint, ["rule_id"] = finding.RuleId, ["unit_id"] = finding.UnitId ?? "", ["message"] = finding.Message });
                        break;
                    default:
                        if (later.Add(fingerprint))
                            session.Add(new SortedDictionary<string, object>(StringComparer.Ordinal) { ["fingerprint"] = fingerprint, ["action"] = "fix-later", ["note"] = Text(decision, "note").Trim() });
                        break;
                }
            }
            if (suppressions.Count > 0 || File.Exists(Path.Combine(stateDir, "suppressions.json"))) WriteSuppressions(stateDir, suppressions);
            if (baseline.Count > 0) WriteBaseline(stateDir, baseline, BaselineCreated(stateDir));
            WriteSession(stateDir, session);
            return new Dictionary<string, object>
            {
                ["suppressed"] = decisions.Count(d => Text(d, "action").Trim() == "suppress"),
                ["baselined"] = decisions.Count(d => Text(d, "action").Trim() == "baseline"),
                ["fix_later"] = decisions.Count(d => Text(d, "action").Trim() == "fix-later"),
            };
        }
    }
}
