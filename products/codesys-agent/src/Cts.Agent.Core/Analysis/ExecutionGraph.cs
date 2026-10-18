using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // Who calls whom among the project's POUs, from the implementations:
    // calls resolve against project units and declared FB instances only, so
    // an unknown library or dynamic call adds no edge.
    internal sealed class ExecutionGraph
    {
        static readonly Regex Call = new Regex(@"\b(?<callee>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*\(");
        static readonly HashSet<string> NonCalls = new HashSet<string> { "IF", "ELSIF", "FOR", "WHILE", "CASE", "REPEAT", "RETURN", "SEL", "MUX", "AND", "OR", "XOR", "NOT", "MOD", "TO", "BY", "DO", "THEN", "OF", "UNTIL" };
        static readonly Regex ExtendsName = new Regex(@"\bEXTENDS\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)", RegexOptions.IgnoreCase);

        // Caller -> callees, caller -> names that resolved to nothing, both
        // by lower-case qualified name; caller -> library symbols it calls
        // (an instance's type, a qualified function) as written; and every
        // call's unit offset.
        internal readonly Dictionary<string, SortedSet<string>> Calls = new Dictionary<string, SortedSet<string>>();
        internal readonly Dictionary<string, SortedSet<string>> Unresolved = new Dictionary<string, SortedSet<string>>();
        internal readonly Dictionary<string, SortedSet<string>> LibraryCalls = new Dictionary<string, SortedSet<string>>();
        internal readonly Dictionary<string, List<Tuple<string, int, string>>> Sites = new Dictionary<string, List<Tuple<string, int, string>>>();
        readonly Snapshot _snapshot;
        readonly Dictionary<string, HashSet<string>> _names = new Dictionary<string, HashSet<string>>();
        readonly Dictionary<string, string> _globalTypes = new Dictionary<string, string>();

        internal ExecutionGraph(Snapshot snapshot)
        {
            _snapshot = snapshot;
            foreach (var unit in snapshot.Units.Where(unit => unit.Kind != Kinds.Unknown))
            {
                Index(Key(unit.QualifiedName), Key(unit.QualifiedName));
                Index(Short(unit.QualifiedName), Key(unit.QualifiedName));
            }
            foreach (var unit in snapshot.Units.Where(unit => Kinds.IsGlobals(unit.Kind)))
                foreach (var member in unit.Members().Where(m => !string.IsNullOrEmpty(m.Name) && !string.IsNullOrEmpty(m.Type.Trim())))
                    _globalTypes[Key(unit.QualifiedName + "." + member.Name)] = member.Type.Trim();
            foreach (var unit in snapshot.Units.Where(unit => Kinds.IsCallable(unit.Kind))) Collect(unit);
        }

        internal static string Key(string name) => (name ?? "").Trim().ToLowerInvariant();
        static string Short(string name) => Snapshot.LastSegment(Key(name));

        void Index(string key, string name)
        {
            if (!_names.TryGetValue(key, out var set)) _names[key] = set = new HashSet<string>();
            set.Add(name);
        }

        internal string Resolve(string name) => _names.TryGetValue(Key(name), out var set) && set.Count == 1 ? set.First() : null;

        static readonly Regex NamedArgument = new Regex(@"^(?<parameter>[A-Za-z_]\w*)\s*:=\s*(?<value>.*)$", RegexOptions.Singleline);
        static readonly Regex Variable = new Regex(@"^(?<name>[A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*|\s*\[[^\]]*\])*$");

        // The variables unit hands to a project callee's VAR_IN_OUT (not
        // CONSTANT), whole or a member or element of one: the callee may
        // change them (Logger(io := table), Copy(table[1])).
        internal IEnumerable<string> InOutArguments(Unit unit)
        {
            if (!Sites.TryGetValue(Key(unit.QualifiedName), out var sites)) yield break;
            var text = unit.Body.Text;
            foreach (var site in sites)
            {
                var callee = _snapshot.ByName(site.Item1).FirstOrDefault(found => Kinds.IsCallable(found.Kind));
                if (callee == null) continue;
                var parameters = callee.VarBlocks.Where(block => block.Scope == "VAR_INPUT" || block.Scope == "VAR_IN_OUT")
                    .SelectMany(block => block.Members.Select(member => Tuple.Create(member.Name, block.Scope == "VAR_IN_OUT" && !block.Constant))).ToList();
                var opening = site.Item2 - unit.Body.Base + site.Item3.Length - 1;
                var close = StCalls.Close(text, opening);
                if (close < 0) continue;
                var arguments = StCalls.Arguments(text.Substring(opening + 1, close - opening - 1));
                for (var index = 0; index < arguments.Count; index++)
                {
                    var named = NamedArgument.Match(arguments[index]);
                    var parameter = named.Success
                        ? parameters.FirstOrDefault(item => item.Item1.Equals(named.Groups["parameter"].Value, StringComparison.OrdinalIgnoreCase))
                        : index < parameters.Count ? parameters[index] : null;
                    var variable = Variable.Match(named.Success ? named.Groups["value"].Value.Trim() : arguments[index]);
                    if (parameter != null && parameter.Item2 && variable.Success) yield return variable.Groups["name"].Value;
                }
            }
        }

        string ResolveType(string name) => Resolve(name) ?? (_names.TryGetValue(Short(name), out var set) && set.Count == 1 ? set.First() : null);

        void Collect(Unit unit)
        {
            var section = unit.Body;
            if (section.IsEmpty) return;
            var caller = Key(unit.QualifiedName);
            var locals = new Dictionary<string, string>();
            foreach (var member in unit.Members().Where(m => m.Name.Length > 0 && m.Type.Length > 0)) locals[Key(member.Name)] = member.Type.Trim();
            var owner = unit.OwnerName == null ? null : _snapshot.Units.FirstOrDefault(u => Key(u.QualifiedName) == Key(unit.OwnerName));
            if (owner != null)
                foreach (var member in owner.Members().Where(m => m.Name.Length > 0 && m.Type.Length > 0)) locals[Key(member.Name)] = member.Type.Trim();
            // The declared type of a local, a GVL variable, or a member of
            // one or of a program, however deep (MAIN.fbDrive.fbTimer).
            string InstanceType(string path)
            {
                if (locals.TryGetValue(Key(path), out var type)) return type;
                if (_globalTypes.TryGetValue(Key(path), out var global)) return global;
                var dot = path.LastIndexOf('.');
                if (dot < 0) return null;
                var holder = InstanceType(path.Substring(0, dot)) ?? (Program(path.Substring(0, dot)) ? path.Substring(0, dot) : null);
                return holder == null ? null : MemberType(holder, path.Substring(dot + 1));
            }

            foreach (Match match in Call.Matches(section.Text))
            {
                var name = string.Join(".", match.Groups["callee"].Value.Split('.').Select(part => part.Trim()));
                var parts = name.Split('.');
                if (NonCalls.Contains(parts[parts.Length - 1].ToUpperInvariant())) continue;
                var head = parts[0].ToUpperInvariant();
                if ((head == "THIS" || head == "SUPER") && parts.Length > 1)
                {
                    var target = unit.OwnerName;
                    if (head == "SUPER" && unit.OwnerName != null)
                    {
                        var extends = ExtendsName.Match(owner?.Declaration ?? "");
                        if (extends.Success) target = extends.Groups[1].Value;
                    }
                    var method = Resolve(target != null ? target + "." + parts[parts.Length - 1] : parts[parts.Length - 1]);
                    if (method != null) Add(caller, method, section, match); else AddUnresolved(caller, name, section, match);
                    continue;
                }
                if (head == "THIS" || head == "SUPER") continue;
                var own = parts.Length == 1 ? Scopes(owner ?? unit).Select(scope => Resolve(scope + "." + name)).FirstOrDefault(found => found != null) : null;
                if (own != null) { Add(caller, own, section, match); continue; }
                var callee = Resolve(name);
                if (callee != null) { Add(caller, callee, section, match); continue; }
                var instance = InstanceType(name);
                if (instance != null)
                {
                    var fbType = ResolveType(instance);
                    if (fbType != null) Add(caller, fbType, section, match);
                    // A declared instance of a type not in the view (a library
                    // FB) is not an unresolved call.
                    else if (!locals.ContainsKey(Key(name)) && !Library.IsFunctionBlock(instance)) AddUnresolved(caller, instance, section, match);
                    else AddLibrary(caller, instance);
                    continue;
                }
                if (parts.Length > 1)
                {
                    var prefix = string.Join(".", parts.Take(parts.Length - 1));
                    var type = InstanceType(prefix);
                    if (type != null)
                    {
                        // A method call runs the method, not the block's body.
                        var method = Resolve(type + "." + parts[parts.Length - 1]);
                        if (method != null) { Add(caller, method, section, match); continue; }
                        var fbType = ResolveType(type);
                        if (fbType != null) Add(caller, fbType, section, match);
                        if (!Library.IsFunctionBlock(type)) AddUnresolved(caller, type + "." + parts[parts.Length - 1], section, match);
                        else AddLibrary(caller, type);
                        continue;
                    }
                }
                if (Library.IsFunction(name) || Library.IsFunctionBlock(name))
                {
                    // A bare standard function (LEFT, ADR) says little; a
                    // namespace-qualified one names its library.
                    if (parts.Length > 1 || Library.IsFunctionBlock(name)) AddLibrary(caller, name);
                    continue;
                }
                if (_snapshot.LibraryProvides(name)) AddLibrary(caller, name);
                else AddUnresolved(caller, name, section, match);
            }
        }

        bool Program(string name) => _snapshot.ByName(name).Any(unit => unit.Kind == Kinds.Program);

        // The type of member name of the program or function block type.
        string MemberType(string type, string name)
        {
            var holder = _snapshot.ByName(Snapshot.LastSegment(type)).FirstOrDefault(unit => unit.Kind == Kinds.Program || unit.Kind == Kinds.FunctionBlock);
            var member = holder?.Members().FirstOrDefault(m => Key(m.Name) == Key(name) && m.Type.Length > 0);
            return member?.Type.Trim();
        }

        // A function block and the blocks it extends, nearest first: where a
        // bare call to a method or action of its own resolves.
        IEnumerable<string> Scopes(Unit block)
        {
            var seen = new HashSet<string>();
            for (var current = block; current != null && seen.Add(Key(current.QualifiedName));)
            {
                yield return current.QualifiedName;
                var extends = ExtendsName.Match(current.Declaration ?? "");
                current = extends.Success ? _snapshot.ByName(Snapshot.LastSegment(extends.Groups[1].Value)).FirstOrDefault(unit => unit.Kind == Kinds.FunctionBlock) : null;
            }
        }

        void Add(string caller, string callee, Section section, Match match)
        {
            if (!Calls.TryGetValue(caller, out var set)) Calls[caller] = set = new SortedSet<string>(StringComparer.Ordinal);
            set.Add(callee);
            Site(caller, callee, section, match);
        }

        void AddUnresolved(string caller, string name, Section section, Match match)
        {
            Site(caller, name, section, match);
            if (!Unresolved.TryGetValue(caller, out var set)) Unresolved[caller] = set = new SortedSet<string>(StringComparer.Ordinal);
            set.Add(name);
        }

        void AddLibrary(string caller, string name)
        {
            if (!LibraryCalls.TryGetValue(caller, out var set)) LibraryCalls[caller] = set = new SortedSet<string>(StringComparer.Ordinal);
            set.Add(name);
        }

        void Site(string caller, string name, Section section, Match match)
        {
            if (!Sites.TryGetValue(caller, out var list)) Sites[caller] = list = new List<Tuple<string, int, string>>();
            list.Add(Tuple.Create(name, section.At(match.Index), match.Value));
        }
    }
}
