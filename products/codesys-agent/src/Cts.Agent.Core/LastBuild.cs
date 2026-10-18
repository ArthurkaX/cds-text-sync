// How the last build ended, kept in the memory of the agent that ran it, so
// the outcome survives a CLI that stopped waiting: `last_command` in
// `project.status`.
//
// The error and warning counts: CODESYS qualifies the word ("Compile Error"), so a severity is matched by substring,
// whatever its casing, error before warning.
using System;
using System.Collections.Generic;
using System.Globalization;

namespace Cts.Agent
{
    public static class LastBuild
    {
        // The record of one `app.build` answer: `ok` when it compiled without
        // an error message.
        public static Dictionary<string, object> Record(IDictionary<string, object> answer, IEnumerable<string> severities, DateTime utc)
        {
            int errors, warnings;
            Count(severities, out errors, out warnings);
            object path;
            answer.TryGetValue("project_path", out path);
            return new Dictionary<string, object>
            {
                { "method", "build" },
                { "ok", Equals(answer["compiled"], true) && errors == 0 },
                { "errors", errors },
                { "warnings", warnings },
                { "recorded_at", utc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'") },
                { "project_path", Convert.ToString(path) },
            };
        }

        public static void Count(IEnumerable<string> severities, out int errors, out int warnings)
        {
            errors = 0;
            warnings = 0;
            foreach (var severity in severities)
            {
                var text = (severity ?? "").ToLowerInvariant();
                if (text.Contains("error")) errors++;
                else if (text.Contains("warning")) warnings++;
            }
        }

        // The `last_command` of `project.status`: the record without its path,
        // when the build was of the project at `path`; null otherwise.
        // `changed_after` when an object changed after the build (`lastChange`,
        // UTC) in a later second: the stamp has no finer grain.
        public static Dictionary<string, object> Brief(IDictionary<string, object> record, string path, DateTime lastChange)
        {
            if (record == null || !string.Equals(Convert.ToString(record["project_path"]), path ?? "", StringComparison.OrdinalIgnoreCase))
                return null;
            var brief = new Dictionary<string, object>(record);
            brief.Remove("project_path");
            DateTime built;
            if (DateTime.TryParseExact(Convert.ToString(record["recorded_at"]), "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture,
                    DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out built) && lastChange >= built.AddSeconds(1))
                brief["changed_after"] = true;
            return brief;
        }
    }
}
