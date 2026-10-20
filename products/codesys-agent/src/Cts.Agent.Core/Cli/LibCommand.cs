using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Cts.Analysis;

namespace Cts.Cli
{
    // `cts lib`: the library references of the Library Managers in the sync
    // folder, and edits to them on disk; cts import then loads them in the IDE.
    // The file is edited line by line, so the rest stays as cts export wrote it.
    internal static class LibCommand
    {
        const string ManagerType = "adb5cb65-8e1d-4a00-b70a-375ea27582f3";
        const string PlaceholderItem = "4723ebe7-5bfc-43c6-be6b-5097002ef6b4";
        const string ConcreteItem = "51a11660-6c0d-4598-8c08-419c5845ea1f";
        // The resolver CODESYS gives a placeholder the Library Manager adds (CAA Net Base Services' CAA NetBaseSrv).
        const string PlaceholderResolver = "b303f5ce-75ff-4668-a777-7da8debb449c";
        const string ImportNext = "cts import";
        static readonly Regex Resolution = new Regex(@"^\s*[^,]+?,\s*(\*|[0-9][0-9.]*)\s*\([^()]+\)\s*$");
        static readonly Regex Identifier = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*$");

        static readonly CliOption[] Where =
        {
            CliOption.Text("--workspace", "workspace", "DIR", "The sync folder (default: the one around the current folder)"),
            CliOption.Text("--app", "app", "NAME", "Only the Library Manager of this application (its folder's name)"),
        };

        internal static IEnumerable<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "lib", Summary = "List the libraries the project references (offline)",
                Description = "Reads each Library Manager.xml of the sync folder: one line per reference with its namespace, the library "
                    + "(name, version, vendor), the placeholder it goes through and qualified-only when its names need the namespace in "
                    + "front (Standard.TON). cts lib set, add and remove change the files; cts import then loads them in the IDE.",
                Options = Where, LocalExecute = List, Build = BuildList,
            },
            new CliCommand
            {
                Name = "lib", Sub = "set", Summary = "Change a library reference's qualified-only flag on disk",
                Description = "NAME is the library's name, its placeholder or its namespace; every Library Manager that references it "
                    + "changes unless --app picks one. --qualified-only off lets the project use the library's names without the "
                    + "namespace (TON), on requires it (Standard.TON). cts import then carries the change into the IDE.",
                Arguments = "NAME", ArgumentLimit = 1, ArgumentHelp = "Library name, placeholder or namespace",
                Options = Where.Concat(new[] { CliOption.Choice("--qualified-only", "qualified_only", "Whether names need the namespace in front", "on", "off") }).ToArray(),
                LocalExecute = Set, Build = Edited,
            },
            new CliCommand
            {
                Name = "lib", Sub = "add", Summary = "Reference a library on disk",
                Description = "Adds \"Name, Version (Vendor)\" (version * for the newest installed) to the application's Library Manager "
                    + "as a direct reference, or through --placeholder, which lets the device pick the version (CAA Net Base Services "
                    + "goes through CAA NetBaseSrv); --namespace is the prefix its names take (the library's documentation names it, cts docs "
                    + "--show). With several applications --app picks one; a project with none (a new library) gets one at its root. cts import "
                    + "then loads the library; it names one that does not load.",
                Arguments = "LIBRARY", ArgumentLimit = 1, ArgumentHelp = "\"Name, Version (Vendor)\", e.g. \"CAA Net Base Services, * (CAA Technical Workgroup)\"",
                Options = Where.Concat(new[]
                {
                    CliOption.Needed("--namespace", "namespace", "NS", "The namespace its names take, e.g. NBS"),
                    CliOption.Switch("--qualified-only", "qualified_only", "Its names need the namespace in front"),
                    CliOption.Text("--placeholder", "placeholder", "NAME", "Reference it through this placeholder; the library is its default resolution"),
                }).ToArray(),
                LocalExecute = Add, Build = Edited,
            },
            new CliCommand
            {
                Name = "lib", Sub = "remove", Summary = "Drop a library reference on disk",
                Description = "NAME is the library's name, its placeholder or its namespace; every Library Manager that references it "
                    + "drops it unless --app picks one. cts import then removes it in the IDE; cts build names what still uses it.",
                Arguments = "NAME", ArgumentLimit = 1, ArgumentHelp = "Library name, placeholder or namespace",
                Options = Where, LocalExecute = Remove, Build = Edited,
            },
        };

        sealed class Item
        {
            internal int Start, End, QualifiedLine = -1;
            internal string Kind, Placeholder = "", Library = "", Namespace = "";
            internal bool QualifiedOnly;

            internal string Name => Library.Split(',')[0].Trim();

            internal bool Matches(string name) => new[] { Name, Placeholder, Namespace }.Any(key => key.Length > 0 && key.Equals(name.Trim(), StringComparison.OrdinalIgnoreCase));

            internal string Line() => (Namespace.Length > 0 ? Namespace : "-") + "  " + Library + (Kind == "placeholder" ? "  placeholder " + Placeholder : "")
                + (QualifiedOnly ? "  qualified-only" : "");
        }

        sealed class Manager
        {
            internal string File, Relative, App;
            internal bool Bom;
            internal List<string> Lines;
            internal List<Item> Items = new List<Item>();
            internal int ListEnd = -1;

            internal void Save()
            {
                System.IO.File.WriteAllText(File, string.Join("\n", Lines), new UTF8Encoding(Bom));
            }
        }

        // With *create*, a project with no Library Manager gets one at its
        // root (POUs/, where export writes it), with no references yet.
        static List<Manager> Managers(CliOptions options, string work, string verb, bool create = false)
        {
            AnalyzeWorkspace workspace;
            try { workspace = AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work); }
            catch (AnalyzeException error) { throw new CliFailure(verb, "refused", error.Message, "cts " + verb.Replace('-', ' ') + " --help", 2); }
            var managers = Directory.GetFiles(workspace.View, "Library Manager.xml", SearchOption.AllDirectories)
                .OrderBy(file => file, StringComparer.OrdinalIgnoreCase).Select(file => Read(file, workspace.View)).Where(manager => manager != null).ToList();
            var app = options.Text("app");
            if (app != null)
            {
                var picked = managers.Where(manager => manager.App.Equals(app, StringComparison.OrdinalIgnoreCase)).ToList();
                if (picked.Count == 0)
                    throw new CliFailure(verb, "no such application", "no Library Manager belongs to " + app + "; the managers are in: " + string.Join(", ", managers.Select(manager => manager.App)), "cts lib", 1);
                return picked;
            }
            if (managers.Count == 0 && create)
            {
                var file = Path.Combine(workspace.View, "POUs", "Library Manager.xml");
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                File.WriteAllText(file, EmptyManager.Replace("{guid}", Guid.NewGuid().ToString("D")).Replace("\r\n", "\n"), new UTF8Encoding(false));
                managers.Add(Read(file, workspace.View));
            }
            if (managers.Count == 0)
                throw new CliFailure(verb, "no Library Manager", "the project has no Library Manager: cts lib add creates one with its first reference", "cts lib add --help", 1);
            return managers;
        }

        static Manager Read(string file, string view)
        {
            var bytes = File.ReadAllBytes(file);
            var bom = bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF;
            var text = new UTF8Encoding(false).GetString(bytes, bom ? 3 : 0, bytes.Length - (bom ? 3 : 0));
            XDocument doc;
            try { doc = XDocument.Parse(text, LoadOptions.SetLineInfo | LoadOptions.PreserveWhitespace); }
            catch (XmlException) { return null; }
            var list = doc.Descendants("List").FirstOrDefault(element => (string)element.Attribute("Name") == "Items"
                && ((string)element.Parent?.Attribute("Type") ?? "").Trim('{', '}').Equals(ManagerType, StringComparison.OrdinalIgnoreCase));
            if (list == null) return null;
            var relative = ExportCommand.Relative(view, file);
            var manager = new Manager
            {
                File = file, Relative = relative, Bom = bom, Lines = text.Split('\n').ToList(),
                App = Path.GetFileName(Path.GetDirectoryName(file)),
            };
            foreach (var element in list.Elements("Single"))
            {
                var kind = ((string)element.Attribute("Type") ?? "").Trim('{', '}').ToLowerInvariant();
                var item = new Item { Kind = kind == PlaceholderItem ? "placeholder" : kind == ConcreteItem ? "library" : "other" };
                item.Start = ((IXmlLineInfo)element).LineNumber - 1;
                item.End = Closing(manager.Lines, item.Start, "</Single>");
                foreach (var field in element.Elements())
                {
                    var value = field.Value.Trim();
                    switch ((string)field.Attribute("Name"))
                    {
                        case "PlaceholderName": item.Placeholder = value; break;
                        case "DefaultResolution":
                        case "Name": item.Library = value; break;
                        case "Namespace": item.Namespace = value; break;
                        case "QualifiedOnly":
                            item.QualifiedOnly = value == "True";
                            item.QualifiedLine = ((IXmlLineInfo)field).LineNumber - 1;
                            break;
                    }
                }
                if (item.End >= 0) manager.Items.Add(item);
            }
            if (!list.IsEmpty) manager.ListEnd = Closing(manager.Lines, ((IXmlLineInfo)list).LineNumber - 1, "</List>");
            return manager;
        }

        // The line that closes the element starting on line *start*: the
        // export indents the closing tag as the opening one.
        static int Closing(List<string> lines, int start, string tag)
        {
            var indent = Indent(lines[start]);
            for (var i = start + 1; i < lines.Count; i++)
                if (lines[i].TrimEnd('\r') == indent + tag) return i;
            return -1;
        }

        static string Indent(string line) => line.Substring(0, line.Length - line.TrimStart(' ', '\t').Length);

        static IDictionary<string, object> List(CliOptions options, IAgentHost host, string work)
        {
            var managers = Managers(options, work, "lib");
            return new Dictionary<string, object>
            {
                ["managers"] = managers.Select(manager => (object)new Dictionary<string, object>
                {
                    ["file"] = manager.Relative,
                    ["libraries"] = manager.Items.Select(item => (object)new Dictionary<string, object>
                    {
                        ["kind"] = item.Kind, ["library"] = item.Library, ["placeholder"] = item.Placeholder, ["namespace"] = item.Namespace,
                        ["qualified_only"] = item.QualifiedOnly, ["line"] = item.Line(),
                    }).ToList(),
                }).ToList(),
            };
        }

        static Answer BuildList(IDictionary<string, object> data)
        {
            var managers = ((IList<object>)data["managers"]).Cast<IDictionary<string, object>>().ToList();
            var answer = new Answer().Add("managers", managers.Count)
                .Add("libraries", managers.Sum(manager => ((IList<object>)manager["libraries"]).Count)).Whole();
            foreach (var manager in managers)
            {
                answer.Detail(manager["file"] + ":");
                foreach (IDictionary<string, object> item in (IList<object>)manager["libraries"]) answer.Detail("  " + item["line"]);
            }
            return answer;
        }

        static IDictionary<string, object> Set(CliOptions options, IAgentHost host, string work)
        {
            var name = Argument(options, "lib-set", "NAME");
            if (options.Text("qualified_only") == null) throw new CliFailure("lib-set", "usage", "nothing to set: pass --qualified-only on|off", "cts lib set --help", 2);
            var on = options.Text("qualified_only") == "on";
            var changed = new List<object>();
            var found = false;
            foreach (var manager in Managers(options, work, "lib-set"))
            {
                var edited = false;
                foreach (var item in manager.Items.Where(item => item.Matches(name)))
                {
                    found = true;
                    if (item.QualifiedOnly == on || item.QualifiedLine < 0) continue;
                    var line = manager.Lines[item.QualifiedLine];
                    manager.Lines[item.QualifiedLine] = line.Replace(on ? ">False<" : ">True<", on ? ">True<" : ">False<");
                    changed.Add(manager.Relative + ": " + item.Library);
                    edited = true;
                }
                if (edited) manager.Save();
            }
            if (!found) throw NotReferenced("lib-set", name);
            return new Dictionary<string, object> { ["changed"] = changed };
        }

        static IDictionary<string, object> Add(CliOptions options, IAgentHost host, string work)
        {
            var library = Argument(options, "lib-add", "LIBRARY").Trim();
            if (!Resolution.IsMatch(library))
                throw new CliFailure("lib-add", "usage", "LIBRARY is \"Name, Version (Vendor)\", e.g. \"CAA Net Base Services, * (CAA Technical Workgroup)\"", "cts lib add --help", 2);
            var ns = options.Text("namespace").Trim();
            if (!Identifier.IsMatch(ns)) throw new CliFailure("lib-add", "usage", "--namespace is an identifier, e.g. NBS", "cts lib add --help", 2);
            var managers = Managers(options, work, "lib-add", true);
            if (managers.Count > 1)
                throw new CliFailure("lib-add", "several Library Managers", "several Library Managers: pick one with --app (" + string.Join(", ", managers.Select(manager => manager.App)) + ")", "cts lib", 1);
            var target = managers[0];
            var name = library.Split(',')[0].Trim();
            var placeholder = options.Text("placeholder")?.Trim();
            if (placeholder?.Length == 0) throw new CliFailure("lib-add", "usage", "--placeholder names the placeholder, e.g. \"CAA NetBaseSrv\"", "cts lib add --help", 2);
            var already = target.Items.FirstOrDefault(item => item.Name.Equals(name, StringComparison.OrdinalIgnoreCase) || item.Namespace.Equals(ns, StringComparison.OrdinalIgnoreCase)
                || placeholder != null && item.Matches(placeholder));
            if (already != null)
                throw new CliFailure("lib-add", "already referenced", target.Relative + " already references " + already.Line() + ": cts lib set changes it, cts lib remove drops it", "cts lib", 1);
            if (target.ListEnd < 0) throw new CliFailure("lib-add", "no list of references", target.Relative + " has no list of references to add to", "cts lib", 1);
            var sample = target.Items.FirstOrDefault();
            var indent = sample != null ? Indent(target.Lines[sample.Start]) : Indent(target.Lines[target.ListEnd]) + "  ";
            var step = sample != null && sample.End > sample.Start + 1 ? Indent(target.Lines[sample.Start + 1]).Substring(indent.Length) : "  ";
            var cr = target.Lines[target.ListEnd].EndsWith("\r", StringComparison.Ordinal) ? "\r" : "";
            var inner = indent + step;
            var head = placeholder == null ? new[]
            {
                indent + "<Single Type=\"{" + ConcreteItem + "}\" Method=\"IArchivable\">",
                inner + "<Single Name=\"Optional\" Type=\"bool\">False</Single>",
                inner + "<Null Name=\"Params\" />",
                inner + "<Single Name=\"Name\" Type=\"string\">" + Escaped(library) + "</Single>",
            } : new[]
            {
                indent + "<Single Type=\"{" + PlaceholderItem + "}\" Method=\"IArchivable\">",
                inner + "<Single Name=\"DefaultResolution\" Type=\"string\">" + Escaped(library) + "</Single>",
                inner + "<Single Name=\"Optional\" Type=\"bool\">False</Single>",
                inner + "<Null Name=\"Params\" />",
                inner + "<Single Name=\"PlaceholderName\" Type=\"string\">" + Escaped(placeholder) + "</Single>",
                inner + "<Single Name=\"ResolverGuid\" Type=\"System.Guid\">" + PlaceholderResolver + "</Single>",
            };
            var block = head.Concat(new[]
            {
                inner + "<Single Name=\"Id\" Type=\"long\">" + NewId(target) + "</Single>",
                inner + "<Single Name=\"Namespace\" Type=\"string\">" + ns + "</Single>",
                inner + "<Single Name=\"SystemLibrary\" Type=\"bool\">False</Single>",
                inner + "<Single Name=\"HideWhenReferencedAsDependency\" Type=\"bool\">False</Single>",
                inner + "<Single Name=\"PublishSymbolsInContainer\" Type=\"bool\">False</Single>",
                inner + "<Single Name=\"QualifiedOnly\" Type=\"bool\">" + (options.Params.ContainsKey("qualified_only") ? "True" : "False") + "</Single>",
                inner + "<Single Name=\"LinkAllContent\" Type=\"bool\">False</Single>",
                indent + "</Single>",
            }).Select(line => line + cr);
            target.Lines.InsertRange(target.ListEnd, block);
            target.Save();
            return new Dictionary<string, object> { ["changed"] = new List<object> { target.Relative + ": " + library + (placeholder == null ? "" : " through placeholder " + placeholder) } };
        }

        static IDictionary<string, object> Remove(CliOptions options, IAgentHost host, string work)
        {
            var name = Argument(options, "lib-remove", "NAME");
            var changed = new List<object>();
            foreach (var manager in Managers(options, work, "lib-remove"))
            {
                var drop = manager.Items.Where(item => item.Matches(name)).OrderByDescending(item => item.Start).ToList();
                foreach (var item in drop)
                {
                    manager.Lines.RemoveRange(item.Start, item.End - item.Start + 1);
                    changed.Add(manager.Relative + ": " + item.Library);
                }
                if (drop.Count > 0) manager.Save();
            }
            if (changed.Count == 0) throw NotReferenced("lib-remove", name);
            return new Dictionary<string, object> { ["changed"] = changed };
        }

        static Answer Edited(IDictionary<string, object> data)
        {
            var changed = (IList<object>)data["changed"];
            var answer = new Answer().Add("changed", changed.Count);
            foreach (var line in changed) answer.Detail(line);
            answer.Detail(changed.Count == 0 ? "the files already say so; nothing changed" : "Next: " + ImportNext + " loads the change in the IDE");
            return answer;
        }

        static string Argument(CliOptions options, string verb, string metavar)
        {
            if (options.Arguments.Count == 0) throw new CliFailure(verb, "usage", metavar + " is required", "cts " + verb.Replace('-', ' ') + " --help", 2);
            return options.Arguments[0];
        }

        static CliFailure NotReferenced(string verb, string name) =>
            new CliFailure(verb, "not referenced", "no Library Manager references " + name + " by its name, placeholder or namespace", "cts lib", 1);

        // An Id no reference of *manager* has: CODESYS keys a reference by it.
        static long NewId(Manager manager)
        {
            var taken = new HashSet<string>(manager.Lines.Select(line => line.Trim()).Where(line => line.StartsWith("<Single Name=\"Id\"", StringComparison.Ordinal)));
            var random = new Random();
            while (true)
            {
                var id = (long)(uint)random.Next(1, int.MaxValue) * 2 + random.Next(0, 2);
                if (!taken.Contains("<Single Name=\"Id\" Type=\"long\">" + id + "</Single>")) return id;
            }
        }

        // A root Library Manager as export writes it, with no references.
        const string EmptyManager = @"<?xml version='1.0' encoding='utf-8'?>
<Single Type=""{6198ad31-4b98-445c-927f-3258a0e82fe3}"" Method=""IArchivable"">
      <Single Name=""IsRoot"" Type=""bool"">True</Single>
      <Single Name=""MetaObject"" Type=""{81297157-7ec9-45ce-845e-84cab2b88ade}"" Method=""IArchivable"">
        <Single Name=""Guid"" Type=""System.Guid"">{guid}</Single>
        <Single Name=""ParentGuid"" Type=""System.Guid"">00000000-0000-0000-0000-000000000000</Single>
        <Single Name=""Name"" Type=""string"">Library Manager</Single>
        <Dictionary Type=""{2c41fa04-1834-41c1-816e-303c7aa2c05b}"" Name=""Properties"">
        </Dictionary>
        <Single Name=""TypeGuid"" Type=""System.Guid"">" + ManagerType + @"</Single>
        <Null Name=""EmbeddedTypeGuids"" />
      </Single>
      <Single Name=""Object"" Type=""{" + ManagerType + @"}"" Method=""IArchivable"">
        <List2 Name=""ParameterTable"" />
        <List Name=""Items"" Type=""System.Collections.ArrayList"">
        </List>
        <Dictionary Type=""System.Collections.Hashtable"" Name=""PlaceholderRedirectionTable"">
        </Dictionary>
      </Single>
      <Single Name=""ParentSVNodeGuid"" Type=""System.Guid"">00000000-0000-0000-0000-000000000000</Single>
      <Array Name=""Path"" Type=""string"" />
      <Single Name=""Index"" Type=""int"">-1</Single>
    </Single>
";

        static string Escaped(string text) => text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;");
    }
}
