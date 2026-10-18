// `dev.reflect` walks an object graph by a textual path. A path is a list of
// steps, each read from one string:
//
//   Prop              a property of the runtime type or of any interface it implements
//   Prop = <value>    the same property, written to
//   Method()          a zero-argument method
//   Method(a, b)      a method with arguments
//   [n]               the n-th element of an IEnumerable
//
// and a value is one of
//
//   "text"            a string (JSON string syntax, escapes included)
//   <guid>            a Guid
//   <int>             an integer
//   <true|false>      a boolean
//   pinned:<n>        an object kept by dev.pin, so a walked object can be an argument
//   [a, b, ...]       an array of the above, for the many methods that take one
//
// This file is the parser only: it turns strings into steps and back. The
// reflection that carries a step out lives in DevReflection and DevTools, so
// the whole thing is testable against ordinary .NET objects.
using System;
using System.Collections.Generic;
using System.Globalization;

namespace Cts.Agent
{
    // A reference to an object kept by `dev.pin`, usable as an argument.
    public sealed class PinnedRef
    {
        public int Id { get; private set; }
        public PinnedRef(int id) { Id = id; }
        public override string ToString() { return "pinned:" + Id.ToString(CultureInfo.InvariantCulture); }
    }

    public sealed class PathStep
    {
        public enum StepKind { Property, Set, Method, Index }

        public StepKind Kind { get; private set; }
        public string Name { get; private set; }
        public IList<object> Arguments { get; private set; }
        public int Index { get; private set; }

        PathStep(StepKind kind)
        {
            Kind = kind;
            Arguments = new List<object>();
        }

        public static PathStep Property(string name)
        {
            if (string.IsNullOrEmpty(name))
                throw new ProtocolException(ErrorCodes.BadParams, "a path step has an empty property name");
            return new PathStep(StepKind.Property) { Name = name };
        }

        public static PathStep Set(string name, object value)
        {
            if (string.IsNullOrEmpty(name))
                throw new ProtocolException(ErrorCodes.BadParams, "a path step has an empty property name");
            var step = new PathStep(StepKind.Set) { Name = name };
            step.Arguments.Add(value);
            return step;
        }

        public static PathStep Method(string name, IList<object> arguments)
        {
            if (string.IsNullOrEmpty(name))
                throw new ProtocolException(ErrorCodes.BadParams, "a path step has an empty method name");
            var step = new PathStep(StepKind.Method) { Name = name };
            if (arguments != null) foreach (var argument in arguments) step.Arguments.Add(argument);
            return step;
        }

        public static PathStep Element(int index)
        {
            if (index < 0)
                throw new ProtocolException(ErrorCodes.BadParams, "a path index must not be negative");
            return new PathStep(StepKind.Index) { Index = index };
        }

        // How a client writes this step back (`GetApplication(<guid>)`).
        public override string ToString()
        {
            switch (Kind)
            {
                case StepKind.Index:
                    return "[" + Index.ToString(CultureInfo.InvariantCulture) + "]";
                case StepKind.Set:
                    return Name + " = " + DevPath.ArgumentText(Arguments[0]);
                case StepKind.Method:
                    return Name + "(" + string.Join(", ", ArgumentTexts()) + ")";
                default:
                    return Name;
            }
        }

        IEnumerable<string> ArgumentTexts()
        {
            foreach (var argument in Arguments) yield return DevPath.ArgumentText(argument);
        }
    }

    public static class DevPath
    {
        // Parses the `path` parameter: a JSON array of step strings.
        public static List<PathStep> Parse(IDictionary<string, object> parameters)
        {
            var steps = new List<PathStep>();
            object raw;
            if (parameters == null || !parameters.TryGetValue("path", out raw) || raw == null)
                return steps;
            var list = raw as IList<object>;
            if (list == null)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'path' must be an array of step strings");
            foreach (var item in list)
            {
                var text = item as string;
                if (text == null)
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'path' must contain only strings");
                steps.Add(ParseStep(text));
            }
            return steps;
        }

        public static PathStep ParseStep(string text)
        {
            if (string.IsNullOrEmpty(text))
                throw new ProtocolException(ErrorCodes.BadParams, "a path step is empty");

            if (text[0] == '[')
            {
                if (text[text.Length - 1] != ']')
                    throw new ProtocolException(ErrorCodes.BadParams, "unterminated index step: " + text);
                int index;
                if (!int.TryParse(text.Substring(1, text.Length - 2), NumberStyles.None,
                        CultureInfo.InvariantCulture, out index))
                    throw new ProtocolException(ErrorCodes.BadParams, "an index step must be [<integer>]: " + text);
                return PathStep.Element(index);
            }

            var open = text.IndexOf('(');
            if (open < 0)
            {
                // `Prop` or `Prop = <value>`; an '=' inside a value is not a step
                // separator, so split on the first one only.
                var assign = text.IndexOf('=');
                if (assign < 0) return PathStep.Property(text.Trim());
                var name = text.Substring(0, assign).Trim();
                var value = text.Substring(assign + 1).Trim();
                if (value.Length == 0)
                    throw new ProtocolException(ErrorCodes.BadParams, "a set step needs a value: " + text);
                return PathStep.Set(name, ParseArgument(value));
            }

            if (text[text.Length - 1] != ')')
                throw new ProtocolException(ErrorCodes.BadParams, "unterminated argument list: " + text);

            var method = text.Substring(0, open);
            var arguments = text.Substring(open + 1, text.Length - open - 2).Trim();
            if (arguments.Length == 0) return PathStep.Method(method, null);
            return PathStep.Method(method, SplitArguments(arguments));
        }

        static List<object> SplitArguments(string text)
        {
            var parts = new List<string>();
            var depth = 0;
            var start = 0;
            var quoted = false;
            for (var i = 0; i < text.Length; i++)
            {
                var c = text[i];
                if (quoted)
                {
                    if (c == '\\') i++;
                    else if (c == '"') quoted = false;
                    continue;
                }
                if (c == '"') quoted = true;
                else if (c == '[' || c == '(' || c == '<') depth++;
                else if (c == ']' || c == ')' || c == '>') depth--;
                else if (c == ',' && depth == 0)
                {
                    parts.Add(text.Substring(start, i - start));
                    start = i + 1;
                }
            }
            parts.Add(text.Substring(start));

            var values = new List<object>();
            foreach (var part in parts)
            {
                var trimmed = part.Trim();
                if (trimmed.Length == 0)
                    throw new ProtocolException(ErrorCodes.BadParams, "an empty argument in " + text);
                values.Add(ParseArgument(trimmed));
            }
            return values;
        }

        public static object ParseArgument(string text)
        {
            if (text.Length == 0) throw new ProtocolException(ErrorCodes.BadParams, "an empty argument");
            if (text[0] == '"')
            {
                object parsed;
                try { parsed = Json.Parse(text); }
                catch (JsonException e)
                {
                    throw new ProtocolException(ErrorCodes.BadParams, "bad string argument " + text + ": " + e.Message);
                }
                var s = parsed as string;
                if (s == null)
                    throw new ProtocolException(ErrorCodes.BadParams, "a quoted argument must be a string: " + text);
                return s;
            }
            if (text[0] == '[' && text[text.Length - 1] == ']')
            {
                var inner = text.Substring(1, text.Length - 2).Trim();
                if (inner.Length == 0) return new List<object>();
                return SplitArguments(inner);
            }
            if (text.StartsWith("pinned:", StringComparison.Ordinal))
            {
                int id;
                if (!int.TryParse(text.Substring("pinned:".Length), NumberStyles.None,
                        CultureInfo.InvariantCulture, out id))
                    throw new ProtocolException(ErrorCodes.BadParams, "pinned:<n> needs an integer: " + text);
                return new PinnedRef(id);
            }
            if (text[0] == '<' && text[text.Length - 1] == '>')
            {
                var inner = text.Substring(1, text.Length - 2).Trim();
                Guid guid;
                if (Guid.TryParse(inner, out guid)) return guid;
                long number;
                if (long.TryParse(inner, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out number))
                    return number;
                if (inner == "true") return true;
                if (inner == "false") return false;
                if (inner == "null") return null;
                throw new ProtocolException(ErrorCodes.BadParams,
                    "an angle-bracket argument must be a Guid, an integer, true/false or null: " + text);
            }
            throw new ProtocolException(ErrorCodes.BadParams,
                "an argument must be a quoted string, <guid>/<int>/<bool>/<null>, pinned:<n> or an array: " + text);
        }

        // Rendering an argument back into the grammar; a list is an array.
        public static string ArgumentText(object argument)
        {
            if (argument == null) return "<null>";
            if (argument is Guid) return "<" + argument + ">";
            if (argument is bool) return "<" + ((bool)argument).ToString().ToLowerInvariant() + ">";
            var text = argument as string;
            if (text != null) return Json.Serialize(text);
            var pinned = argument as PinnedRef;
            if (pinned != null) return pinned.ToString();
            var list = argument as IList<object>;
            if (list != null)
            {
                var parts = new List<string>();
                foreach (var item in list) parts.Add(ArgumentText(item));
                return "[" + string.Join(", ", parts) + "]";
            }
            return "<" + Convert.ToString(argument, CultureInfo.InvariantCulture) + ">";
        }
    }
}
