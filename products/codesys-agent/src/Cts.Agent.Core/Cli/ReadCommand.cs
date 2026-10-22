using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using Cts.Agent;
using Cts.Analysis;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static class ReadCommand
    {

        internal static IList<IDictionary<string, object>> VariableLeaves(IEnumerable<IDictionary<string, object>> objects)
        {
            var rows = objects.ToList();
            var index = new DeclarationIndex(rows.Select(x => Convert.ToString(Value(x, "declaration") ?? "", CultureInfo.InvariantCulture)));
            return index.VariableLeaves(rows).Select(x => (IDictionary<string, object>)new Dictionary<string, object>
            { { "path", x.Key }, { "type", x.Value } }).OrderBy(x => Convert.ToString(x["path"], CultureInfo.InvariantCulture), StringComparer.OrdinalIgnoreCase).ToList();
        }

        public static readonly CliCommand Command = new CliCommand
        {
            Name = "read", Arguments = "[NAME ...]", ArgumentHelp = "Variable expressions; one per --file line may be added.",
            Summary = "Read PLC variables or expressions",
            Description = "Reads every name in one vars.read request. --samples repeats the read; --until waits for one name to show a value.",
            TimeoutKey = "read_variables",
            Options = new[]
            {
                CliOption.Text("--file", "file", "PATH", "Read names from a file, one expression per line; blank lines and #-comments are ignored"),
                CliOption.Int("--samples", "samples", "Read this many samples (default: 1)"),
                CliOption.Text("--interval", "interval", "SECONDS", "Seconds between samples, or reads for --until (default: 1)"),
                CliOption.Text("--until", "until", "VALUE", "Read one name until it shows this value"),
                CliOption.Text("--within", "within", "SECONDS", "Maximum time --until waits (default: 30)"),
            },
            Execute = Execute, Build = Build,
        };

        static IDictionary<string, object> Execute(CliCall call)
        {
            var names = new List<string>(call.Options.Arguments);
            if (call.Options.Params.TryGetValue("file", out var file) && !string.IsNullOrEmpty(Convert.ToString(file)))
            {
                var path = Convert.ToString(file);
                if (!File.Exists(path)) throw new CliFailure("read", "file not found", "File not found: " + path, null, 1);
                names.AddRange(File.ReadAllLines(path).Select(x => x.Trim()).Where(x => x.Length > 0 && !x.StartsWith("#", StringComparison.Ordinal)));
            }
            if (names.Count == 0) throw new CliFailure("read", "no variable names given", "No variable names given. Pass names as arguments or via --file.", "cts read --help", 1);
            var interval = JsonMap.Number(call.Options.Params, "interval", 1);
            var within = JsonMap.Number(call.Options.Params, "within", 30);
            var count = call.Options.Params.TryGetValue("samples", out var sampleValue) ? Convert.ToInt32(sampleValue, CultureInfo.InvariantCulture) : 1;
            if (count < 1) count = 1;
            if (call.Options.Params.TryGetValue("until", out var expected))
            {
                if (names.Count != 1) throw Usage("--until waits for one name, not " + names.Count);
                var started = DateTime.UtcNow;
                var reads = 0;
                IDictionary<string, object> row;
                bool reached;
                do
                {
                    row = ReadRows(call, names)[0]; reads++;
                    if (!Equals(row["read_ok"], true))
                        throw new CliFailure("read", Convert.ToString(row["read_error"], CultureInfo.InvariantCulture),
                            names[0] + ": " + row["read_error"], null, 1);
                    reached = WriteCommand.Agree(Convert.ToString(expected, CultureInfo.InvariantCulture), Convert.ToString(row["value"], CultureInfo.InvariantCulture));
                    if (reached || (DateTime.UtcNow - started).TotalSeconds + interval > within) break;
                    Thread.Sleep(TimeSpan.FromSeconds(interval));
                } while (true);
                var after = Math.Round((DateTime.UtcNow - started).TotalSeconds, 3);
                return new Dictionary<string, object> { { "name", names[0] }, { "value", row["value"] }, { "until", expected }, { "reached", reached }, { "after_s", after }, { "reads", reads } };
            }
            if (count == 1)
            {
                var rows = ReadRows(call, names);
                if (names.Count == 1 && !Equals(rows[0]["read_ok"], true))
                    throw new CliFailure("read", "Read variable error: " + rows[0]["read_error"], "Read variable error: " + rows[0]["read_error"], null, 1);
                if (names.Count == 1 && rows.Count > 1) return new Dictionary<string, object> { { "results", rows.Cast<object>().ToList() }, { "count", rows.Count } };
                if (names.Count == 1) return new Dictionary<string, object> { { "name", names[0] }, { "value", rows[0]["value"] } };
                return new Dictionary<string, object> { { "results", rows.Cast<object>().ToList() }, { "count", rows.Count } };
            }
            var samples = new List<object>(); var begin = DateTime.UtcNow;
            var cancelled = false;
            ConsoleCancelEventHandler cancel = (sender, args) => { args.Cancel = true; cancelled = true; };
            Console.CancelKeyPress += cancel;
            try
            {
                for (var i = 0; i < count && !cancelled; i++)
                {
                    var due = begin.AddSeconds(i * interval); var delay = due - DateTime.UtcNow;
                    if (delay > TimeSpan.Zero) Thread.Sleep(delay);
                    if (cancelled) break;
                    var rows = ReadRows(call, names);
                    if (cancelled) break;
                    samples.Add(new Dictionary<string, object> { { "t", Math.Round((DateTime.UtcNow - begin).TotalSeconds, 3) }, { "results", rows.Cast<object>().ToList() } });
                }
            }
            finally { Console.CancelKeyPress -= cancel; }
            return new Dictionary<string, object> { { "samples", samples }, { "count", samples.Count }, { "interval", interval } };
        }

        static List<IDictionary<string, object>> ReadRows(CliCall call, IList<string> names)
        {
            var answer = call.Call("vars.read", new Dictionary<string, object> { { "names", names.Cast<object>().ToList() } });
            if (!Equals(Value(answer, "logged_in"), true)) throw new CliFailure("read", WriteCommand.NotConnected, WriteCommand.NotConnected, "cts connect", 1);
            var results = (Value(answer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
            var expanded = new List<string>();
            var owners = new Dictionary<string, DeclarationIndex>(StringComparer.OrdinalIgnoreCase);
            for (var i = 0; i < names.Count; i++)
                if (i < results.Count && Equals(Value(Value(results[i], "error") as IDictionary<string, object>, "code"), "not_scalar")) expanded.Add(names[i]);
            if (expanded.Count > 0)
            {
                var texts = call.Call("objects.texts", new Dictionary<string, object>());
                var textObjects = (Value(texts, "objects") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
                var index = new DeclarationIndex(textObjects.Select(obj => Convert.ToString(Value(obj, "declaration") ?? "", CultureInfo.InvariantCulture)));
                foreach (var obj in textObjects)
                {
                    var owner = Convert.ToString(Value(obj, "name") ?? "", CultureInfo.InvariantCulture);
                    if (owner.Length > 0 && index.Members.Count > 0) owners[owner] = index;
                }
                var leaves = new List<string>();
                var expandedByRoot = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
                foreach (var root in expanded)
                {
                    var dot = root.IndexOf('.');
                    var owner = dot > 0 && dot < root.Length - 1 && owners.TryGetValue(root.Substring(0, dot), out var found) ? found : null;
                    var type = owner?.TypeOf(root.Substring(dot + 1));
                    if (type == null) { expandedByRoot[root] = new List<string>(); continue; }
                    var rootLeaves = owner.Leaves(root, type).Take(Math.Max(0, 5000 - leaves.Count)).ToList();
                    expandedByRoot[root] = rootLeaves;
                    leaves.AddRange(rootLeaves);
                }
                if (leaves.Count > 0)
                {
                    leaves = leaves.Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(x => x, StringComparer.OrdinalIgnoreCase).ToList();
                    var expandedAnswer = call.Call("vars.read", new Dictionary<string, object> { { "names", leaves.Cast<object>().ToList() } });
                    if (!Equals(Value(expandedAnswer, "logged_in"), true)) throw new CliFailure("read", WriteCommand.NotConnected, WriteCommand.NotConnected, "cts connect", 1);
                    var leafResults = (Value(expandedAnswer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
                    var byPath = ToRows(leaves, leafResults).ToDictionary(row => Convert.ToString(row["name"]), StringComparer.OrdinalIgnoreCase);
                    var finalNames = new List<string>();
                    foreach (var name in names)
                    {
                        if (!expandedByRoot.TryGetValue(name, out var rootLeaves)) { finalNames.Add(name); continue; }
                        finalNames.AddRange(rootLeaves);
                    }
                    var direct = ToRows(names, results).ToDictionary(row => Convert.ToString(row["name"]), StringComparer.OrdinalIgnoreCase);
                    var output = new List<IDictionary<string, object>>();
                    foreach (var name in finalNames)
                        output.Add(byPath.TryGetValue(name, out var leaf) ? leaf : direct[name]);
                    return output;
                }
            }
            return WithSuggestions(call, ToRows(names, results));
        }

        // A name the PLC does not know gets the closest declared names from the sync
        // view: the GVL's globals, then each step's FB members along the path.
        static List<IDictionary<string, object>> WithSuggestions(CliCall call, List<IDictionary<string, object>> rows)
        {
            var folder = call.Hello.SyncFolder;
            if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(ViewFolder.Of(folder))) return rows;
            var files = Directory.GetFiles(ViewFolder.Of(folder), "*.st", SearchOption.AllDirectories);
            foreach (var row in rows.Where(row => Equals(row["read_ok"], false)
                && Convert.ToString(row["read_error"], CultureInfo.InvariantCulture).StartsWith("Invalid expression:", StringComparison.Ordinal)))
            {
                var parts = Convert.ToString(row["name"], CultureInfo.InvariantCulture).Split('.');
                var gvl = files.FirstOrDefault(path => Path.GetFileNameWithoutExtension(path).Equals(parts[0], StringComparison.OrdinalIgnoreCase));
                if (parts.Length < 2 || gvl == null) continue;
                var members = StDeclarations.VarBlocks(File.ReadAllText(gvl)).SelectMany(block => block.Members).ToList();
                for (var step = 1; step < parts.Length - 1 && members.Count > 0; step++)
                {
                    var type = members.FirstOrDefault(member => member.Name.Equals(parts[step], StringComparison.OrdinalIgnoreCase))?.Type;
                    var pou = type == null ? null : files.Select(File.ReadAllText).FirstOrDefault(text => StDeclarations.Header.Match(StText.Blank(text)) is var header
                        && header.Success && header.Groups["name"].Value.Equals(type, StringComparison.OrdinalIgnoreCase));
                    members = pou == null ? new List<VarMember>() : StDeclarations.VarBlocks(pou).SelectMany(block => block.Members).ToList();
                }
                var prefix = string.Join(".", parts.Take(parts.Length - 1)) + ".";
                var close = DevReflection.Closest(members.Select(member => member.Name), parts[parts.Length - 1]).Take(3).Select(name => prefix + name).ToList();
                if (close.Count > 0) row["read_error"] = Convert.ToString(row["read_error"], CultureInfo.InvariantCulture) + "\n  did you mean: " + string.Join(", ", close);
            }
            return rows;
        }

        static List<IDictionary<string, object>> ToRows(IList<string> names, IList<IDictionary<string, object>> results)
        {
            return names.Select((name, i) =>
            {
                var result = i < results.Count ? results[i] : new Dictionary<string, object>();
                var error = Value(result, "error") as IDictionary<string, object>;
                var code = Convert.ToString(Value(error, "code"), CultureInfo.InvariantCulture);
                var message = code == "not_exported"
                    ? "Invalid expression: '" + name + "' is not exported to the online application. It may be misspelled, not declared as a symbol, or not compiled into the PLC."
                    : Convert.ToString(Value(error, "message") ?? "read failed", CultureInfo.InvariantCulture);
                var ok = Equals(Value(result, "ok"), true);
                var value = Value(result, "text") ?? Value(result, "value");
                return (IDictionary<string, object>)new Dictionary<string, object>
                {
                    { "name", name }, { "value", ok && value != null ? Convert.ToString(value, CultureInfo.InvariantCulture) : "" },
                    { "read_ok", ok }, { "read_error", ok ? "" : message },
                };
            }).ToList();
        }

        // A compact declaration index: enough IEC syntax to follow aliases,
        // arrays and user-defined composites into online-readable scalar leaves.
        sealed class DeclarationIndex
        {
            static readonly Regex Comment = new Regex("(?s)(\\{[^}]*\\}|//[^\\r\\n]*|/\\*.*?\\*/)");
            static readonly Regex Array = new Regex("(?is)^ARRAY\\s*\\[(.*?)\\]\\s*OF\\s+(.+)$");
            static readonly Regex Range = new Regex("^\\s*(-?\\d+)\\s*\\.\\.\\s*(-?\\d+)\\s*$");
            static readonly HashSet<string> Scalars = new HashSet<string>(new[] { "BOOL", "BIT", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "USINT", "INT", "UINT", "DINT", "UDINT", "LINT", "ULINT", "REAL", "LREAL", "TIME", "LTIME", "TIME_OF_DAY", "TOD", "DATE", "DATE_AND_TIME", "DT", "LTIME_OF_DAY", "LTOD", "LDATE", "LDATE_AND_TIME", "LDT", "STRING", "WSTRING", "CHAR", "WCHAR", "POINTER", "REFERENCE" }, StringComparer.OrdinalIgnoreCase);
            public readonly Dictionary<string, string> Members = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            readonly Dictionary<string, List<KeyValuePair<string, string>>> _types = new Dictionary<string, List<KeyValuePair<string, string>>>(StringComparer.OrdinalIgnoreCase);
            readonly Dictionary<string, int> _constants = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            // *declarations*: one text per IDE object, so a function block's
            // variables are read from its own declaration only.
            public DeclarationIndex(IEnumerable<string> declarations)
            {
                var own = declarations.Select(d => Comment.Replace(d ?? "", " ")).ToList();
                var text = string.Join("\n", own);
                foreach (Match type in Regex.Matches(text, "(?is)\\bTYPE\\s+([A-Za-z_]\\w*)\\s*:\\s*(.*?)\\bEND_TYPE\\b"))
                {
                    var name = type.Groups[1].Value; var body = type.Groups[2].Value;
                    var fields = new List<KeyValuePair<string, string>>();
                    var structure = Regex.Match(body, "(?is)\\b(?:STRUCT|UNION)\\b(.*?)\\bEND_(?:STRUCT|UNION)\\b");
                    if (structure.Success) fields.AddRange(ParseMembers(structure.Groups[1].Value));
                    else if (body.TrimStart().StartsWith("(", StringComparison.Ordinal)) _types[name] = fields; // enum is a readable leaf
                    else
                    {
                        var alias = body.Trim().TrimEnd(';');
                        _types[name] = new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", alias) };
                        continue;
                    }
                    _types[name] = fields;
                }
                foreach (Match block in Regex.Matches(text, "(?is)\\b(VAR(?:_GLOBAL|_INPUT|_OUTPUT|_IN_OUT|_TEMP|_STAT|_EXTERNAL|_INST)?)\\b(.*?)\\bEND_VAR\\b"))
                    if (block.Groups[1].Value.Equals("VAR", StringComparison.OrdinalIgnoreCase) || block.Groups[1].Value.Equals("VAR_GLOBAL", StringComparison.OrdinalIgnoreCase))
                        foreach (var member in ParseMembers(block.Groups[2].Value)) Members[member.Key] = member.Value;
                foreach (var declaration in own)
                {
                    var fb = Regex.Match(declaration, "(?is)\\bFUNCTION_BLOCK\\s+([A-Za-z_]\\w*)(.*)");
                    if (fb.Success) _types[fb.Groups[1].Value] = Regex.Matches(fb.Groups[2].Value, "(?is)\\bVAR(?:_INPUT|_OUTPUT)?\\b(.*?)\\bEND_VAR\\b").Cast<Match>().SelectMany(x => ParseMembers(x.Groups[1].Value)).ToList();
                }
                foreach (Match block in Regex.Matches(text, "(?is)\\bVAR_GLOBAL\\b(.*?)\\bEND_VAR\\b"))
                    foreach (Match constant in Regex.Matches(block.Groups[1].Value, "(?i)\\b([A-Za-z_]\\w*)\\s*:\\s*[^;:=]+\\s*:=\\s*(-?\\d+)\\s*;"))
                        if (int.TryParse(constant.Groups[2].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)) _constants[constant.Groups[1].Value] = parsed;
            }
            static IEnumerable<KeyValuePair<string, string>> ParseMembers(string body)
            {
                foreach (var statement in body.Split(';'))
                {
                    var match = Regex.Match(statement, "(?s)^\\s*([A-Za-z_]\\w*(?:\\s*,\\s*[A-Za-z_]\\w*)*)\\s*:\\s*(.*?)(?:\\s*:=.*)?$");
                    if (!match.Success) continue;
                    var type = match.Groups[2].Value.Trim();
                    foreach (var name in match.Groups[1].Value.Split(',').Select(x => x.Trim())) yield return new KeyValuePair<string, string>(name, type);
                }
            }
            // The declared type at *path* below an owner ("fb.arr[2].field"):
            // each step a member, a structure's or a function block's field,
            // or an array's element; null where the declarations do not say.
            public string TypeOf(string path)
            {
                string type = null;
                foreach (var step in Steps(path))
                {
                    var part = Regex.Match(step, "^\\s*([A-Za-z_]\\w*)\\s*((?:\\[[^\\]]*\\]\\s*)*)$");
                    if (!part.Success) return null;
                    var name = part.Groups[1].Value;
                    type = type == null ? (Members.TryGetValue(name, out var member) ? member : null) : Field(type, name, 0);
                    foreach (Match index in Regex.Matches(part.Groups[2].Value, "\\["))
                    {
                        var array = type == null ? null : Array.Match(type.Trim());
                        type = array != null && array.Success ? array.Groups[2].Value.Trim() : null;
                    }
                    if (type == null) return null;
                }
                return type;
            }

            // *path* split at the dots outside brackets ("a[GVL.N].b": a[GVL.N], b).
            static IEnumerable<string> Steps(string path)
            {
                var depth = 0; var start = 0;
                for (var i = 0; i < path.Length; i++)
                {
                    if (path[i] == '[') depth++;
                    else if (path[i] == ']') depth--;
                    else if (path[i] == '.' && depth == 0) { yield return path.Substring(start, i - start); start = i + 1; }
                }
                yield return path.Substring(start);
            }

            // The type of *name* in *type*, through aliases.
            string Field(string type, string name, int depth)
            {
                if (depth > 8 || !_types.TryGetValue(type.Trim(), out var fields)) return null;
                foreach (var field in fields)
                {
                    if (field.Key.Length == 0) return Field(field.Value, name, depth + 1);
                    if (field.Key.Equals(name, StringComparison.OrdinalIgnoreCase)) return field.Value;
                }
                return null;
            }

            static bool IsScalar(string type) => Scalars.Contains(type) || Regex.IsMatch(type, "(?i)^W?STRING\\s*(?:\\(.*\\)|\\[.*\\])$");

            public IEnumerable<string> Leaves(string path, string type, int depth = 0)
            {
                if (depth > 8) yield break;
                var array = Array.Match(type.Trim());
                if (array.Success)
                {
                    var bounds = array.Groups[1].Value.Split(',').Select(x => BoundMatch(x)).ToArray();
                    if (bounds.Any(x => !x.Success)) yield break;
                    foreach (var suffix in Indices(bounds, 0, new List<int>()))
                        foreach (var leaf in Leaves(path + "[" + suffix + "]", array.Groups[2].Value.Trim(), depth + 1)) yield return leaf;
                    yield break;
                }
                var simple = Regex.Match(type.Trim(), "(?i)^(?:POINTER|REFERENCE)\\s+TO\\s+(.+)$");
                if (simple.Success) { yield return path; yield break; }
                if (IsScalar(type.Trim())) { yield return path; yield break; }
                if (!_types.TryGetValue(type.Trim(), out var fields)) yield break;
                if (fields.Count == 0) { yield return path; yield break; }
                foreach (var field in fields)
                {
                    if (field.Key.Length == 0) foreach (var leaf in Leaves(path, field.Value, depth + 1)) yield return leaf;
                    else foreach (var leaf in Leaves(path + "." + field.Key, field.Value, depth + 1)) yield return leaf;
                }
            }

            public IEnumerable<KeyValuePair<string, string>> VariableLeaves(IEnumerable<IDictionary<string, object>> objects)
            {
                foreach (var obj in objects)
                {
                    var declaration = Convert.ToString(Value(obj, "declaration") ?? "", CultureInfo.InvariantCulture);
                    var owner = Convert.ToString(Value(obj, "name") ?? "", CultureInfo.InvariantCulture);
                    if (owner.Length == 0) continue;
                    var isProgram = Regex.IsMatch(declaration, "(?im)^\\s*PROGRAM\\s+");
                    if (isProgram)
                    {
                        var program = Regex.Match(declaration, "(?im)^\\s*PROGRAM\\s+([A-Za-z_]\\w*)");
                        if (program.Success) owner = program.Groups[1].Value;
                    }
                    foreach (Match block in Regex.Matches(Comment.Replace(declaration, " "), "(?is)\\b(VAR_GLOBAL|VAR)\\b(.*?)\\bEND_VAR\\b"))
                    {
                        if (block.Groups[1].Value.Equals("VAR", StringComparison.OrdinalIgnoreCase) && !isProgram) continue;
                        foreach (var member in ParseMembers(block.Groups[2].Value))
                            foreach (var path in TypedLeaves(owner + "." + member.Key, member.Value))
                                yield return path;
                    }
                }
            }

            IEnumerable<KeyValuePair<string, string>> TypedLeaves(string path, string type, int depth = 0)
            {
                if (depth > 8) yield break;
                var array = Array.Match(type.Trim());
                if (array.Success)
                {
                    var bounds = array.Groups[1].Value.Split(',').Select(BoundMatch).ToArray();
                    if (bounds.Any(x => !x.Success)) yield break;
                    foreach (var suffix in Indices(bounds, 0, new List<int>()))
                        foreach (var leaf in TypedLeaves(path + "[" + suffix + "]", array.Groups[2].Value.Trim(), depth + 1)) yield return leaf;
                    yield break;
                }
                if (IsScalar(type.Trim()) || Regex.IsMatch(type.Trim(), "(?i)^(?:POINTER|REFERENCE)\\s+TO\\s+"))
                { yield return new KeyValuePair<string, string>(path, type.Trim()); yield break; }
                if (!_types.TryGetValue(type.Trim(), out var fields) || fields.Count == 0)
                { if (_types.ContainsKey(type.Trim())) yield return new KeyValuePair<string, string>(path, type.Trim()); yield break; }
                foreach (var field in fields)
                    foreach (var leaf in TypedLeaves(path + (field.Key.Length == 0 ? "" : "." + field.Key), field.Value, depth + 1)) yield return leaf;
            }
            Match BoundMatch(string text)
            {
                var normalized = Regex.Replace(text, "(?i)\\b[A-Za-z_]\\w*\\.([A-Za-z_]\\w*)\\b", "$1");
                normalized = Regex.Replace(normalized, "[A-Za-z_]\\w*", match => _constants.TryGetValue(match.Value, out var value) ? value.ToString(CultureInfo.InvariantCulture) : match.Value);
                return Range.Match(normalized);
            }
            IEnumerable<string> Indices(Match[] ranges, int dimension, List<int> current)
            {
                if (dimension == ranges.Length) { yield return string.Join(",", current); yield break; }
                var low = int.Parse(ranges[dimension].Groups[1].Value, CultureInfo.InvariantCulture); var high = int.Parse(ranges[dimension].Groups[2].Value, CultureInfo.InvariantCulture);
                if (high < low || high - low > 5000) yield break;
                for (var i = low; i <= high; i++)
                {
                    current.Add(i); foreach (var item in Indices(ranges, dimension + 1, current)) yield return item; current.RemoveAt(current.Count - 1);
                }
            }
        }

        static Answer Build(IDictionary<string, object> data)
        {
            if (data.ContainsKey("reached"))
            {
                var reached = Equals(Value(data, "reached"), true);
                var answer = new Answer().Add("reached", reached).Add("value", Value(data, "value"))
                    .Add("name", Value(data, "name")).Add("until", Value(data, "until")).Add("after_s", Value(data, "after_s")).Add("reads", Value(data, "reads"));
                return reached ? answer : answer.Partial().WithExitCode(2);
            }
            if (data.ContainsKey("value") && !data.ContainsKey("results")) return new Answer().Add("value", data["value"]);
            if (data.ContainsKey("samples"))
            {
                var samples = ((IEnumerable<object>)data["samples"]).OfType<IDictionary<string, object>>().ToList();
                var details = new List<string>(); var last = new Dictionary<string, object>(); var changes = 0; var failed = 0;
                for (var i = 0; i < samples.Count; i++)
                {
                    var moved = new List<string>();
                    foreach (var row in ((IEnumerable<object>)samples[i]["results"]).OfType<IDictionary<string, object>>())
                    {
                        var ok = Equals(Value(row, "read_ok"), true); var shown = ok ? Value(row, "value") : "?(" + Value(row, "read_error") + ")";
                        if (!ok) failed++;
                        var name = Convert.ToString(row["name"]);
                        if (i == 0 || !last.TryGetValue(name, out var old) || !Equals(old, shown)) moved.Add(name + "=" + shown);
                        last[name] = shown;
                    }
                    if (moved.Count > 0) { if (i > 0) changes++; details.Add("+" + Convert.ToDouble(samples[i]["t"], CultureInfo.InvariantCulture).ToString("0.0", CultureInfo.InvariantCulture) + "s " + string.Join(" ", moved)); }
                }
                var sampled = new Answer().Add("samples", samples.Count).Add("changes", changes).Add("failed", failed);
                foreach (var detail in details) sampled.Detail(detail);
                return failed > 0 ? sampled.Partial() : sampled;
            }
            var rows = ((IEnumerable<object>)data["results"]).OfType<IDictionary<string, object>>().ToList();
            var failures = rows.Count(r => !Equals(Value(r, "read_ok"), true));
            var answerRows = new Answer().Add("count", rows.Count).Add("failed", failures);
            foreach (var row in rows) answerRows.Detail(Equals(Value(row, "read_ok"), true) ? row["name"] + " = " + row["value"] : row["name"] + ": " + row["read_error"]);
            return failures == 0 ? answerRows : answerRows.Partial();
        }

        static CliFailure Usage(string message) => new CliFailure("read", "usage", message, "cts read --help", 2);
    }
}
