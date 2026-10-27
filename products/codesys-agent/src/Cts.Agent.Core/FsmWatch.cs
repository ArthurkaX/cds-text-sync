using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;
using Cts.Analysis;

namespace Cts.Agent
{
    // What to read online to watch a state machine run, from the
    // declarations alone: the path of its CASE variable in each instance the
    // programs and global variable lists hold (through function blocks,
    // structures and arrays), and the number a state's label stands for when
    // it is a constant or an enumeration's member.  `cts fsm` names both; the
    // FSM window reads the paths and finds the state by the numbers.
    internal sealed class FsmWatch
    {
        //: Instances listed for one function block at most, and how deep they nest.
        const int MostInstances = 200;
        const int Depth = 8;
        static readonly string[] Followed = { "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_GLOBAL" };
        static readonly Regex Range = new Regex(@"^(.+?)\s*\.\.\s*(.+)$");
        static readonly Regex This = new Regex(@"^THIS\^\.", RegexOptions.IgnoreCase);
        static readonly Regex Head = new Regex(@"^[A-Za-z_]\w*");
        static readonly Regex Index = new Regex(@"\[([^\]]*)\]");

        sealed class Pou
        {
            internal string Kind, Name, Extends, Declaration;
            internal List<VarBlock> Blocks;
        }

        readonly Dictionary<string, Pou> _pous = new Dictionary<string, Pou>(StringComparer.OrdinalIgnoreCase);
        //: Global variable lists by name, with their blocks.
        readonly Dictionary<string, List<VarBlock>> _lists = new Dictionary<string, List<VarBlock>>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, Dut> _types = new Dictionary<string, Dut>(StringComparer.OrdinalIgnoreCase);
        //: Global constants: name and List.name, to the text of their value.
        readonly Dictionary<string, string> _constants = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        Dictionary<string, List<string>> _instances;

        // *objects*: each text object's name and declaration.
        internal FsmWatch(IEnumerable<KeyValuePair<string, string>> objects)
        {
            foreach (var item in objects)
            {
                var declaration = item.Value ?? "";
                var header = StDeclarations.Header.Match(StText.Blank(declaration));
                if (header.Success && header.Groups["kind"].Value.Equals("TYPE", StringComparison.OrdinalIgnoreCase))
                {
                    var dut = StDeclarations.ParseDut(declaration);
                    if (dut != null) _types[dut.Name] = dut;
                    continue;
                }
                var blocks = StDeclarations.VarBlocks(declaration);
                if (!header.Success)
                {
                    if (blocks.Count == 0 || blocks.Any(block => block.Scope != "VAR_GLOBAL") || string.IsNullOrEmpty(item.Key)) continue;
                    _lists[item.Key] = blocks;
                    foreach (var member in blocks.Where(block => block.Constant).SelectMany(block => block.Members).Where(member => member.Initial.Length > 0))
                    {
                        if (!_constants.ContainsKey(member.Name)) _constants[member.Name] = member.Initial;
                        _constants[item.Key + "." + member.Name] = member.Initial;
                    }
                    continue;
                }
                var kind = header.Groups["kind"].Value.ToUpperInvariant();
                if (kind != "PROGRAM" && kind != "FUNCTION_BLOCK" && kind != "FUNCTION") continue;
                _pous[header.Groups["name"].Value] = new Pou
                {
                    Kind = kind, Name = header.Groups["name"].Value, Declaration = declaration, Blocks = blocks,
                    Extends = StDeclarations.PouHeader(declaration).Key,
                };
            }
        }

        // The paths that read the CASE variable *selector* of a machine in the
        // object *label* ("POU" or "POU.Method"), whose own declaration is
        // *declaration*; none when no instance holds it or it is a local.  An
        // array indexed by a variable (`aState[i]`) is a machine per element.
        internal List<string> Paths(string label, string declaration, string selector)
        {
            var path = This.Replace((selector ?? "").Trim(), "");
            var head = Head.Match(path).Value;
            if (head.Length == 0 || path.Contains("^")) return new List<string>();
            if (_lists.ContainsKey(head) && path.Length > head.Length && path[head.Length] == '.')
                return new List<string> { path };
            var parts = (label ?? "").Split('.');
            var member = parts.Length > 1;
            if (member && Declares(StDeclarations.VarBlocks(declaration), head)) return new List<string>();
            if (_pous.TryGetValue(parts[0], out var owner) && owner.Kind != "FUNCTION")
            {
                var all = Chain(owner).SelectMany(pou => pou.Blocks).ToList();
                var blocks = all.Where(block => Followed.Contains(block.Scope)).ToList();
                if (Declares(blocks, head))
                {
                    var elements = Elements(path, head, blocks, Constants(all));
                    return owner.Kind == "PROGRAM" ? elements.Select(element => owner.Name + "." + element).ToList()
                        : InstancesOf(owner.Name).SelectMany(instance => elements.Select(element => instance + "." + element)).Take(MostInstances).ToList();
                }
            }
            var list = _lists.FirstOrDefault(entry => Declares(entry.Value, head));
            return list.Key == null ? new List<string>() : Elements(path, head, list.Value, new Dictionary<string, string>()).Select(element => list.Key + "." + element).ToList();
        }

        // *path* as it is, or once per element when its first index is a
        // variable over an array of *head*'s with numbered bounds; none when
        // an index is a variable elsewhere.
        List<string> Elements(string path, string head, IEnumerable<VarBlock> blocks, Dictionary<string, string> own)
        {
            var indices = Index.Matches(path).Cast<Match>().ToList();
            var variable = indices.Where(index => Number(index.Groups[1].Value) == null).ToList();
            if (variable.Count == 0) return new List<string> { path };
            if (variable.Count > 1 || variable[0].Index != head.Length) return new List<string>();
            var type = blocks.SelectMany(block => block.Members).First(item => item.Name.Equals(head, StringComparison.OrdinalIgnoreCase)).Type;
            var shape = StDeclarations.ClassifyType(type);
            if (shape.Kind != "array" || shape.Dimensions.Count != 1) return new List<string>();
            var rest = path.Substring(variable[0].Index + variable[0].Length);
            return Indices(shape.Dimensions, own).Select(index => head + "[" + index + "]" + rest).ToList();
        }

        // The numbers a state's *label* ("A, B" or "10..19") stands for, as
        // decimal text or "low..high"; *declaration* holds its own constants.
        internal List<string> Values(string label, string owner, string declaration)
        {
            var blocks = new List<VarBlock>();
            if (_pous.TryGetValue(owner ?? "", out var pou)) blocks.AddRange(Chain(pou).SelectMany(item => item.Blocks));
            blocks.AddRange(StDeclarations.VarBlocks(declaration));
            var own = Constants(blocks);
            var values = new List<string>();
            foreach (var alias in (label ?? "").Split(',').Select(alias => alias.Trim()).Where(alias => alias.Length > 0))
            {
                var range = Range.Match(alias);
                if (range.Success)
                {
                    var low = Resolve(range.Groups[1].Value, own);
                    var high = Resolve(range.Groups[2].Value, own);
                    if (low != null && high != null) values.Add(low + ".." + high);
                    continue;
                }
                var value = Resolve(alias, own);
                if (value != null) values.Add(value.ToString());
            }
            return values;
        }

        // A literal, a constant (own, then global) or an enumeration's
        // member as a number; null for none.
        BigInteger? Resolve(string text, Dictionary<string, string> own)
        {
            text = text.Trim();
            var number = Number(text);
            if (number != null) return number;
            if (own.TryGetValue(text, out var local) || _constants.TryGetValue(text, out local)) return Number(local);
            var dot = text.LastIndexOf('.');
            if (dot > 0 && _types.TryGetValue(text.Substring(0, dot), out var type))
                return type.Fields.FirstOrDefault(field => field.Name.Equals(text.Substring(dot + 1), StringComparison.OrdinalIgnoreCase))?.Value;
            return null;
        }

        // The constants *blocks* declare, by name, to the text of their value.
        static Dictionary<string, string> Constants(IEnumerable<VarBlock> blocks)
        {
            var constants = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in blocks.Where(block => block.Constant).SelectMany(block => block.Members).Where(member => member.Initial.Length > 0))
                constants[member.Name] = member.Initial;
            return constants;
        }

        static BigInteger? Number(string text) => StConstants.Value(text.Trim()) is BigInteger value ? value : (BigInteger?)null;

        // The instance paths of a function block or of one that extends it.
        List<string> InstancesOf(string name)
        {
            if (_instances == null)
            {
                _instances = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
                foreach (var program in _pous.Values.Where(pou => pou.Kind == "PROGRAM").OrderBy(pou => pou.Name, StringComparer.OrdinalIgnoreCase))
                    Walk(program.Name, Chain(program).SelectMany(pou => pou.Blocks), 0);
                foreach (var list in _lists.OrderBy(entry => entry.Key, StringComparer.OrdinalIgnoreCase))
                    Walk(list.Key, list.Value, 0);
            }
            return _pous.Values.Where(pou => pou.Kind == "FUNCTION_BLOCK" && Chain(pou).Any(item => item.Name.Equals(name, StringComparison.OrdinalIgnoreCase)))
                .SelectMany(pou => _instances.TryGetValue(pou.Name, out var found) ? found : new List<string>()).Take(MostInstances).ToList();
        }

        void Walk(string path, IEnumerable<VarBlock> blocks, int depth)
        {
            var all = blocks.ToList();
            var own = Constants(all);
            foreach (var member in all.Where(block => !block.Constant && Followed.Contains(block.Scope)).SelectMany(block => block.Members))
                Place(path + "." + member.Name, member.Type, own, depth);
        }

        // One variable of *type* at *path*: an instance to note, a structure
        // or an array to look into.
        void Place(string path, string type, Dictionary<string, string> own, int depth)
        {
            if (depth > Depth) return;
            var shape = StDeclarations.ClassifyType(type);
            if (shape.Kind == "array")
            {
                foreach (var index in Indices(shape.Dimensions, own))
                    Place(path + "[" + index + "]", shape.Element, own, depth + 1);
                return;
            }
            if (shape.Kind != "ref") return;
            var name = shape.Name;
            if (_pous.TryGetValue(name, out var pou) || name.Contains(".") && _pous.TryGetValue(name.Substring(name.LastIndexOf('.') + 1), out pou))
            {
                if (pou.Kind != "FUNCTION_BLOCK") return;
                if (!_instances.TryGetValue(pou.Name, out var paths)) _instances[pou.Name] = paths = new List<string>();
                if (paths.Count >= MostInstances) return;
                paths.Add(path);
                Walk(path, Chain(pou).SelectMany(item => item.Blocks), depth + 1);
            }
            else if (_types.TryGetValue(name, out var dut) && dut.Kind == "struct")
                foreach (var field in dut.Fields) Place(path + "." + field.Name, field.Type, new Dictionary<string, string>(), depth + 1);
        }

        // Each index of an array whose bounds are numbers or constants (*own*,
        // then global), the first dimension varying slowest; none past
        // MostInstances.
        IEnumerable<string> Indices(List<KeyValuePair<string, string>> dimensions, Dictionary<string, string> own)
        {
            var bounds = dimensions.Select(dimension => new[] { Resolve(dimension.Key, own), Resolve(dimension.Value, own) }).ToList();
            if (bounds.Any(pair => pair[0] == null || pair[1] == null || pair[1] < pair[0])) return Enumerable.Empty<string>();
            IEnumerable<string> indices = new[] { "" };
            foreach (var pair in bounds)
            {
                var low = (long)pair[0].Value;
                var count = (long)(pair[1].Value - pair[0].Value) + 1;
                indices = indices.SelectMany(prefix => Enumerable.Range(0, (int)Math.Min(count, MostInstances))
                    .Select(i => (prefix.Length == 0 ? "" : prefix + ",") + (low + i).ToString(CultureInfo.InvariantCulture)));
            }
            return indices.Take(MostInstances);
        }

        // A POU and the ones it extends, nearest first.
        IEnumerable<Pou> Chain(Pou pou)
        {
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (var current = pou; current != null && seen.Add(current.Name); current = _pous.TryGetValue(current.Extends ?? "", out var parent) ? parent : null)
                yield return current;
        }

        static bool Declares(IEnumerable<VarBlock> blocks, string name) =>
            blocks.SelectMany(block => block.Members).Any(member => member.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
    }
}
