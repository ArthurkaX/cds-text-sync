using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Cts.Agent;

namespace Cts.Trend
{
    // The samples of a PLC's trend file, decoded into this PC's database of
    // the trend: one row per variable and moment, merged with the pulls
    // before, so the history outlasts the PLC's file, which drops its oldest
    // rows at its size limit.
    //
    // The PLC's file keeps a row per recorded cycle (TblTrendData: TS in µs,
    // Val1..ValN) and, per configuration the PLC ran, which column holds
    // which variable (TblTrendConfiguration: VarName, VarType, ColId) and
    // since when (TblTrendConfigurationDuration). A value is its variable's
    // raw bits as an integer. A row with no value at all is a gap: a cycle
    // while the recording was off (the PLC fills the time it was off with
    // them once it records again) or one its storage could not keep up with.
    internal static class TrendData
    {
        internal const string Schema =
            "samples(ts, name, value): ts in µs since 1970 (UTC as the PLC's clock has it); "
            + "samples_at(at, name, value, ts): the same with at as text; variables(name, type); gaps(ts): cycles with no values, "
            + "while the recording was off or the PLC could not store them";

        // The IEC type class the PLC names a variable's type by: its name,
        // its size in bits and whether it is signed.
        static readonly Dictionary<long, Tuple<string, int, bool>> Types = new Dictionary<long, Tuple<string, int, bool>>
        {
            [0] = Tuple.Create("BOOL", 1, false), [1] = Tuple.Create("BIT", 1, false),
            [2] = Tuple.Create("BYTE", 8, false), [3] = Tuple.Create("WORD", 16, false), [4] = Tuple.Create("DWORD", 32, false), [5] = Tuple.Create("LWORD", 64, false),
            [6] = Tuple.Create("SINT", 8, true), [7] = Tuple.Create("INT", 16, true), [8] = Tuple.Create("DINT", 32, true), [9] = Tuple.Create("LINT", 64, true),
            [10] = Tuple.Create("USINT", 8, false), [11] = Tuple.Create("UINT", 16, false), [12] = Tuple.Create("UDINT", 32, false), [13] = Tuple.Create("ULINT", 64, false),
            [14] = Tuple.Create("REAL", 32, false), [15] = Tuple.Create("LREAL", 64, false),
            [18] = Tuple.Create("TIME (ms)", 32, false), [19] = Tuple.Create("DATE (s)", 32, false), [20] = Tuple.Create("DT (s)", 32, false), [21] = Tuple.Create("TOD (ms)", 32, false),
        };

        internal sealed class Merged
        {
            internal long Rows, Gaps, Added;
            internal long? From, To;
            internal List<string> Variables = new List<string>();
        }

        // The PLC's file *plcFile* merged into *localFile*, the gate left out.
        internal static Merged Merge(string plcFile, string localFile, string gate)
        {
            var merged = new Merged();
            using (var plc = Sqlite.Open(plcFile, false))
            using (var local = Sqlite.Open(localFile, true))
            {
                var configurations = plc.Rows("SELECT Id, VarName, VarType, ColId FROM TblTrendConfiguration ORDER BY Id, VarIdx")
                    .Where(row => (string)row[1] != gate).GroupBy(row => (long)row[0])
                    .ToDictionary(group => group.Key, group => group.GroupBy(row => (string)row[1]).Select(same => same.First()).ToList());
                var since = plc.Rows("SELECT Id, TSFrom FROM TblTrendConfigurationDuration ORDER BY TSFrom")
                    .Select(row => Tuple.Create((long)row[1], (long)row[0])).ToList();
                local.Run("CREATE TABLE IF NOT EXISTS samples(ts INTEGER NOT NULL, name TEXT NOT NULL, value, PRIMARY KEY (name, ts)) WITHOUT ROWID");
                local.Run("CREATE TABLE IF NOT EXISTS variables(name TEXT PRIMARY KEY, type TEXT NOT NULL)");
                local.Run("CREATE TABLE IF NOT EXISTS gaps(ts INTEGER PRIMARY KEY)");
                local.Run("CREATE VIEW IF NOT EXISTS samples_at AS SELECT strftime('%Y-%m-%d %H:%M:%f', ts / 1000000.0, 'unixepoch') AS at, name, value, ts FROM samples");
                var before = Count(local);
                local.Run("BEGIN");
                using (var sample = local.Prepare("INSERT OR IGNORE INTO samples VALUES (?, ?, ?)"))
                using (var gap = local.Prepare("INSERT OR IGNORE INTO gaps VALUES (?)"))
                using (var variable = local.Prepare("INSERT OR REPLACE INTO variables VALUES (?, ?)"))
                using (var rows = plc.Prepare("SELECT * FROM TblTrendData ORDER BY TS"))
                {
                    foreach (var row in configurations.Values.SelectMany(columns => columns).GroupBy(row => (string)row[1]).Select(same => same.Last()))
                    {
                        variable.Run((string)row[1], TypeName((long)row[2]));
                        merged.Variables.Add((string)row[1]);
                    }
                    rows.Bind(new object[0]);
                    var named = rows.Columns().Select((name, at) => new { name, at }).ToDictionary(column => column.name, column => column.at, StringComparer.OrdinalIgnoreCase);
                    while (rows.Step())
                    {
                        var values = rows.Values();
                        var ts = Convert.ToInt64(values[0], CultureInfo.InvariantCulture);
                        merged.Rows++;
                        merged.From = merged.From ?? ts;
                        merged.To = ts;
                        if (values.Skip(1).All(value => value == null))
                        {
                            merged.Gaps++;
                            gap.Run(ts);
                            continue;
                        }
                        var id = since.LastOrDefault(start => start.Item1 <= ts)?.Item2 ?? since.FirstOrDefault()?.Item2 ?? 0;
                        if (!configurations.TryGetValue(id, out var columns)) continue;
                        foreach (var column in columns)
                        {
                            if (!named.TryGetValue("Val" + column[3], out var at) || values[at] == null) continue;
                            sample.Run(ts, (string)column[1], Decode(values[at], (long)column[2]));
                        }
                    }
                }
                local.Run("COMMIT");
                merged.Added = Count(local) - before;
            }
            return merged;
        }

        static long Count(Sqlite local) => (long)local.Rows("SELECT count(*) FROM samples")[0][0];

        static string TypeName(long type) => Types.TryGetValue(type, out var known) ? known.Item1 : "type class " + type.ToString(CultureInfo.InvariantCulture);

        // A stored value as its variable's type reads it.
        internal static object Decode(object stored, long type)
        {
            if (!(stored is long raw) || !Types.TryGetValue(type, out var known)) return stored;
            switch (known.Item1)
            {
                case "REAL":
                    var single = BitConverter.ToSingle(BitConverter.GetBytes((int)raw), 0);
                    return double.Parse(single.ToString("R", CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
                case "LREAL": return BitConverter.Int64BitsToDouble(raw);
            }
            var bits = known.Item2;
            if (bits == 64) return raw;
            var value = raw & ((1L << bits) - 1);
            return known.Item3 && (value >> (bits - 1)) != 0 ? value - (1L << bits) : value;
        }

        // This PC's database of the trend of *app* in the sync folder *root*.
        internal static string LocalFile(string root, string app)
        {
            var id = ProjectInfo.IdOf(root);
            var key = id.Length > 0 ? id : string.Concat(Path.GetFileName(root.TrimEnd('/', '\\')).Select(ch => char.IsLetterOrDigit(ch) || ch == '-' ? ch : '_'));
            return Path.Combine(Path.GetDirectoryName(ProjectInfo.RegistryPath()), "trend", key, app + ".sqlite");
        }
    }
}
