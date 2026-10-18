using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Visu;

namespace Cts.Cli
{
    internal static partial class VisuSketchCommands
    {
        static IDictionary<string, object> Lint(string path, string source, Sketch sketch, CliOptions options)
        {
            var findings = SketchLinter.Find(sketch);
            var fixedCount = 0;
            if (Has(options, "fix"))
            {
                for (var pass = 0; pass < FixPasses; pass++)
                {
                    var edits = SketchLinter.Find(sketch)
                                    .Where(finding => finding.Fixes.Count > 0)
                                    .GroupBy(finding => finding.Index)
                                    .OrderByDescending(group => group.Key)
                                    .ToList();
                    if (edits.Count == 0) break;
                    var tags = SketchEditor.SourceTags(source);
                    foreach (var group in edits)
                    {
                        var index = group.Key;
                        if (index >= tags.Count) continue;
                        var tag = tags[index];
                        var updated = tag.Value;
                        foreach (var finding in group)
                            foreach (var fix in finding.Fixes)
                                updated = SketchEditor.SetAttribute(updated, fix.Key, fix.Value);
                        source = source.Substring(0, tag.Index) + updated + source.Substring(tag.Index + tag.Length);
                        fixedCount += group.Sum(finding => finding.Fixes.Count);
                        try
                        {
                            sketch = Sketch.Parse(source, options.Text("sync_folder"), options.Text("background"), options.Text("scheme"),
                                                  options.Text("theme"));
                        }
                        catch
                        {
                            break;
                        }
                    }
                    File.WriteAllText(path, source, new System.Text.UTF8Encoding(false));
                }
                findings = SketchLinter.Find(sketch);
            }
            var fatal = findings.Count(finding => finding.Severity == "error");
            var strict = Has(options, "strict") && findings.Count > 0;
            var stillFixable = findings.Any(finding => finding.Fixes.Count > 0);
            if (options.Output == "json")
            {
                var jsonFindings = findings
                                       .Select(finding => (object) new Dictionary<string, object> {
                                           ["rule_id"] = finding.Rule,
                                           ["severity"] = finding.Severity,
                                           ["message"] = finding.Message,
                                           ["location"] = new Dictionary<string, object> { ["path"] = path },
                                           ["index"] = finding.Index,
                                       })
                                       .ToList();
                var payload = new Dictionary<string, object> { ["schema_version"] = 1, ["ok"] = fatal == 0 && !strict, ["findings"] = jsonFindings };
                return new Dictionary<string, object> { ["raw_body"] = Cts.Agent.Json.Serialize(payload),
                                                        ["exit_code"] = fatal > 0 || strict ? 1 : 0 };
            }
            return new Dictionary<string, object> { ["path"] = path,
                                                    ["findings"] = findings.Cast<object>().ToList(),
                                                    ["fixed"] = fixedCount,
                                                    ["errors"] = fatal,
                                                    ["strict"] = strict,
                                                    ["fix_requested"] = Has(options, "fix"),
                                                    ["still_fixable"] = stillFixable };
        }
    }
}
