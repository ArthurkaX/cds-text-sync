using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // One arm of an IF (its condition, or "ELSE") or a CASE label.
    internal sealed class Branch
    {
        internal string Label;
        // Body: where its statements begin, after THEN, ELSE or a CASE label's ':'.
        internal int Start, Body, End;
    }

    // An IF/CASE/FOR/WHILE/REPEAT block of blanked implementation text, with
    // the blocks nested in it. Offsets are absolute (local offset + base).
    internal sealed class Block
    {
        internal string Kind;
        internal int Start;
        internal int? End;
        internal int Depth;
        internal Block Parent;
        internal readonly List<Block> Children = new List<Block>();
        internal readonly List<Branch> Branches = new List<Branch>();
        internal string HeaderText = "";
        // A loop: whether its body surely runs once (REPEAT, FOR over literal
        // bounds that meet), and the EXITs that leave it.
        internal bool RunsOnce;
        internal readonly List<int> Exits = new List<int>();
        // The root only: a block left open, closed at the section's end.
        internal bool Unbalanced;
        internal readonly List<KeyValuePair<int, string>> Issues = new List<KeyValuePair<int, string>>();

        internal int? PendingStart, PendingBody;
        internal string PendingLabel;
        internal bool InLabels;

        // The blocks and arms from this block down to offset (end closes a
        // block left open): two offsets with the same path share one
        // control-flow path.
        internal string PathTo(int offset, int end)
        {
            var path = new System.Text.StringBuilder();
            for (var node = this; node != null; node = node.Children.FirstOrDefault(child => child.Start <= offset && offset < (child.End ?? end)))
                path.Append(node.Start).Append(':').Append(node.Branches.FindIndex(branch => branch.Start <= offset && offset < branch.End)).Append('/');
            return path.ToString();
        }

        // An IF or CASE that takes an arm whatever the values: one with an
        // ELSE, or an IF whose conditions leave no case out (BoolLogic).
        bool Complete => (Kind == "IF" || Kind == "CASE") && (Branches.Any(branch => branch.Label == "ELSE")
            || Kind == "IF" && BoolLogic.Exhaustive(Branches.Select(branch => Guards.ConditionOf(branch.Label)).ToList()));

        // Whether every path through this block's text from start to end
        // passes one of offsets: one outside the nested blocks, a nested
        // complete IF or CASE whose every arm does, or a loop that surely
        // runs once and whose body does, before each of its EXITs too.
        internal bool Covers(List<int> offsets, int start, int end)
        {
            var children = Children.Where(child => start <= child.Start && child.Start < end && (child.End == null || child.End <= end)).ToList();
            return offsets.Any(offset => start <= offset && offset < end && !children.Any(child => child.Start <= offset && offset < (child.End ?? offset + 1)))
                || children.Any(child => child.End != null && child.Complete && child.Branches.All(branch => child.Covers(offsets, branch.Start, branch.End)))
                || children.Any(child => child.End != null && child.RunsOnce && child.Covers(offsets, child.Start, child.End.Value)
                    && child.Exits.All(exit => child.CoversBefore(offsets, child.Start, exit)));
        }

        // Whether every path from start to target, a point inside this
        // block, passes one of offsets.
        bool CoversBefore(List<int> offsets, int start, int target)
        {
            var inside = Children.FirstOrDefault(child => start <= child.Start && child.Start < target && target < (child.End ?? int.MaxValue));
            if (Covers(offsets, start, inside?.Start ?? target)) return true;
            var branch = inside?.Branches.FirstOrDefault(arm => arm.Start <= target && target < arm.End);
            return branch != null && inside.CoversBefore(offsets, branch.Start, target);
        }

        internal IEnumerable<Block> Descendants() => Children.SelectMany(child => new[] { child }.Concat(child.Descendants()));
    }

    // The control-flow nesting of blanked implementation text, nothing else:
    // no expressions, no symbols. Malformed text is tolerated: an unterminated
    // block closes at the end and the root says so.
    internal static class StBlocks
    {
        // A simple assignment to a named variable in implementation text.
        internal static readonly Regex Assignment = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*:=");
        // One to a whole variable, not to a member of one (rec.field :=).
        internal static readonly Regex WholeAssignment = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)\s*:=");
        static readonly Regex AssignsHere = new Regex(@"\G\s*:=");

        // Whether := follows at index, past blanks: the name before it is written.
        internal static bool AssignsAt(string text, int index) => AssignsHere.IsMatch(text, index);

        static readonly Regex LabelHere = new Regex(@"\G\s*=>");
        // Read leftwards, ending where the name starts.
        static readonly Regex OutputTarget = new Regex(@"=>\s*\G", RegexOptions.RightToLeft);
        static readonly Regex AddressTaken = new Regex(@"\bADR\s*\(\s*\G", RegexOptions.RightToLeft | RegexOptions.IgnoreCase);

        // Whether the name ending at end labels an argument ("label => target"): no read.
        internal static bool LabelsArgument(string text, int end) => LabelHere.IsMatch(text, end);

        // Whether the variable starting at start, its selectors ending at
        // end, is written there: assigned, an output mapping's target, or
        // handed to ADR.
        internal static bool WrittenAt(string text, int start, int end) => AssignsAt(text, end) || OutputTarget.IsMatch(text, start) || AddressTaken.IsMatch(text, start);
        static readonly Regex[] Writes =
        {
            new Regex(@"(?<![A-Za-z0-9_.])(?:THIS\s*\^\s*\.\s*)?(?<name>[A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*|\s*\[[^\]]+\])*\s*:=", RegexOptions.IgnoreCase),
            new Regex(@"=>\s*(?<name>[A-Za-z_]\w*)\b"),
            new Regex(@"(?<![A-Za-z0-9_.])(?:THIS\s*\^\s*\.\s*)?(?<name>[A-Za-z_]\w*)\s*(?:\.\s*[A-Za-z_]\w*\s*)?\(", RegexOptions.IgnoreCase),
        };
        static readonly Regex Keyword = new Regex(@"\G\b(?:IF|CASE|FOR|WHILE|REPEAT|ELSIF|ELSE|END_IF|END_CASE|END_FOR|END_WHILE|END_REPEAT|UNTIL|THEN|DO|TO|BY|OF|EXIT)\b", RegexOptions.IgnoreCase);

        // The variables text may change: the head of an assignment's target
        // (rec.field[i] := ...), an output mapping's target (Q => done) and an
        // instance called or whose method is called (fb(), fb.Stop()).
        internal static HashSet<string> Written(string text) => new HashSet<string>(
            Writes.SelectMany(pattern => pattern.Matches(text).Cast<Match>()).Select(match => match.Groups["name"].Value), StringComparer.OrdinalIgnoreCase);

        // A CASE label: tokens separated by ',' and ending in ':' (not ':=').
        // No ',' inside a token: a long "a,b,c,..." without a ':' would
        // otherwise be split every possible way before it fails.
        static readonly Regex Label = new Regex(@"\G[^\s:=\n,]+(?:\s*,\s*[^\s:=\n,]+)*\s*:(?!=)", RegexOptions.Multiline);
        static readonly HashSet<string> Openers = new HashSet<string> { "IF", "CASE", "FOR", "WHILE", "REPEAT" };
        static readonly HashSet<string> Loops = new HashSet<string> { "FOR", "WHILE", "REPEAT" };
        static readonly Dictionary<string, string> Closers = new Dictionary<string, string>
        {
            ["END_IF"] = "IF", ["END_CASE"] = "CASE", ["END_FOR"] = "FOR", ["END_WHILE"] = "WHILE", ["END_REPEAT"] = "REPEAT",
        };

        static IEnumerable<KeyValuePair<int, string>> Tokens(string text)
        {
            var i = 0;
            // The character before failed as a label's start and could be in
            // its first token: a label from here would be the tail of that one,
            // so fails too.
            var inLabel = false;
            while (i < text.Length)
            {
                var c = text[i];
                // A keyword starts a word with a letter.
                if ((c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z') && (i == 0 || !IsWord(text[i - 1])))
                {
                    var keyword = Keyword.Match(text, i);
                    if (keyword.Success) { yield return new KeyValuePair<int, string>(i, keyword.Value.ToUpperInvariant()); i += keyword.Length; inLabel = false; continue; }
                }
                if (!inLabel)
                {
                    var label = Label.Match(text, i);
                    if (label.Success) { yield return new KeyValuePair<int, string>(i, label.Value); i += label.Length; continue; }
                }
                inLabel = !char.IsWhiteSpace(c) && c != ':' && c != '=' && c != ',';
                i++;
            }
        }

        // What \w matches.
        static bool IsWord(char c)
        {
            if (char.IsLetterOrDigit(c) || c == '_') return true;
            var category = CharUnicodeInfo.GetUnicodeCategory(c);
            return category == UnicodeCategory.NonSpacingMark || category == UnicodeCategory.ConnectorPunctuation;
        }

        internal static Block Scan(string text, int offsetBase)
        {
            var root = new Block { Kind = "ROOT", Start = offsetBase };
            if (string.IsNullOrEmpty(text)) return root;
            var stack = new List<Block> { root };
            foreach (var token in Tokens(text))
            {
                var offset = token.Key;
                var word = token.Value;
                var top = stack[stack.Count - 1];
                if (Openers.Contains(word))
                {
                    var block = new Block { Kind = word, Start = offsetBase + offset, Depth = top.Depth + 1, Parent = top };
                    top.Children.Add(block);
                    // The opening keyword starts the first IF arm; a CASE
                    // selector is dropped at OF.
                    if (word == "IF" || word == "CASE") block.PendingStart = offset;
                    block.RunsOnce = word == "REPEAT";
                    stack.Add(block);
                    continue;
                }
                if (Closers.TryGetValue(word, out var expected))
                {
                    if (top.Kind != expected) { root.Issues.Add(new KeyValuePair<int, string>(offsetBase + offset, word + " without a matching " + expected)); continue; }
                    Finish(top, offset, offsetBase);
                    top.End = offsetBase + offset + word.Length;
                    stack.RemoveAt(stack.Count - 1);
                    continue;
                }
                switch (word)
                {
                    case "THEN":
                        if (top.Kind == "IF" && top.PendingStart.HasValue)
                        {
                            top.HeaderText = text.Substring(top.PendingStart.Value, offset - top.PendingStart.Value).Trim();
                            top.PendingLabel = top.HeaderText;
                            top.PendingBody = offset + word.Length;
                        }
                        continue;
                    case "OF":
                        if (top.Kind == "CASE") { top.InLabels = true; top.PendingStart = null; }
                        continue;
                    case "ELSE":
                    case "ELSIF":
                        if (top.Kind == "IF" || (top.Kind == "CASE" && word == "ELSE"))
                        {
                            Finish(top, offset, offsetBase);
                            top.PendingStart = offset;
                            top.PendingLabel = word == "ELSIF" ? null : "ELSE";
                            top.PendingBody = word == "ELSIF" ? (int?)null : offset + word.Length;
                        }
                        else root.Issues.Add(new KeyValuePair<int, string>(offsetBase + offset, word + " outside a block"));
                        continue;
                    case "UNTIL":
                        continue;
                    case "DO":
                        if (top.Kind == "FOR")
                        {
                            var head = top.Start - offsetBase + 3;
                            top.HeaderText = text.Substring(head, offset - head).Trim();
                            top.RunsOnce = RunsOnce(top.HeaderText);
                        }
                        continue;
                    case "EXIT":
                        stack.LastOrDefault(block => Loops.Contains(block.Kind))?.Exits.Add(offsetBase + offset);
                        continue;
                }
                if (top.Kind == "CASE" && top.InLabels)
                {
                    Finish(top, offset, offsetBase);
                    top.PendingStart = offset;
                    top.PendingLabel = word.TrimEnd(':').Trim();
                    top.PendingBody = offset + word.Length;
                }
            }
            while (stack.Count > 1)
            {
                var block = stack[stack.Count - 1];
                stack.RemoveAt(stack.Count - 1);
                Finish(block, text.Length, offsetBase);
                block.End = offsetBase + text.Length;
                root.Unbalanced = true;
                root.Issues.Add(new KeyValuePair<int, string>(block.Start, "unterminated " + block.Kind + " block"));
            }
            return root;
        }

        // FOR i := 1 TO 10 [BY 1] over literals that meet: the body runs once.
        static bool RunsOnce(string header)
        {
            var literal = ForLoop.LiteralForm.Match(header);
            if (!literal.Success) return false;
            var from = IecTypes.Literal(literal.Groups["start"].Value);
            var to = IecTypes.Literal(literal.Groups["end"].Value);
            var by = literal.Groups["step"].Success ? IecTypes.Literal(literal.Groups["step"].Value) : 1;
            return by > 0 ? from <= to : by < 0 && from >= to;
        }

        static void Finish(Block block, int end, int offsetBase)
        {
            if (!block.PendingStart.HasValue) return;
            block.Branches.Add(new Branch { Label = block.PendingLabel ?? "", Start = offsetBase + block.PendingStart.Value, Body = offsetBase + (block.PendingBody ?? block.PendingStart.Value), End = offsetBase + end });
            block.PendingStart = block.PendingBody = null;
        }
    }
}
