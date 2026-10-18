using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Analysis
{
    // One region of a unit (implementation or declaration): Raw as written,
    // Text with comments, pragmas and string contents blanked. Blanking only
    // replaces characters, so a position in Text is the same in Raw, and
    // At() turns it into an offset in the unit's text.
    internal sealed class Section
    {
        internal readonly string Raw, Text;
        internal readonly int Base;

        internal Section(string raw, int offsetBase)
        {
            Raw = raw ?? "";
            Base = offsetBase;
            Text = StText.Blanked(Raw);
        }

        internal bool IsEmpty => Raw.Trim().Length == 0;

        internal int At(int local) => Base + local;

        // ';'-terminated statements of the blanked text, at unit offsets.
        internal IEnumerable<KeyValuePair<int, string>> Statements() => StText.Statements(Text, Base);

        // Each raw line: its 1-based number in the section, its unit offset.
        internal IEnumerable<Tuple<int, int, string>> Lines()
        {
            var lines = Raw.Split('\n').ToList();
            if (lines.Count > 0 && lines[lines.Count - 1].Length == 0) lines.RemoveAt(lines.Count - 1);
            var offset = 0;
            for (var i = 0; i < lines.Count; i++)
            {
                yield return Tuple.Create(i + 1, Base + offset, lines[i].TrimEnd('\r', '\n'));
                offset += lines[i].Length + 1;
            }
        }
    }

    // One analysable object: a POU, a member of one (method, action, property
    // accessor), a GVL or a DUT. Offsets are into Text, the object's part of
    // its file; LineBase turns a line of Text into a line of the file.
    internal sealed class Unit
    {
        internal string Id, Kind, QualifiedName, SourcePath, Text, Declaration, Implementation, OwnerId, OwnerName;
        internal int DeclarationStart, ImplementationStart, LineBase;
        // The object properties its cts pragma line sets.
        internal bool ExcludedFromBuild, LinkAlways;

        Section _body, _declarationSection;
        Match _header;
        List<VarBlock> _varBlocks;
        Block _tree;
        Dut _dut;
        bool _dutRead;

        // The implementation; a unit without one is analysed as its whole text.
        internal Section Body => _body ?? (_body = new Section(Implementation ?? Text, Implementation != null ? ImplementationStart : 0));
        internal Section DeclarationSection => _declarationSection ?? (_declarationSection = new Section(Declaration, DeclarationStart));
        internal List<VarBlock> VarBlocks => _varBlocks ?? (_varBlocks = string.IsNullOrEmpty(Declaration) ? new List<VarBlock>() : StDeclarations.VarBlocks(Declaration));
        internal IEnumerable<VarMember> Members(params string[] scopes) => StDeclarations.Members(VarBlocks, scopes);
        internal Block Tree => _tree ?? (_tree = StBlocks.Scan(Body.Text, Body.Base));
        // The declaration's header (StDeclarations.Header); its offsets are into Declaration.
        internal Match Header => _header ?? (_header = StDeclarations.Header.Match(StText.Blank(Declaration ?? "")));

        internal Dut Dut
        {
            get
            {
                if (!_dutRead) { _dut = string.IsNullOrEmpty(Declaration) ? null : StDeclarations.ParseDut(Declaration); _dutRead = true; }
                return _dut;
            }
        }

        // Unit offset of a declared member's name (null when not found).
        internal int? MemberOffset(VarMember member)
        {
            if (member.Line <= 0) return null;
            var lines = (Declaration ?? "").Split('\n');
            var index = member.Line - 1;
            if (index >= lines.Length) return null;
            var position = lines[index].IndexOf(member.Name, StringComparison.Ordinal);
            if (position < 0) return null;
            return DeclarationSection.At(lines.Take(index).Sum(line => line.Length + 1) + position);
        }
    }

    internal sealed class FileDirectives
    {
        internal HashSet<string> Rules = new HashSet<string>();
        internal List<Tuple<string, string, int>> Issues = new List<Tuple<string, string, int>>();
    }

    // The analysable units of one project-view tree, read from its .st files.
    internal sealed class Snapshot
    {
        static readonly Regex KeywordSplit = new Regex(@"^[ \t]*IMPLEMENTATION[ \t]*(?:\n|$)", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex MarkerSplit = new Regex(@"^[ \t]*" + Regex.Escape(StPragma.ImplementationMarker) + @"[ \t]*(?:\n|$)", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex TopLevelPou = new Regex(@"^[ \t]*(?<kind>FUNCTION_BLOCK|PROGRAM|FUNCTION)\s+(?<name>[A-Za-z_]\w*)\b", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex DirectiveLine = new Regex(@"^[ \t]*//[ \t]*cts:ignore-file\b([^\r\n]*)", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex DirectiveBlock = new Regex(@"^[ \t]*\(\*[ \t]*cts:ignore-file\b(.*?)[ \t]*\*\)", RegexOptions.IgnoreCase | RegexOptions.Multiline | RegexOptions.Singleline);
        // A system component library's name and the prefix of its functions.
        static readonly Regex ComponentStem = new Regex(@"^(?:Cmp(?<stem>[A-Z]\w{2,}?)|(?<stem>Sys[A-Z]\w*?))(?:Core)?$");

        internal string Root;
        internal readonly List<Unit> Units = new List<Unit>();
        internal readonly List<Docs.LibraryReference> Libraries = new List<Docs.LibraryReference>();
        internal readonly List<Diagnostic> Diagnostics = new List<Diagnostic>();
        internal readonly Dictionary<string, FileDirectives> Directives = new Dictionary<string, FileDirectives>(StringComparer.Ordinal);
        readonly Dictionary<string, Unit> _byId = new Dictionary<string, Unit>(StringComparer.Ordinal);
        readonly Dictionary<string, List<Unit>> _byName = new Dictionary<string, List<Unit>>(StringComparer.OrdinalIgnoreCase);
        HashSet<string> _blockTypes;

        internal Unit Find(string id) => id != null && _byId.TryGetValue(id, out var unit) ? unit : null;
        internal List<Unit> ByName(string name) => _byName.TryGetValue(name ?? "", out var units) ? units : new List<Unit>();
        // Whether a declared type is one of the project's function blocks,
        // named in full or by its last segment (Lib.FB_X or FB_X).
        internal bool IsFunctionBlockType(string type)
        {
            if (_blockTypes == null)
            {
                _blockTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var unit in Units.Where(unit => unit.Kind == Kinds.FunctionBlock))
                {
                    _blockTypes.Add(unit.QualifiedName);
                    _blockTypes.Add(LastSegment(unit.QualifiedName));
                }
            }
            type = type.Trim();
            return _blockTypes.Contains(type) || _blockTypes.Contains(LastSegment(type));
        }

        // The name after the last '.': " Lib.FB_Pump " -> "FB_Pump".
        internal static string LastSegment(string name)
        {
            var text = (name ?? "").Trim();
            return text.Substring(text.LastIndexOf('.') + 1);
        }

        // A library timer, counter or PID, or a project function block that
        // holds one, however deep; edges and bistables are not clocked.
        internal bool IsClocked(string type)
        {
            var name = LastSegment((type ?? "").Trim());
            if (Clocks.Contains(name)) return true;
            if (_clocked.TryGetValue(name, out var answer)) return answer;
            _clocked[name] = false;
            var block = ByName(name).FirstOrDefault(unit => unit.Kind == Kinds.FunctionBlock);
            return _clocked[name] = block != null && block.Members().Any(member => IsClocked(member.Type));
        }

        static readonly HashSet<string> Clocks = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "TON", "TOF", "TP", "LTON", "LTOF", "LTP", "CTU", "CTD", "CTUD", "PID", "INTEGRAL", "DERIVATIVE",
        };
        readonly Dictionary<string, bool> _clocked = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);

        // Whether a library the project references can hold the call name:
        // through its namespace (CmpLog.LogAdd2), or bare when a system
        // component library names its functions after itself (SysTimeGetNs
        // from SysTimeCore, IecTaskResetStatistics from CmpIecTask), by its
        // name or its placeholder (a device may redirect it to another).
        internal bool LibraryProvides(string name)
        {
            var dot = name.IndexOf('.');
            if (dot > 0)
            {
                var head = name.Substring(0, dot);
                return Libraries.Any(library => head.Equals(library.Namespace, StringComparison.OrdinalIgnoreCase) || head.Equals(library.Placeholder, StringComparison.OrdinalIgnoreCase));
            }
            return Libraries.SelectMany(library => new[] { library.Name, library.Placeholder }).Select(library => ComponentStem.Match(library ?? ""))
                .Any(stem => stem.Success && name.StartsWith(stem.Groups["stem"].Value, StringComparison.OrdinalIgnoreCase));
        }

        // The program or function block a method, action or accessor belongs
        // to (they share its file), or null.
        internal Unit InstanceOwner(Unit unit) => unit.OwnerName == null ? null : Find(unit.SourcePath + "#" + unit.OwnerName.Split('.')[0]) ?? Find(unit.OwnerId);

        // The variables a unit's code can name without a prefix: its own, then
        // those of its program or function block that it does not hide.
        internal IEnumerable<VarMember> MembersSeenBy(Unit unit)
        {
            var own = unit.Members().ToList();
            var owner = InstanceOwner(unit);
            if (owner == null) return own;
            var hidden = new HashSet<string>(own.Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            return own.Concat(owner.Members().Where(member => !hidden.Contains(member.Name)));
        }

        // The units inside owner: its methods and actions, and its properties' accessors (owned by Owner.Prop).
        internal IEnumerable<Unit> OwnedBy(string owner) => Units.Where(unit => unit.OwnerName != null && owner != null
            && (unit.OwnerName.Equals(owner, StringComparison.OrdinalIgnoreCase) || unit.OwnerName.StartsWith(owner + ".", StringComparison.OrdinalIgnoreCase)));

        // Every .st file under projectView (hidden folders skipped).
        internal static Snapshot Read(string projectView)
        {
            var root = Path.GetFullPath(projectView);
            var files = new SortedDictionary<string, string>(StringComparer.Ordinal);
            var unreadable = new List<Diagnostic>();
            foreach (var path in Directory.EnumerateFiles(root, "*.st", SearchOption.AllDirectories))
            {
                var relative = path.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar).Replace('\\', '/');
                if (relative.Split('/').Take(relative.Split('/').Length - 1).Any(part => part.StartsWith(".", StringComparison.Ordinal))) continue;
                try { files[relative] = File.ReadAllText(path, new UTF8Encoding(false, false)); }
                catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
                {
                    unreadable.Add(new Diagnostic("project-read", "cannot read " + relative + ": " + error.Message, new Location(relative)));
                }
            }
            var snapshot = Build(root, files);
            snapshot.Diagnostics.AddRange(unreadable);
            snapshot.Libraries.AddRange(Docs.LibraryReferences.Read(root, out _));
            return snapshot;
        }

        // A snapshot of the given files (project-view relative path -> text).
        internal static Snapshot Build(string root, IDictionary<string, string> files)
        {
            var snapshot = new Snapshot { Root = root };
            foreach (var file in files)
            {
                var text = StText.Lf((file.Value ?? "").TrimStart('﻿'));
                snapshot.Directives[file.Key] = ReadDirectives(text);
                snapshot.Units.AddRange(FileUnits(file.Key, text));
            }
            snapshot.Index();
            return snapshot;
        }

        // What CODESYS compiles: this snapshot without the objects excluded
        // from the build, a POU's members going with it. Files, directives
        // and diagnostics stay.
        internal Snapshot Built()
        {
            if (!Units.Any(unit => unit.ExcludedFromBuild)) return this;
            var files = new HashSet<string>(Units.Where(unit => unit.ExcludedFromBuild && unit.OwnerName == null).Select(unit => unit.SourcePath), StringComparer.Ordinal);
            var built = new Snapshot { Root = Root };
            built.Units.AddRange(Units.Where(unit => !unit.ExcludedFromBuild && !files.Contains(unit.SourcePath)));
            built.Libraries.AddRange(Libraries);
            built.Diagnostics.AddRange(Diagnostics);
            foreach (var directives in Directives) built.Directives[directives.Key] = directives.Value;
            built.Index();
            return built;
        }

        void Index()
        {
            var byName = new Dictionary<string, Unit>(StringComparer.OrdinalIgnoreCase);
            foreach (var unit in Units) if (!byName.ContainsKey(unit.QualifiedName)) byName[unit.QualifiedName] = unit;
            foreach (var unit in Units)
                if (unit.OwnerName != null && byName.TryGetValue(unit.OwnerName, out var owner)) unit.OwnerId = owner.Id;
            Units.Sort((a, b) => string.CompareOrdinal(a.Id, b.Id));
            foreach (var unit in Units)
            {
                _byId[unit.Id] = unit;
                if (!_byName.TryGetValue(unit.QualifiedName, out var list)) _byName[unit.QualifiedName] = list = new List<Unit>();
                list.Add(unit);
            }
        }

        // A file holding a POU with its members (the sync folder's layout)
        // gives one unit per member; any other file is one unit, or one per
        // top-level POU when it holds several.
        static IEnumerable<Unit> FileUnits(string relative, string text)
        {
            var read = StViewReader.ReadFile(relative, Encoding.UTF8.GetBytes(text));
            if (read.Errors.Count == 0 && read.Objects.Count > 1) return MemberUnits(relative, text, read.Objects);
            var matches = TopLevelPou.Matches(StText.Blanked(text)).Cast<Match>().ToList();
            if (matches.Count <= 1)
            {
                var whole = WholeUnit(relative, text, 0);
                if (read.Errors.Count == 0 && read.Objects.Count == 1) Flag(whole, read.Objects[0]);
                return new[] { whole };
            }
            return matches.Select((match, index) =>
            {
                var end = index + 1 < matches.Count ? matches[index + 1].Index : text.Length;
                var unit = WholeUnit(relative, text.Substring(match.Index, end - match.Index), StText.LineColumn(text, match.Index).Key - 1);
                unit.QualifiedName = match.Groups["name"].Value;
                unit.Id = relative + "#" + unit.QualifiedName;
                return unit;
            }).ToList();
        }

        static IEnumerable<Unit> MemberUnits(string relative, string text, IList<StViewObject> objects)
        {
            var lines = text.Split('\n');
            var depth = (Path.GetDirectoryName(relative) ?? "").Replace('\\', '/').Split('/').Count(part => part.Length > 0);
            foreach (var item in objects)
            {
                // A property's header only names its type; its accessors are the units.
                if (item.Kind == "PROPERTY") continue;
                var first = item.DeclarationLine ?? item.ImplementationLine;
                if (!first.HasValue) continue;
                if (item.Kind == "ACTION" && item.ImplementationLine.HasValue) first = item.ImplementationLine;
                var last = item.ImplementationLine.HasValue
                    ? item.ImplementationLine.Value + item.Implementation.Split('\n').Length - 1
                    : first.Value + item.Declaration.Split('\n').Length - 1;
                var slice = string.Join("\n", lines.Skip(first.Value - 1).Take(last - first.Value + 1));
                var qualified = string.Join(".", item.Path.Skip(depth));
                var unit = Split(relative, slice, first.Value - 1);
                unit.QualifiedName = qualified;
                unit.Id = relative + "#" + qualified;
                Flag(unit, item);
                var dot = qualified.LastIndexOf('.');
                unit.OwnerName = dot > 0 ? qualified.Substring(0, dot) : null;
                if (unit.Kind == Kinds.Unknown)
                    unit.Kind = item.Kind == "ACTION" ? Kinds.Action : item.Kind == "GET" ? Kinds.PropertyGet : item.Kind == "SET" ? Kinds.PropertySet : dot > 0 ? Kinds.Method : Kinds.Unknown;
                yield return unit;
            }
        }

        static void Flag(Unit unit, StViewObject item)
        {
            unit.ExcludedFromBuild = item.Settings != null && item.Settings.ContainsKey("ExcludeFromBuild");
            unit.LinkAlways = item.Settings != null && item.Settings.ContainsKey("LinkAlways");
        }

        // One file as one unit, its kind from the header or, for a member
        // file without one (Owner.Member.st), from the file name.
        static Unit WholeUnit(string relative, string text, int lineBase)
        {
            var unit = Split(relative, text, lineBase);
            var stem = Path.GetFileNameWithoutExtension(relative);
            var dot = stem.LastIndexOf('.');
            if (unit.Kind == Kinds.Unknown && dot >= 0)
            {
                var suffix = stem.Substring(dot + 1).ToLowerInvariant();
                unit.Kind = suffix == "get" ? Kinds.PropertyGet : suffix == "set" ? Kinds.PropertySet : suffix.EndsWith("action", StringComparison.Ordinal) ? Kinds.Action : Kinds.Method;
            }
            unit.QualifiedName = stem;
            unit.Id = relative + "#" + stem;
            unit.OwnerName = dot >= 0 ? stem.Substring(0, dot) : null;
            if (unit.OwnerName == null && (unit.Kind == Kinds.Method || unit.Kind == Kinds.Action || unit.Kind == Kinds.PropertyGet || unit.Kind == Kinds.PropertySet))
                unit.OwnerName = stem;
            return unit;
        }

        // Declaration and implementation, split at IMPLEMENTATION or the
        // sync folder's marker comment.
        static Unit Split(string relative, string text, int lineBase)
        {
            var unit = new Unit { SourcePath = relative, Text = text, LineBase = lineBase };
            var match = KeywordSplit.Match(StText.Blanked(text));
            if (!match.Success) match = MarkerSplit.Match(text);
            if (match.Success)
            {
                var declarationEnd = match.Index > 0 && text[match.Index - 1] == '\n' ? match.Index - 1 : match.Index;
                unit.Declaration = text.Substring(0, declarationEnd);
                var rest = text.Substring(match.Index + match.Length);
                var lead = rest.Length - rest.TrimStart('\n').Length;
                unit.Implementation = rest.Substring(lead);
                unit.ImplementationStart = match.Index + match.Length + lead;
            }
            else unit.Declaration = text;
            unit.Kind = Kinds.Classify(unit.Declaration);
            return unit;
        }

        // "// cts:ignore-file CTS0001, CTS0002 -- reason": the rules a file
        // turns off, and what is wrong with a directive.
        static FileDirectives ReadDirectives(string text)
        {
            var directives = new FileDirectives();
            foreach (var match in DirectiveLine.Matches(text).Cast<Match>().Concat(DirectiveBlock.Matches(text).Cast<Match>()))
            {
                var raw = match.Groups[1].Value.Trim();
                var line = StText.LineColumn(text, match.Index).Key;
                var delimiter = raw.Contains("--") ? "--" : raw.Contains("—") ? "—" : null;
                if (delimiter == null) { directives.Issues.Add(Tuple.Create("directive-missing-reason", "reason is required", line)); continue; }
                if (delimiter == "—") directives.Issues.Add(Tuple.Create("directive-em-dash", "use '--' before the reason", line));
                var payload = raw.Substring(0, raw.IndexOf(delimiter, StringComparison.Ordinal));
                foreach (var token in Regex.Split(payload.Trim(), @"[\s,]+").Select(t => t.ToUpperInvariant()))
                {
                    if (token == "*" || AnalyzeConfig.RuleId.IsMatch(token)) directives.Rules.Add(token);
                    else if (token.Length > 0) directives.Issues.Add(Tuple.Create("directive-invalid-rule", token, line));
                }
            }
            return directives;
        }
    }
}
