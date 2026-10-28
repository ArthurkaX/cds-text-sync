using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using static Cts.Agent.JsonMap;

namespace Cts.Trend
{
    // The samples of the PLC's trace as `trace.samples` answers them, one
    // list of times and values per variable, in one table: a row per time
    // (relative to the trace's start, in its resolution), a column per
    // variable.  The variables of one trace share their times; a time one
    // of them lacks is empty in its column.
    internal sealed class TraceTable
    {
        //: A variable that changes at most this often has its changes listed.
        internal const int ListedChanges = 10;

        internal string Unit;
        internal List<string> Names = new List<string>(), Types = new List<string>();
        internal List<long> Times = new List<long>();
        internal List<object[]> Rows = new List<object[]>();

        internal static TraceTable Of(IDictionary<string, object> answer)
        {
            var table = new TraceTable { Unit = Equals(Value(answer, "microseconds"), true) ? "us" : "ms" };
            var columns = (Value(answer, "variables") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
            var rows = new SortedDictionary<long, object[]>();
            for (var column = 0; column < columns.Count; column++)
            {
                table.Names.Add(Convert.ToString(Value(columns[column], "name"), CultureInfo.InvariantCulture));
                table.Types.Add(Convert.ToString(Value(columns[column], "type"), CultureInfo.InvariantCulture).ToUpperInvariant());
                var times = (Value(columns[column], "t") as IList<object>) ?? new object[0];
                var values = (Value(columns[column], "v") as IList<object>) ?? new object[0];
                for (var at = 0; at < Math.Min(times.Count, values.Count); at++)
                {
                    var time = Convert.ToInt64(times[at], CultureInfo.InvariantCulture);
                    if (!rows.TryGetValue(time, out var row)) rows[time] = row = new object[columns.Count];
                    row[column] = values[at];
                }
            }
            table.Times.AddRange(rows.Keys);
            table.Rows.AddRange(rows.Values);
            return table;
        }

        internal long Span => Times.Count < 2 ? 0 : Times[Times.Count - 1] - Times[0];

        // Comma-separated: the time, then a column per variable.
        internal void Write(string file)
        {
            var text = new StringBuilder();
            text.Append("t_" + Unit);
            foreach (var name in Names) text.Append(',').Append(name);
            text.Append('\n');
            for (var row = 0; row < Times.Count; row++)
            {
                text.Append(Times[row].ToString(CultureInfo.InvariantCulture));
                foreach (var value in Rows[row]) text.Append(',').Append(Field(value));
                text.Append('\n');
            }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file)));
            File.WriteAllText(file, text.ToString(), new UTF8Encoding(false));
        }

        // One line per variable: its type, its first and last value, its
        // range and how often it changed -- and when, for one that seldom does.
        internal List<string> Summary()
        {
            var lines = new List<string>();
            for (var column = 0; column < Names.Count; column++)
            {
                var present = Enumerable.Range(0, Times.Count).Where(row => Rows[row][column] != null).ToList();
                var line = new StringBuilder(Names[column]).Append("  ").Append(Types[column]);
                if (present.Count == 0) { lines.Add(line.Append("  no samples").ToString()); continue; }
                var values = present.Select(row => Rows[row][column]).ToList();
                var numbers = values.Where(value => value is long || value is double).Select(Convert.ToDouble).ToList();
                line.Append("  first ").Append(Field(values[0])).Append(" last ").Append(Field(values[values.Count - 1]));
                if (numbers.Count > 0) line.Append(" min ").Append(Number(numbers.Min())).Append(" max ").Append(Number(numbers.Max()));
                var changes = Enumerable.Range(1, values.Count - 1).Where(at => !Equals(values[at], values[at - 1])).ToList();
                line.Append(" changes ").Append(changes.Count);
                if (changes.Count > 0 && changes.Count <= ListedChanges)
                    line.Append(": ").Append(string.Join(", ", changes.Select(at => Times[present[at]].ToString(CultureInfo.InvariantCulture)
                        + " " + Unit + " " + Field(values[at - 1]) + "->" + Field(values[at]))));
                lines.Add(line.ToString());
            }
            return lines;
        }

        static string Number(double value) => value.ToString("R", CultureInfo.InvariantCulture);

        static string Field(object value)
        {
            switch (value)
            {
                case null: return "";
                case double number: return Number(number);
                case string text: return text.IndexOfAny(new[] { ',', '"', '\n', '\r' }) < 0 ? text : "\"" + text.Replace("\"", "\"\"") + "\"";
                default: return Convert.ToString(value, CultureInfo.InvariantCulture);
            }
        }
    }
}
