using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis
{
    // The analyzer's object kinds, from the ST header keyword (and the file
    // layout where the text has none), and the groups a rule names.
    internal static class Kinds
    {
        internal const string Program = "program", FunctionBlock = "function_block", Function = "function", Method = "method",
            Action = "action", PropertyGet = "property_get", PropertySet = "property_set", Interface = "interface", Gvl = "gvl",
            GvlPersistent = "gvl_persistent", Struct = "struct", Enum = "enum", Union = "union", Alias = "alias", Unknown = "unknown";

        internal static readonly string[] Callable = { Program, FunctionBlock, Function, Method, Action, PropertyGet, PropertySet };
        internal static readonly string[] Pou = Callable.Concat(new[] { Interface }).ToArray();
        internal static readonly string[] Type = { Struct, Enum, Union, Alias };
        internal static readonly string[] Globals = { Gvl, GvlPersistent };
        static readonly string[] All = Pou.Concat(Type).Concat(Globals).Concat(new[] { "visualization", "textlist", "task_config", Unknown }).ToArray();

        static readonly HashSet<string> HeaderKeywords = new HashSet<string> { "PROGRAM", "FUNCTION_BLOCK", "FUNCTION", "METHOD", "ACTION", "PROPERTY", "INTERFACE", "TYPE", "VAR_GLOBAL" };

        // A rule's kinds: group names (CALLABLE, POU, TYPE, ANY) and kinds.
        internal static HashSet<string> Expand(params string[] names)
        {
            var kinds = new HashSet<string>();
            foreach (var name in names)
            {
                switch (name.ToUpperInvariant())
                {
                    case "CALLABLE": kinds.UnionWith(Callable); break;
                    case "POU": kinds.UnionWith(Pou); break;
                    case "TYPE": kinds.UnionWith(Type); break;
                    case "ANY": kinds.UnionWith(All); break;
                    default:
                        if (!All.Contains(name)) throw new ArgumentException("unknown kind or group: " + name);
                        kinds.Add(name);
                        break;
                }
            }
            return kinds;
        }

        internal static bool IsCallable(string kind) => Callable.Contains(kind);
        internal static bool IsGlobals(string kind) => kind == Gvl || kind == GvlPersistent;

        // The kind a declaration's header names, or unknown.
        internal static string Classify(string declaration)
        {
            var blanked = StText.Blank(declaration ?? "");
            var first = blanked.Split('\n').Select(line => line.Trim()).FirstOrDefault(line => line.Length > 0);
            if (first == null) return Unknown;
            var keyword = first.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries)[0].ToUpperInvariant();
            if (!HeaderKeywords.Contains(keyword)) return Unknown;
            switch (keyword)
            {
                case "PROGRAM": return Program;
                case "FUNCTION_BLOCK": return FunctionBlock;
                case "FUNCTION": return Function;
                case "METHOD": return Method;
                case "ACTION": return Action;
                case "INTERFACE": return Interface;
                case "PROPERTY":
                    return Regex.IsMatch(blanked.Split('\n')[0], @"\bSET\b", RegexOptions.IgnoreCase) ? PropertySet : PropertyGet;
                case "TYPE":
                    var dut = StDeclarations.ParseDut(declaration);
                    if (dut == null) return Unknown;
                    return dut.Kind == "enum" ? Enum : dut.Kind == "union" ? Union : dut.Kind == "struct" ? Struct : Alias;
                default:
                    return blanked.Split('\n')[0].ToUpperInvariant().Contains("PERSISTENT") ? GvlPersistent : Gvl;
            }
        }
    }
}
