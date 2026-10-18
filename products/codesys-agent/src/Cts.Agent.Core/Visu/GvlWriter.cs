using System;
using Cts.Agent;
using Cts.Analysis;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using static Cts.Agent.JsonMap;

namespace Cts.Visu
{
    internal sealed class GvlResult
    {
        internal string Path;
        internal bool Written;
        internal IList<string> Warnings = new List<string>();
        internal bool HasVariables;
    }

    // Extract runtime references from SVG element specs and update a GVL without
    // rewriting declarations already present in the project.
    internal static class GvlWriter
    {
        static readonly Regex Dotted = new Regex(@"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b");
        static readonly Regex Declaration = new Regex(@"^\s+(\w+)\s*(?:AT\s+%[\w.*]+\s*)?:", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex Format = new Regex(@"%[-+ 0#]*[0-9]*(?:\.[0-9]+)?([diufFeEgGsxX])");

        internal static GvlResult Ensure(string projectView, IList<Sketch.Element> elements, string name, string explicitPath)
        {
            var result = new GvlResult();
            var variables = new SortedDictionary<string, string>(StringComparer.Ordinal);
            var types = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var element in elements)
            {
                var p = element.SpecParams;
                Record(p, "text_var", variables, types, InferType(Text(p, "text")));
                Record(p, "var", variables, types, element.Type == "combobox" ? "INT" : "BOOL");
                Record(p, "tap_var", variables, types, "BOOL");
                Record(p, "toggle_var", variables, types, "BOOL");
                Record(p, "color_var", variables, types, "BOOL");
                Record(p, "fill_var", variables, types, "DWORD");
                Record(p, "border_var", variables, types, "DWORD");
                foreach (var key in new[] { "input_actions", "configured_inputs", "configured_complex_inputs" })
                {
                    if (!p.TryGetValue(key, out var actions) || !(actions is IList<object> list)) continue;
                    foreach (var action in list.OfType<IDictionary<string, object>>())
                    {
                        var values = JsonMap.Value(action, "values") as IDictionary<string, object>;
                        if (values == null) continue;
                        RecordExpression(Text(values, "variable"), variables, types, "BOOL");
                        foreach (Match match in Dotted.Matches(Text(values, "snippet"))) RecordExpression(match.Value, variables, types, "BOOL");
                    }
                }
            }
            result.HasVariables = variables.Count > 0;
            if (!result.HasVariables) return result;
            var target = Target(projectView, name, explicitPath, result.Warnings);
            if (target == null) return result;
            result.Path = target;
            var project = ScanProject(projectView);
            var declare = new SortedDictionary<string, string>(StringComparer.Ordinal);
            foreach (var item in variables)
            {
                if (!item.Key.Contains(".")) declare[item.Key] = item.Value;
                else
                {
                    var parts = item.Key.Split('.');
                    var owner = parts[0];
                    var head = parts[1];
                    if (owner == name)
                    {
                        if (parts.Length > 2)
                            result.Warnings.Add(item.Key + " -- cannot synthesise nested member '" + string.Join(".", parts.Skip(1)) + "'; declare '" + head + "' in " + name + " yourself");
                        else declare[item.Key] = head;
                    }
                    else if (project.TryGetValue(owner, out var known))
                    {
                        if (!known.Contains(head))
                            result.Warnings.Add(item.Key + " -- GVL '" + owner + "' declares no '" + head + "' -- adding it to " + name + " would not satisfy this reference");
                    }
                    else declare[item.Key] = item.Value;
                }
            }
            var existingNames = File.Exists(target) ? Declarations(File.ReadAllText(target, Encoding.UTF8)) : new HashSet<string>(StringComparer.Ordinal);
            var used = new HashSet<string>(existingNames, StringComparer.Ordinal);
            var additions = new List<string>();
            foreach (var item in declare)
            {
                if (!used.Add(item.Value))
                {
                    if (!existingNames.Contains(item.Value))
                        result.Warnings.Add(item.Key + " -- identifier '" + item.Value + "' already declared for another path; two paths cannot share one declaration");
                    continue;
                }
                additions.Add("    " + item.Value + " : " + (types.TryGetValue(item.Key, out var type) ? type : "BOOL") + ";\n");
            }
            if (additions.Count == 0) return result;
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(target));
            if (File.Exists(target))
            {
                var current = File.ReadAllText(target, Encoding.UTF8);
                var end = current.LastIndexOf("END_VAR", StringComparison.Ordinal);
                current = end >= 0 ? current.Insert(end, "\n" + Block(additions)) : current + "\n" + NewFile(additions);
                File.WriteAllText(target, current, new UTF8Encoding(false));
            }
            else File.WriteAllText(target, NewFile(additions), new UTF8Encoding(false));
            result.Written = true;
            return result;
        }

        // An explicit file, else the project's GVL of that name wherever it lies, else a new
        // one in POUs; null when several GVLs carry the name.
        static string Target(string projectView, string name, string explicitPath, IList<string> warnings)
        {
            if (!string.IsNullOrWhiteSpace(explicitPath)) return System.IO.Path.GetFullPath(explicitPath);
            var existing = GvlFiles(projectView).Where(file => System.IO.Path.GetFileNameWithoutExtension(file) == name).ToList();
            if (existing.Count > 1)
            {
                warnings.Add(name + " -- " + existing.Count + " GVLs carry that name ("
                    + string.Join(", ", existing.Select(file => file.Substring(projectView.Length).TrimStart('\\', '/'))) + "); name one with --gvl-file");
                return null;
            }
            return existing.Count == 1 ? existing[0] : System.IO.Path.Combine(projectView, "POUs", name + ".st");
        }

        static IEnumerable<string> GvlFiles(string projectView)
        {
            if (!Directory.Exists(projectView)) return new string[0];
            return Directory.GetFiles(projectView, "*.st", SearchOption.AllDirectories)
                .Where(file => File.ReadAllText(file, Encoding.UTF8).Contains("VAR_GLOBAL"));
        }

        static string NewFile(IList<string> declarations) => "{attribute 'qualified_only'}\nVAR_GLOBAL\n" + Block(declarations) + "END_VAR\n";

        // The generated declarations as one table aligned as cts fmt does,
        // a blank line apart from the ones before it in an existing GVL.
        static string Block(IList<string> declarations)
        {
            const string open = "VAR_GLOBAL\n", close = "END_VAR";
            var text = StFormatter.Format(open + "    {attribute 'hide'}\n    // Auto-generated by cts visu from-svg --gvl\n" + string.Concat(declarations) + close, true);
            return text.Substring(open.Length, text.Length - open.Length - close.Length);
        }

        static void Record(IDictionary<string, object> parameters, string key, IDictionary<string, string> variables,
                           IDictionary<string, string> types, string type)
        {
            RecordExpression(Text(parameters, key), variables, types, type);
        }

        static void RecordExpression(string expression, IDictionary<string, string> variables, IDictionary<string, string> types, string type)
        {
            var value = (expression ?? "").Trim();
            if (!Regex.IsMatch(value, @"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")) return;
            variables[value] = Snapshot.LastSegment(value);
            if (!types.TryGetValue(value, out var prior) || prior == "BOOL") types[value] = type;
        }

        static string InferType(string format)
        {
            var match = Format.Match(format ?? "");
            if (!match.Success) return "BOOL";
            return "fFeEgG".IndexOf(match.Groups[1].Value, StringComparison.Ordinal) >= 0 ? "REAL"
                : "s".IndexOf(match.Groups[1].Value, StringComparison.OrdinalIgnoreCase) >= 0 ? "STRING" : "INT";
        }

        static Dictionary<string, HashSet<string>> ScanProject(string projectView)
        {
            var result = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var file in GvlFiles(projectView))
            {
                var text = File.ReadAllText(file, Encoding.UTF8);
                var name = System.IO.Path.GetFileNameWithoutExtension(file);
                if (!result.TryGetValue(name, out var values)) result[name] = values = new HashSet<string>(StringComparer.Ordinal);
                foreach (Match match in Declaration.Matches(text)) values.Add(match.Groups[1].Value);
            }
            return result;
        }

        static HashSet<string> Declarations(string text)
        {
            return new HashSet<string>(Declaration.Matches(text).Cast<Match>().Select(match => match.Groups[1].Value), StringComparer.Ordinal);
        }

    }
}
