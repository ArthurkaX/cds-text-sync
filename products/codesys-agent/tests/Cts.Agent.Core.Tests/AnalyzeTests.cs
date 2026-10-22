using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Analysis;
using Xunit;

namespace Cts.Agent.Tests
{
    public class AnalyzeTests
    {
        // A rule's documentation is its test: each ```st good``` block gives
        // no finding, each ```st bad [N]``` block at least one (exactly N),
        // on the lines marked // cts:here when there are marks.
        public static IEnumerable<object[]> DocumentedRules() => RuleCatalog.All.Select(rule => new object[] { rule.Id });

        [Theory]
        [MemberData(nameof(DocumentedRules))]
        public void A_rule_keeps_what_its_documentation_shows(string id)
        {
            var rule = RuleCatalog.All.Single(r => r.Id == id);
            var blocks = Regex.Matches(rule.Doc(), @"```st\s+(good|bad)(?:\s+(\d+))?\s*\n(.*?)```", RegexOptions.Singleline).Cast<Match>().ToList();
            Assert.True(blocks.Count > 0, id + " documents no ```st good/bad``` example");
            foreach (var block in blocks)
            {
                var good = block.Groups[1].Value == "good";
                Assert.False(good && block.Groups[2].Success, id + ": a good example takes no count");
                var marks = new HashSet<int>();
                var lines = block.Groups[3].Value.Trim('\n').Split('\n');
                for (var i = 0; i < lines.Length; i++)
                {
                    var marked = Regex.Replace(lines[i], @"//\s*cts:here", m => new string(' ', m.Length));
                    if (marked != lines[i]) marks.Add(i + 1);
                    lines[i] = marked;
                }
                var findings = Snippet(rule, string.Join("\n", lines));
                var shown = block.Value + "\n -> " + string.Join("; ", findings.Select(f => f.Location.Line + ": " + f.Message));
                if (good) Assert.True(findings.Count == 0, id + " finds something in a good example:\n" + shown);
                else
                {
                    if (block.Groups[2].Success) Assert.True(findings.Count == int.Parse(block.Groups[2].Value), id + " finds " + findings.Count + ", not " + block.Groups[2].Value + ":\n" + shown);
                    else Assert.True(findings.Count > 0, id + " finds nothing in a bad example:\n" + shown);
                    if (marks.Count > 0) Assert.True(marks.SetEquals(findings.Select(f => f.Location.Line ?? 0)), id + " finds on other lines than marked:\n" + shown);
                }
            }
        }

        [Fact]
        public void The_runner_names_each_rule_as_it_starts()
        {
            var snapshot = Snapshot.Build(".", new Dictionary<string, string> { ["Main.st"] = "PROGRAM Main\nVAR\n    x : INT;\nEND_VAR\nx := x + 1;\n" });
            var config = AnalyzeConfig.Load(Path.GetTempPath());
            var steps = new List<Tuple<int, int, string>>();
            Runner.Run(snapshot, config, Runner.Select(config, null), (number, count, rule) => steps.Add(Tuple.Create(number, count, rule)));
            Assert.NotEmpty(steps);
            Assert.Equal(Enumerable.Range(1, steps.Count), steps.Select(step => step.Item1));
            Assert.All(steps, step => Assert.Equal(steps.Count, step.Item2));
            Assert.Equal(steps.Count, steps.Select(step => step.Item3).Distinct().Count());
        }

        [Fact]
        public void A_screen_with_an_image_is_read_in_one_pass()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-external-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                // An image's base64: one long word a path inside it would rescan from every letter.
                File.WriteAllText(Path.Combine(root, "Screen.xml"), "<v>GVL.fbPump.xOut</v><img>" + new string('A', 400000) + "</img>");
                var clock = System.Diagnostics.Stopwatch.StartNew();
                var external = new ExternalReferences(root);
                Assert.True(external.IsReferenced("gvl.fbpump", "xout"));
                Assert.True(external.IsReferenced("fbPump", "xOut"));
                Assert.True(clock.Elapsed < TimeSpan.FromSeconds(5), "read in " + clock.Elapsed);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void A_variable_mapped_to_an_io_channel_is_in_use()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-io-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.WriteAllText(Path.Combine(root, "DI_8.xml"), "<Single Name=\"Variable\" Type=\"string\">Application.GVL_IO.\txStart</Single><Single Name=\"Variable\" Type=\"string\">Application.GVL_IO.wLamps.OUT.bit3</Single>");
                var snapshot = Snapshot.Build(root, new Dictionary<string, string>
                {
                    ["GVL_IO.st"] = "VAR_GLOBAL\n    xStart : BOOL;\n    xStop : BOOL;\n    wLamps : WORD;\nEND_VAR\n",
                    ["Main.st"] = "PROGRAM Main\nVAR\n    n : INT;\nEND_VAR\nIMPLEMENTATION\nn := n + 1;\n",
                });
                var rule = RuleCatalog.All.Single(r => r.Id == "CTS0013");
                var findings = rule.Check(new RuleContext(snapshot, new AnalyzeConfig()) { Active = rule }).ToList();
                Assert.Equal(new[] { "declared symbol 'xStop' has no explicit reference in the analyzed Structured Text" }, findings.Select(f => f.Message));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void An_object_no_task_reaches_is_named()
        {
            var files = new Dictionary<string, string>
            {
                ["MAIN.st"] = "PROGRAM MAIN\nVAR\n    fbA : FB_A;\nEND_VAR\nIMPLEMENTATION\nfbA();\nGVL_Used.n := GVL_Used.n + 1;\n",
                ["FB_A.st"] = "FUNCTION_BLOCK FB_A\nVAR\n    n : INT;\nEND_VAR\nIMPLEMENTATION\nn := n + 1;\n",
                ["FB_B.st"] = "FUNCTION_BLOCK FB_B\nVAR\n    n : INT;\nEND_VAR\nIMPLEMENTATION\nn := n + 1;\n",
                ["GVL_Used.st"] = "VAR_GLOBAL\n    n : INT;\nEND_VAR\n",
                ["GVL_Spare.st"] = "VAR_GLOBAL\n    m : INT;\nEND_VAR\n",
                ["Kept.st"] = "{attribute 'linkalways'}\nFUNCTION Kept : INT\nIMPLEMENTATION\nKept := 1;\n",
                // The object properties: a linked one is a root; an excluded one is
                // not built, so neither reported nor reaching what it calls.
                ["Pinned.st"] = "(* cds-text-sync: LinkAlways *)\nFUNCTION Pinned : INT\n// --- implementation ---\nPinned := 1;\nEND_FUNCTION\n",
                ["Old.st"] = "(* cds-text-sync: ExcludeFromBuild *)\nPROGRAM Old\nVAR\n    fbB : FB_B;\nEND_VAR\n// --- implementation ---\nfbB();\nEND_PROGRAM\n",
            };
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0100");
            List<string> Messages(bool tasks)
            {
                var root = Path.Combine(Path.GetTempPath(), "cts-reach-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(root);
                try
                {
                    if (tasks) File.WriteAllText(Path.Combine(root, "MainTask.xml"), "<List Name=\"PouList\"><Single Name=\"Name\">MAIN</Single><Single Name=\"Name\">Old</Single></List>");
                    var context = new RuleContext(Snapshot.Build(root, files).Built(), new AnalyzeConfig()) { Active = rule };
                    return rule.Check(context).Select(f => f.Message).OrderBy(m => m, StringComparer.Ordinal).ToList();
                }
                finally { Directory.Delete(root, true); }
            }
            Assert.Equal(new[]
            {
                "FUNCTION_BLOCK 'FB_B' is not reached from any task, event or screen; CODESYS leaves it out of the application",
                "GVL 'GVL_Spare' is not reached from any task, event or screen; CODESYS leaves it out of the application",
            }, Messages(true));
            // No task configuration in the view: nothing to reach from.
            Assert.Empty(Messages(false));
        }

        [Theory]
        [InlineData("<v>GVL.fbPump.xOut</v>", "GVL|fbPump|xOut")]
        [InlineData("x . y[1] . z", "x|y|z")]
        [InlineData("x . y [1] . z", "x|y")]
        [InlineData("a[b.c]", "b|c")]
        [InlineData("q.w[1].e[2] r.t", "q|w|e;r|t")]
        [InlineData("9abc.def a.b.5", "a|b")]
        [InlineData("a[1\n].b A.b[", "A|b")]
        [InlineData("plain words, no path", "")]
        [InlineData("<Single Name=\"Expr\" Type=\"Cts.Visu.Element\">GVL.a.b</Single>", "GVL|a|b")]
        [InlineData("<![CDATA[x := A.b > 1;]]>", "A|b")]
        public void A_screen_names_the_paths_its_text_holds(string text, string paths)
        {
            Assert.Equal(paths, string.Join(";", ExternalReferences.Paths(text).Select(path => string.Join("|", path))));
        }

        [Fact]
        public void A_long_list_without_spaces_does_not_stall_the_block_scan()
        {
            // 40 arguments joined by ',' and no ':' after them: a label pattern
            // that may split the run at every ',' tries 2^40 ways.
            var call = "F(" + string.Join(",", Enumerable.Repeat("a", 40)) + ")";
            var text = "CASE n OF\n1, 2: x := " + call + ";\nELSE y := 0;\nEND_CASE\n";
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var block = StBlocks.Scan(text, 0).Children.Single();
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(5), "scanned in " + clock.Elapsed);
            Assert.Equal(new[] { "1, 2", "ELSE" }, block.Branches.Select(branch => branch.Label));
        }

        [Fact]
        public void Every_rule_document_belongs_to_a_rule()
        {
            var ids = new HashSet<string>(RuleCatalog.All.Select(rule => rule.Id));
            var documents = typeof(Rule).Assembly.GetManifestResourceNames().Where(n => n.StartsWith("Cts.Analysis.Rules.", StringComparison.Ordinal)).ToList();
            Assert.All(documents, name => Assert.Contains(name.Substring("Cts.Analysis.Rules.".Length, 7), ids));
            Assert.Equal(RuleCatalog.All.Select(rule => rule.Id).OrderBy(id => id, StringComparer.Ordinal), RuleCatalog.All.Select(rule => rule.Id));
        }

        static readonly Regex TopLevel = new Regex(@"^\s*(?:\{attribute[^}]*\}\s*)*(?:PROGRAM\b|FUNCTION_BLOCK\b|FUNCTION\b|METHOD\b|INTERFACE\b|VAR_GLOBAL\b)", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex Header = new Regex(@"^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION|METHOD|INTERFACE)\s+([A-Za-z_]\w*)\b", RegexOptions.IgnoreCase | RegexOptions.Multiline);

        // The example as a project: each top-level object its own file, a
        // body alone wrapped in a PROGRAM, plus what its marks declare
        // (// cts:owner FB, // cts:fb FB [extends BASE], // cts:method FB: M, // cts:interface I,
        // cts:function F, // cts:gvl G: name [TYPE]).
        static List<Finding> Snippet(Rule rule, string text)
        {
            var starts = TopLevel.Matches(text).Cast<Match>().Select(m => m.Index).ToList();
            if (starts.Count <= 1) starts = new List<int> { 0 };
            var segments = starts.Select((start, i) => Tuple.Create(start, text.Substring(start, (i + 1 < starts.Count ? starts[i + 1] : text.Length) - start))).ToList();
            var files = new Dictionary<string, string>();
            var lineBases = new Dictionary<string, int>();
            var owner = Regex.Match(text, @"//\s*cts:owner\s+(\S+)", RegexOptions.IgnoreCase);
            for (var index = 0; index < segments.Count; index++)
            {
                var segment = segments[index].Item2;
                var header = Header.Match(segment);
                var stem = header.Success ? header.Groups[1].Value : "snippet" + (index > 0 ? index.ToString() : "");
                var prefix = "";
                if (Snapshot.Build(".", new Dictionary<string, string> { [stem + ".st"] = segment }).Units.Single().Kind == Kinds.Unknown)
                    prefix = Regex.IsMatch(Regex.Replace(segment, @"(?m)^\s*//.*$", "").TrimStart(), @"^VAR(?:_[A-Z_]+)?\b", RegexOptions.IgnoreCase)
                        ? "PROGRAM Snippet\n" : "PROGRAM Snippet\nVAR\nEND_VAR\nIMPLEMENTATION\n";
                if (owner.Success && Regex.IsMatch(segment, @"^\s*METHOD\b", RegexOptions.IgnoreCase | RegexOptions.Multiline)) stem = owner.Groups[1].Value + "." + stem;
                files[stem + ".st"] = prefix + segment;
                lineBases[stem + ".st"] = text.Substring(0, segments[index].Item1).Count(c => c == '\n') - prefix.Count(c => c == '\n');
            }
            foreach (Match m in Regex.Matches(text, @"//\s*cts:fb\s+(\S+)(?:\s+extends\s+(\S+))?", RegexOptions.IgnoreCase))
                files[m.Groups[1].Value + ".st"] = "FUNCTION_BLOCK " + m.Groups[1].Value + (m.Groups[2].Success ? " EXTENDS " + m.Groups[2].Value : "") + "\nVAR\nEND_VAR\n";
            foreach (Match m in Regex.Matches(text, @"//\s*cts:method\s+([^:]+):\s*(\S+)", RegexOptions.IgnoreCase))
                files[m.Groups[1].Value.Trim() + "." + m.Groups[2].Value + ".st"] = "METHOD " + m.Groups[2].Value + "\nIMPLEMENTATION\n";
            foreach (Match m in Regex.Matches(text, @"//\s*cts:interface\s+(\S+)", RegexOptions.IgnoreCase))
                files[m.Groups[1].Value + ".st"] = "INTERFACE " + m.Groups[1].Value + "\nEND_INTERFACE\n";
            foreach (Match m in Regex.Matches(text, @"//\s*cts:function\s+(\S+)", RegexOptions.IgnoreCase))
                files[m.Groups[1].Value + ".st"] = "FUNCTION " + m.Groups[1].Value + " : BOOL\nIMPLEMENTATION\n" + m.Groups[1].Value + " := TRUE;\n";
            foreach (var gvl in Regex.Matches(text, @"//\s*cts:gvl\s+([^:]+):\s*(\S+)(?:[ \t]+([^\s]+))?", RegexOptions.IgnoreCase).Cast<Match>().GroupBy(m => m.Groups[1].Value.Trim()))
                files[gvl.Key + ".st"] = "VAR_GLOBAL\n" + string.Join("\n", gvl.Select(m => "    " + m.Groups[2].Value + " : " + (m.Groups[3].Success ? m.Groups[3].Value : "INT") + ";")) + "\nEND_VAR\n";
            var snapshot = Snapshot.Build(".", files);
            foreach (var unit in snapshot.Units) if (lineBases.TryGetValue(unit.SourcePath, out var lineBase)) unit.LineBase = lineBase;
            var candidates = snapshot.Units.Where(unit => lineBases.ContainsKey(unit.SourcePath)).ToList();
            var target = candidates.FirstOrDefault(unit => Kinds.IsCallable(unit.Kind)) ?? candidates.First();
            var context = new RuleContext(snapshot, new AnalyzeConfig()) { Active = rule };
            return (rule.PerUnit ? rule.Check(target, context) : rule.Check(context)).ToList();
        }

        [Fact]
        public void A_literal_of_any_length_is_a_number_not_an_overflow()
        {
            var huge = "123456789012345678901234567890";
            Assert.Single(Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0040"), "PROGRAM P\nVAR\n    b : BYTE;\nEND_VAR\nIMPLEMENTATION\nb := SHL(b, " + huge + ");\n"));
            Assert.Single(Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0038"), "PROGRAM P\nVAR\n    i : INT;\nEND_VAR\nIMPLEMENTATION\nFOR i := 1 TO " + huge + " BY -1 DO\nEND_FOR;\n"));
        }

        [Fact]
        public void Array_bounds_may_be_based_or_grouped_and_a_string_holds_its_terminator()
        {
            var sizes = Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0071"),
                "PROGRAM P\nVAR\n    a : ARRAY[0..16#7FF] OF BYTE;\n    b : ARRAY[1..1_000] OF STRING(1);\n    c : STRING(1023);\n    d : WSTRING(511);\n    e : STRING(1024);\nEND_VAR\nIMPLEMENTATION\n");
            Assert.Equal(new[] { "variable 'a' has a statically known size of 2048 bytes", "variable 'b' has a statically known size of 2000 bytes", "variable 'e' has a statically known size of 1025 bytes" },
                sizes.Select(finding => finding.Message));
        }

        [Fact]
        public void A_member_or_bit_access_is_not_the_variable_of_the_same_name()
        {
            var declarations = "PROGRAM P\nVAR\n    x : INT;\n    u : UINT;\n    w : WORD;\n    t : TIME;\n    s : ST_Point;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0055"), declarations + "IF s.x < u OR x = w.3 THEN\n    x := 0;\nEND_IF;\n"));
            Assert.Single(Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0055"), declarations + "IF x < u THEN\n    x := 0;\nEND_IF;\n"));
            Assert.Empty(Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0062"), declarations + "t := s.t + 5;\n"));
            Assert.Single(Snippet(RuleCatalog.All.Single(rule => rule.Id == "CTS0062"), declarations + "t := t + 5;\n"));
        }

        [Fact]
        public void A_pointer_guard_is_the_condition_up_to_THEN_over_any_lines()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0082");
            var declarations = "PROGRAM P\nVAR\n    p : POINTER TO INT;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Single(Snippet(rule, declarations + "IF p <> 0\n    AND p^ > 0 THEN\n    p^ := 0;\nEND_IF;\n"));
            Assert.Empty(Snippet(rule, declarations + "IF p <> 0 AND TRUE THEN p^ := 0; END_IF;\n"));
        }

        [Fact]
        public void An_integer_division_counts_into_a_method_result_but_not_inside_a_real_literal()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0077");
            Assert.Single(Snippet(rule, "METHOD PUBLIC Ratio : REAL\nVAR_INPUT\n    a : INT;\n    b : INT;\nEND_VAR\nIMPLEMENTATION\nRatio := a / b;\n"));
            Assert.Empty(Snippet(rule, "PROGRAM P\nVAR\n    r : REAL;\n    n : INT;\nEND_VAR\nIMPLEMENTATION\nr := 1.5 / n + n / 2.0;\n"));
        }

        [Fact]
        public void A_string_literal_counts_each_dollar_escape_as_one_character()
        {
            var findings = Snippet(RuleCatalog.All.Single(r => r.Id == "CTS0078"),
                "PROGRAM P\nVAR\n    s : STRING(3);\n    t : STRING(2) := 'abc';\nEND_VAR\nIMPLEMENTATION\ns := '$02$03';\ns := 'a$'b$N';\n");
            Assert.Equal(new[] { "string literal has 3 characters but t is limited to STRING(2)", "string literal has 4 characters but s is limited to STRING(3)" }, findings.Select(f => f.Message));
        }

        [Fact]
        public void A_tighter_operator_takes_its_operand_out_of_a_boolean_pair()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0081");
            var declarations = "PROGRAM P\nVAR\n    a : BOOL;\n    b : BOOL;\n    x : BOOL;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "x := a OR TRUE AND b;\nx := b AND a OR NOT a;\nx := a OR NOT a XOR b;\n"));
            Assert.Equal(new[] { "boolean expression 'a AND NOT a' is always false", "boolean expression 'a OR TRUE' is always true" },
                Snippet(rule, declarations + "x := a OR TRUE;\nx := b OR a AND NOT a;\n").Select(f => f.Message));
        }

        [Fact]
        public void Mixed_AND_and_OR_are_read_per_expression_whatever_its_lines_and_per_group()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0098");
            var declarations = "PROGRAM P\nVAR\n    a : BOOL;\n    b : BOOL;\n    x : BOOL;\n    s : STRING;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "x := (a AND b) OR x;\nx := a OR (b AND x);\nx := SEL(a AND b, x OR a, b);\nx := a OR b;\nx := a AND b;\n"
                + "// a AND b OR x\ns := 'a AND b OR x';\nIF a OR b THEN\n    x := a AND b;\nEND_IF\n"));
            var findings = Snippet(rule, declarations + "IF a <> b // differs\n    OR x\n    AND b\nTHEN\n    x := FALSE;\nEND_IF\nIF (a) OR b AND x THEN\n    x := NOT x;\nEND_IF\nx := a OR b AND x;\n");
            Assert.Equal(new[] { "boolean expression 'a <> b OR x AND b' mixes AND and OR without parentheses", "boolean expression '(a) OR b AND x' mixes AND and OR without parentheses",
                "boolean expression 'x := a OR b AND x' mixes AND and OR without parentheses" },
                findings.Select(f => f.Message));
        }

        [Fact]
        public void A_lone_semicolon_is_empty_after_a_branch_header_on_however_many_lines_but_ends_a_long_statement()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0023");
            var declarations = "PROGRAM P\nVAR\n    a : BOOL;\n    b : BOOL;\n    n : INT;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "n := n\n    + 1\n;\nIF a THEN\n    ; // wait for b\nEND_IF\n"));
            var findings = Snippet(rule, declarations + "IF a\n    AND b\nTHEN\n    ;\nEND_IF\nCASE n OF\n    1:\n    ;\nEND_CASE\nWHILE a\n    OR b DO\n    ;\nEND_WHILE\nn := 1;;\n");
            Assert.Equal(new[] { 11, 15, 19, 21 }, findings.Select(f => f.Location.Line ?? 0));
        }

        [Fact]
        public void A_result_is_assigned_on_all_paths_with_an_ELSE_or_conditions_that_leave_no_case_out_and_a_method_counts_once_it_assigns()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0075");
            var input = "VAR_INPUT\n    a : BOOL;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, "FUNCTION F : INT\n" + input + "IF a THEN\n    F := 1;\nELSIF NOT a THEN\n    F := 2;\nEND_IF;\n"));
            Assert.Single(Snippet(rule, "FUNCTION F : INT\n" + input + "IF a THEN\n    F := 1;\nELSIF a = FALSE THEN\n    F := 2;\nEND_IF;\n"));
            Assert.Single(Snippet(rule, "FUNCTION F : INT\n" + input + "IF a THEN\n    F := 1;\nELSIF NOT a AND a THEN\n    F := 2;\nEND_IF;\n"));
            Assert.Empty(Snippet(rule, "FUNCTION F : INT\n" + input + "IF a THEN\n    F := 1;\nELSE\n    F := 2;\nEND_IF;\n"));
            Assert.Single(Snippet(rule, "METHOD PUBLIC M : BOOL\n" + input + "IF a THEN\n    M := TRUE;\nEND_IF;\n"));
            Assert.Empty(Snippet(rule, "METHOD PUBLIC M : BOOL\n" + input + "a := FALSE;\n"));
        }

        [Fact]
        public void A_reference_is_guarded_inside_a_branch_that_requires_it_but_not_in_its_own_condition()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0061");
            var declarations = "PROGRAM P\nVAR\n    r : REFERENCE TO ST_Data;\n    a : BOOL;\n    n : INT;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "IF NOT __ISVALIDREF(r) THEN\n    a := FALSE;\nELSIF a THEN\n    IF __ISVALIDREF(r) AND a THEN\n        n := r.n;\n    END_IF;\nELSE\n    n := r.n;\nEND_IF;\n"));
            Assert.Single(Snippet(rule, declarations + "IF __ISVALIDREF(r) AND r.n > 0 THEN\n    n := 1;\nEND_IF;\n"));
            Assert.Single(Snippet(rule, declarations + "IF __ISVALIDREF(r) OR a THEN\n    n := r.n;\nEND_IF;\n"));
        }

        [Fact]
        public void A_pointer_is_guarded_by_a_dominating_test_or_an_early_RETURN_until_it_is_reassigned()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0060");
            var declarations = "PROGRAM P\nVAR\n    p : POINTER TO INT;\n    q : POINTER TO INT;\n    n : INT;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "IF p = 0 THEN\n    n := 0;\nELSE\n    n := p^;\nEND_IF;\nIF p <> 0 THEN\n    n := p^;\nEND_IF;\n"));
            Assert.Empty(Snippet(rule, declarations + "IF p = 0 THEN\n    RETURN;\nEND_IF;\nn := p^;\n"));
            Assert.Single(Snippet(rule, declarations + "IF p <> 0 THEN\n    p := q;\n    n := p^;\nEND_IF;\n"));
            Assert.Single(Snippet(rule, declarations + "IF p = 0 THEN\n    RETURN;\nEND_IF;\np := q;\nn := p^;\n"));
            Assert.Single(Snippet(rule, "METHOD PUBLIC M : INT\nVAR_INPUT\n    p : POINTER TO INT;\nEND_VAR\nIMPLEMENTATION\nM := p^;\n"));
        }

        [Fact]
        public void An_output_read_before_the_call_is_last_cycle_unless_the_owner_calls_the_instance()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0052");
            var declarations = "PROGRAM P\nVAR\n    t : TON;\n    a : BOOL;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Equal(new[] { "function-block instance 't' field '.Q' is read before the instance is called in this cycle" },
                Snippet(rule, declarations + "a := t.Q;\nt(IN := a, PT := T#1S);\n").Select(f => f.Message));
            Assert.Empty(Snippet(rule, declarations + "t(IN := a, PT := T#1S);\nt.IN := FALSE;\na := t.Q;\n"));
            var file = "FUNCTION_BLOCK FB_A\nVAR\n    t : R_TRIG;\nEND_VAR\n// --- implementation ---\n{0}\nEND_FUNCTION_BLOCK\n\nMETHOD M : BOOL\n// --- implementation ---\nM := t.Q;\nEND_METHOD\n";
            List<Finding> InMethod(string body)
            {
                var snapshot = Snapshot.Build(".", new Dictionary<string, string> { ["FB_A.st"] = string.Format(file, body) });
                return rule.Check(snapshot.Find("FB_A.st#FB_A.M"), new RuleContext(snapshot, new AnalyzeConfig()) { Active = rule }).ToList();
            }
            Assert.Empty(InMethod("t(CLK := TRUE);"));
            Assert.Single(InMethod(""));
        }

        [Fact]
        public void A_SEL_or_MUX_value_with_a_call_that_may_change_state_is_reported_but_conversions_are_not()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0083");
            var declarations = "PROGRAM P\nVAR\n    a : BOOL;\n    n : INT;\n    d : DINT;\n    t : TON;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "d := SEL(a, INT_TO_DINT(n), TO_DINT(ABS(n)));\n"));
            Assert.Equal(new[] { "SEL/MUX evaluates argument call(s) with possible side effects before selecting a value: Next, t" },
                Snippet(rule, declarations + "d := MUX(n, Next(n), t(IN := a), 0);\n").Select(f => f.Message));
        }

        [Fact]
        public void A_function_result_never_assigned_is_named_so()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0075");
            var input = "VAR_INPUT\n    ok : BOOL;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Equal(new[] { "FUNCTION result 'F' is never assigned; every caller gets the type's default value" },
                Snippet(rule, "FUNCTION F : INT\n" + input + "ok := NOT ok;\n").Select(f => f.Message));
            Assert.Equal(new[] { "FUNCTION result 'F' is not assigned on all control-flow paths" },
                Snippet(rule, "FUNCTION F : INT\n" + input + "IF ok THEN\n    F := 1;\nEND_IF;\n").Select(f => f.Message));
        }

        [Fact]
        public void A_call_cycle_is_reported_once_at_its_first_call()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0085");
            var input = "VAR_INPUT\n    n : INT;\nEND_VAR\nIMPLEMENTATION\n";
            var findings = Snippet(rule, "FUNCTION F : INT\n" + input + "F := G(n);\nFUNCTION G : INT\n" + input + "G := F(n - 1);\nFUNCTION H : INT\n" + input + "H := F(n);\n");
            Assert.Equal(new[] { "recursive POU call cycle detected: F -> G -> F; the fixed PLC call stack may overflow" }, findings.Select(f => f.Message));
            Assert.Single(Snippet(rule, "FUNCTION F : INT\n" + input + "F := F(n - 1);\n"));
            Assert.Empty(Snippet(rule, "FUNCTION F : INT\n" + input + "F := n;\nFUNCTION G : INT\n" + input + "G := F(n);\n"));
        }

        [Fact]
        public void A_divisor_is_guarded_by_a_comparison_ruling_out_zero_until_a_finished_reassignment()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0050");
            var declarations = "PROGRAM P\nVAR\n    x : INT;\n    y : INT;\n    s : ST_S;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, declarations + "IF x <> 0 THEN\n    x := y / x;\nEND_IF;\nIF s.n > 0 AND y > 1 THEN\n    y := y / s . n;\nEND_IF;\nIF x = 0 THEN\n    y := 0;\nELSIF y > 0 THEN\n    y := y / x;\nEND_IF;\n"));
            Assert.Empty(Snippet(rule, declarations + "IF x = 0 THEN\n    EXIT;\nEND_IF;\ny := y / x;\n"));
            Assert.Equal(new[] { "division by 'x' occurs on a branch where the divisor is proven to be zero", "division by 'x' is not protected by a simple non-zero check on this path" },
                Snippet(rule, declarations + "IF x = 0 THEN\n    y := y / x;\nEND_IF;\nIF x >= 1 THEN\n    x := y;\n    y := y / x;\nEND_IF;\n").Select(f => f.Message));
        }

        [Fact]
        public void A_local_declared_non_zero_that_no_code_changes_is_a_safe_divisor()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0050");
            var block = "FUNCTION_BLOCK FB_Scale\nVAR\n    nColumns : INT := 107;\n    nTrays : INT := 215;\n    y : INT;\nEND_VAR\nIMPLEMENTATION\ny := nTrays / nColumns;\n";
            Assert.Empty(Snippet(rule, block));
            Assert.Equal(new[] { "nColumns" }, Snippet(rule, block + "// cts:owner FB_Scale\nMETHOD tune\nIMPLEMENTATION\nnColumns := 0;\n").Select(f => f.Anchor));
            Assert.Equal(new[] { "nTrays" }, Snippet(rule, block.Replace("y := nTrays / nColumns;", "y := nColumns / nTrays;\nSetUp(ADR(nTrays));")).Select(f => f.Anchor));
            Assert.Equal(new[] { "nColumns" }, Snippet(rule, block.Replace("nColumns : INT := 107;", "nColumns : INT;")).Select(f => f.Anchor));
            Assert.Equal(new[] { "nColumns" }, Snippet(rule, "PROGRAM P\nVAR\n    nColumns : INT := 5;\n    y : INT;\nEND_VAR\nIMPLEMENTATION\ny := 10 / nColumns;\nPROGRAM Q\nVAR\nEND_VAR\nIMPLEMENTATION\nP.nColumns := 0;\n").Select(f => f.Anchor));
        }

        [Fact]
        public void A_literal_condition_is_evaluated_with_ST_precedence_and_integer_division()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0048");
            var program = "PROGRAM P\nVAR\n    x : INT;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Equal(new[] { "control-flow condition '7 / 2 = 3' is always true", "control-flow condition 'TRUE OR FALSE XOR TRUE' is always true", "control-flow condition '16#10 MOD 3 <> 1' is always false" },
                Snippet(rule, program + "IF 7 / 2 = 3 THEN\n    x := 1;\nELSIF TRUE OR FALSE XOR TRUE THEN\n    x := 2;\nEND_IF;\nWHILE 16#10 MOD 3 <> 1 DO\nEND_WHILE;\n").Select(f => f.Message));
            Assert.Empty(Snippet(rule, program + "IF TRUE THEN\n    x := 1;\nELSIF 1 AND 2 THEN\n    x := 2;\nELSIF x > 1 OR 1 / 0 = 0 THEN\n    x := 3;\nEND_IF;\n"));
        }

        [Fact]
        public void A_constant_value_out_of_its_integer_type_is_reported_where_it_is_given()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0049");
            var findings = Snippet(rule, "PROGRAM P\nVAR\n    b : BYTE := 16#100;\n    i : INT;\n    s : ST_S;\nEND_VAR\nIMPLEMENTATION\ni := 200 * 200;\ni := 7 / 2 * 10000;\ns.i := 99999;\ni := 4.0E4;\n");
            Assert.Equal(new[] { "constant expression '16#100' evaluates to 256 outside BYTE range [0..255]", "constant expression '200 * 200' evaluates to 40000 outside INT range [-32768..32767]", "constant expression '4.0E4' evaluates to 40000.0 outside INT range [-32768..32767]" },
                findings.Select(f => f.Message));
            Assert.Equal(3, findings[0].Location.Line);
        }

        [Fact]
        public void A_fraction_is_no_literal_zero_divisor()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0035");
            var findings = Snippet(rule, "PROGRAM P\nVAR\n    x : LREAL;\nEND_VAR\nIMPLEMENTATION\nx := x / 0.001;\nx := x / 0.0;\n");
            Assert.Equal(new[] { "0.0" }, findings.Select(f => f.Anchor));
        }

        [Fact]
        public void A_quote_escaped_with_a_dollar_does_not_end_a_string_before_a_case_label()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0015");
            Assert.Empty(Snippet(rule, "PROGRAM P\nVAR\n    n : INT;\n    s : STRING;\nEND_VAR\nIMPLEMENTATION\nCASE n OF\n1: s := 'at $'2023-11-14 22:13:20$' x';\n22: s := 'b';\n13: s := 'c';\nEND_CASE;\n"));
        }

        [Fact]
        public void A_field_or_an_operand_of_arithmetic_is_no_self_comparison()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0047");
            var program = "PROGRAM P\nVAR\n    r : REAL;\n    u : REAL;\n    hi : REAL;\n    lo : REAL;\n    a : ARRAY[0..1] OF ST_M;\n    i : INT;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, program + "IF a[i].r <= r THEN\n    i := 0;\nEND_IF;\nIF hi - u >= u - lo THEN\n    i := 1;\nEND_IF;\nIF NOT u = u THEN\n    i := 2;\nEND_IF;\n"));
            Assert.Equal(new[] { "r <= r" }, Snippet(rule, program + "IF r <= r THEN\n    i := 0;\nEND_IF;\n").Select(f => f.Anchor));
        }

        [Fact]
        public void A_pointer_field_read_through_a_pointer_has_the_field_type()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0091");
            var program = "PROGRAM P\nVAR\n    pAsk : POINTER TO ST_Ask;\n    pReply : POINTER TO ST_Reply;\nEND_VAR\nIMPLEMENTATION\n";
            Assert.Empty(Snippet(rule, program + "pReply := pAsk^.pReply;\n"));
            Assert.Single(Snippet(rule, program + "pReply := pAsk;\n"));
        }

        [Fact]
        public void An_early_return_on_a_flag_set_from_the_divisor_check_guards_the_division()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0050");
            var block = "FUNCTION_BLOCK FB_Lag\nVAR_INPUT\n    rC : REAL;\n    rT : REAL;\nEND_VAR\nVAR\n    y : REAL;\n    xError : BOOL;\nEND_VAR\nIMPLEMENTATION\n";
            var check = "xError := NOT (rC > 0.0) OR rT <= 0.0;\nIF xError THEN\n    RETURN;\nEND_IF;\n";
            Assert.Empty(Snippet(rule, block + check + "y := y / rC + y / rT;\n"));
            Assert.Equal(new[] { "rC" }, Snippet(rule, block + "xError := rT <= 0.0;\nIF xError THEN\n    RETURN;\nEND_IF;\ny := y / rC;\n").Select(f => f.Anchor));
            Assert.Equal(new[] { "rC" }, Snippet(rule, block + "xError := NOT (rC > 0.0);\nrC := y;\nIF xError THEN\n    RETURN;\nEND_IF;\ny := y / rC;\n").Select(f => f.Anchor));
            Assert.Equal(new[] { "rC" }, Snippet(rule, block + "IF rT > 0.0 THEN\n    xError := NOT (rC > 0.0);\nEND_IF;\nIF xError THEN\n    RETURN;\nEND_IF;\ny := y / rC;\n").Select(f => f.Anchor));
        }

        [Fact]
        public void A_method_of_a_library_interface_keeps_no_local_address()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0051");
            var text = "FUNCTION F : DINT\nVAR\n    itfAcc : IIecVarAccess3;\n    fbKeep : FB_Keep;\n    r : DINT;\nEND_VAR\n// --- implementation ---\n{0}\nEND_FUNCTION\n\nFUNCTION_BLOCK FB_Keep\n// --- implementation ---\nEND_FUNCTION_BLOCK\n";
            List<Finding> InFunction(string body)
            {
                var snapshot = Snapshot.Build(".", new Dictionary<string, string> { ["F.st"] = string.Format(text, body) });
                return rule.Check(snapshot.Find("F.st#F"), new RuleContext(snapshot, new AnalyzeConfig()) { Active = rule }).ToList();
            }
            Assert.Empty(InFunction("itfAcc.VarAccGetNode(ADR(r));"));
            Assert.Single(InFunction("fbKeep.Hold(ADR(r));"));
        }

        [Fact]
        public void A_local_address_escapes_into_the_owner_or_a_call_but_not_into_a_runtime_library_call()
        {
            var rule = RuleCatalog.All.Single(r => r.Id == "CTS0051");
            var text = "FUNCTION_BLOCK FB_A\nVAR\n    p : POINTER TO BYTE;\nEND_VAR\n// --- implementation ---\nEND_FUNCTION_BLOCK\n\nMETHOD M : BOOL\nVAR\n    b : BYTE;\n    q : POINTER TO BYTE;\n    r : DINT;\nEND_VAR\n// --- implementation ---\n{0}\nEND_METHOD\n";
            List<Finding> InMethod(string body)
            {
                var snapshot = Snapshot.Build(".", new Dictionary<string, string> { ["FB_A.st"] = string.Format(text, body) });
                return rule.Check(snapshot.Find("FB_A.st#FB_A.M"), new RuleContext(snapshot, new AnalyzeConfig()) { Active = rule }).ToList();
            }
            Assert.Equal(new[] { "address of local 'b' escapes through destination 'p'", "address of local 'b' is passed out of its lifetime through a call" },
                InMethod("p := ADR(b);\nq := ADR(b);\nM := Keep(ADR(b));").Select(f => f.Message));
            Assert.Empty(InMethod("sysfile.SysFileOpen(szFile := 'a', pResult := ADR(r));\nMEMCPY(ADR(b), p, 1);"));
        }

        [Fact]
        public void A_fingerprint_is_the_one_the_Python_analyzer_wrote()
        {
            Assert.Equal("cts1:7fbdb1329a93fd22c45f02ba350f328713974c00", Fingerprints.Of("CTS0013", "POUs/FB_A.st#FB_A", "nCount", "nCount : INT  ", 0));
            Assert.Equal("cts1:f9181f0c3c13aa57125307a3bf8d1074c704ee37", Fingerprints.Of("CTS0001", "a.st#a", "x := \"1\";\tq", "x  :=  1; — OK\u0001", 2));
            Assert.Equal("\"\u2028\u00e9\"", Fingerprints.Quote("\u2028\u00e9"));
        }

        [Fact]
        public void A_file_with_a_function_block_and_its_methods_gives_one_unit_each_with_the_file_lines()
        {
            var text = "FUNCTION_BLOCK FB_Log\nVAR\n    n : INT;\nEND_VAR\n// --- implementation ---\nn := n + 1;\nEND_FUNCTION_BLOCK\n\nMETHOD Add : BOOL\nVAR_INPUT\n    x : INT;\nEND_VAR\n// --- implementation ---\nAdd := x > 0;\nEND_METHOD\n";
            var snapshot = Snapshot.Build(".", new Dictionary<string, string> { ["POUs/FB_Log.st"] = text });
            Assert.Equal(new[] { "POUs/FB_Log.st#FB_Log", "POUs/FB_Log.st#FB_Log.Add" }, snapshot.Units.Select(unit => unit.Id));
            var method = snapshot.Find("POUs/FB_Log.st#FB_Log.Add");
            Assert.Equal(Kinds.Method, method.Kind);
            Assert.Equal("FB_Log", method.OwnerName);
            Assert.Equal(snapshot.Find("POUs/FB_Log.st#FB_Log").Id, method.OwnerId);
            var finding = Finding.In(method, "x", method.Text.IndexOf("Add :=", StringComparison.Ordinal));
            Assert.Equal(14, finding.Location.Line);
        }

        [Fact]
        public void Analyze_reports_findings_writes_sarif_and_honours_the_baseline()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analyze-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "POUs"));
            try
            {
                File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "PRG_Main.st"),
                    "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    nUnused : INT;\n    n       : INT;\nEND_VAR\n// --- implementation ---\nn := n + 1;\n// n := 0;\n");
                var sarif = Path.Combine(folder, "out.sarif");
                var (code, output, _) = CliTests.RunLocal("analyze", "--workspace", folder, "--sarif", sarif);
                Assert.Equal(1, code);
                Assert.True(output.StartsWith("error analyze findings=2 danger=0 suspicious=2 style=0 diagnostics=0 fail_on=suspicious"), output);
                Assert.True(output.Contains("[CTS0001] suspicious  POUs/PRG_Main.st:9:1  commented-out code: n := 0;"), output);
                Assert.Contains("[CTS0013] suspicious  POUs/PRG_Main.st:4:5  declared symbol 'nUnused'", output);
                Assert.EndsWith("\nby rule: CTS0001 1, CTS0013 1\n", output);
                Assert.Contains("\"ruleId\": \"CTS0013\"", File.ReadAllText(sarif));
                var (dangerOnly, danger, _) = CliTests.RunLocal("analyze", "--workspace", folder, "--severity", "danger");
                Assert.Equal(0, dangerOnly);
                Assert.StartsWith("ok analyze findings=0 danger=0 suspicious=0 style=0", danger);

                Assert.Equal(0, CliTests.RunLocal("analyze", "baseline", "create", "--workspace", folder).code);
                var (after, quiet, _) = CliTests.RunLocal("analyze", "--workspace", folder);
                Assert.Equal(0, after);
                Assert.Contains("ok analyze findings=0", quiet);
                Assert.Contains("baselined=2", quiet);
                var (_, check, _) = CliTests.RunLocal("analyze", "baseline", "check", "--workspace", folder);
                Assert.Contains("ok analyze-baseline action=check findings=2 baselined=2 new=0 stale=0", check);

                var (onlyOne, one, _) = CliTests.RunLocal("analyze", "--workspace", folder, "--rule", "cts0001", "--json");
                Assert.Equal(0, onlyOne);
                Assert.Contains("\"rules_run\": [\n      \"CTS0001\"\n    ]", one);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Analyze_path_keeps_the_findings_of_one_folder_and_still_reads_the_rest()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analyze-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "POUs"));
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "Globals"));
            try
            {
                File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "PRG_Main.st"),
                    "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    nUnused : INT;\nEND_VAR\n// --- implementation ---\nGVL_A.nUsed := GVL_A.nUsed + 1;\n// GVL_A.nUsed := 0;\n");
                File.WriteAllText(Path.Combine(folder, "project-view", "Globals", "GVL_A.st"), "VAR_GLOBAL\n    nUsed  : INT;\n    nSpare : INT;\nEND_VAR\n");
                string Findings(params string[] paths)
                {
                    var args = new List<string> { "analyze", "--workspace", folder, "--fail-on", "never" };
                    foreach (var path in paths) args.AddRange(new[] { "--path", path });
                    var (code, output, _) = CliTests.RunLocal(args.ToArray());
                    Assert.True(code == 0, output);
                    return string.Join("\n", output.Split('\n').Where(line => line.Contains("[CTS")).Select(line => line.Trim()));
                }
                // GVL_A.nUsed is read in POUs/, which is still analyzed.
                var globals = "[CTS0013] suspicious  Globals/GVL_A.st:3:5  declared symbol 'nSpare' has no explicit reference in the analyzed Structured Text";
                Assert.Equal(globals, Findings("Globals"));
                Assert.Equal(globals, Findings(Path.Combine(folder, "project-view", "Globals", "GVL_A.st")));
                Assert.Contains("POUs/PRG_Main.st", Findings("POUs/"));
                Assert.DoesNotContain("Globals/", Findings("POUs/"));
                Assert.Contains("Globals/", Findings(Path.Combine(folder, "project-view")));
                Assert.Contains("\nby rule: CTS0013 2, CTS0001 1\n", CliTests.RunLocal("analyze", "--workspace", folder, "--fail-on", "never").output);
                Assert.Equal(globals, Findings("Globals" + Path.DirectorySeparatorChar + "\""));
                var (refused, said, error) = CliTests.RunLocal("analyze", "--workspace", folder, "--path", "Global");
                Assert.True(refused == 2, said);
                Assert.Contains("--path Global names no file or folder in the view", said + error);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Analyze_changed_keeps_the_findings_of_the_files_changed_since_the_last_commit()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analyze-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "POUs"));
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "Globals"));
            try
            {
                var main = Path.Combine(folder, "project-view", "POUs", "PRG_Main.st");
                File.WriteAllText(main, "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    nUnused : INT;\nEND_VAR\n// --- implementation ---\nGVL_A.nUsed := GVL_A.nUsed + 1;\n");
                File.WriteAllText(Path.Combine(folder, "project-view", "Globals", "GVL_A.st"), "VAR_GLOBAL\n    nUsed  : INT;\n    nSpare : INT;\nEND_VAR\n");
                string Run()
                {
                    var (code, output, error) = CliTests.RunLocal("analyze", "--workspace", folder, "--fail-on", "never", "--changed");
                    Assert.True(code == 0, output + error);
                    return output;
                }
                var (refused, said, why) = CliTests.RunLocal("analyze", "--workspace", folder, "--changed");
                Assert.True(refused == 2, said);
                Assert.Contains("--changed needs the view in a git repository", said + why);
                Git(folder, "init -q");
                Assert.Contains(" changed_files=2", Run().Split('\n')[0]);
                Git(folder, "add -A");
                Git(folder, "-c user.name=Fixture -c user.email=fixture@localhost commit -qm first");
                Assert.StartsWith("ok analyze findings=0 ", Run());
                File.AppendAllText(main, "// GVL_A.nUsed := 0;\n");
                File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "PRG_New.st"), "// New program documentation.\nPROGRAM PRG_New\nVAR\n    nIdle : INT;\nEND_VAR\n// --- implementation ---\n");
                var output = Run();
                Assert.Contains(" changed_files=2", output.Split('\n')[0]);
                Assert.Contains("[CTS0001] suspicious  POUs/PRG_Main.st:8:1", output);
                Assert.Contains("[CTS0013] suspicious  POUs/PRG_New.st:4:5", output);
                Assert.DoesNotContain("Globals/", output);
            }
            finally
            {
                foreach (var file in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories)) File.SetAttributes(file, FileAttributes.Normal);
                Directory.Delete(folder, true);
            }
        }

        static void Git(string folder, string args) => GitRepository.Run(folder, args);

        [Fact]
        public void Analyze_leaves_out_an_object_excluded_from_the_build_with_its_members()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analyze-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "POUs"));
            try
            {
                File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "PRG_Main.st"),
                    "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    n : INT;\nEND_VAR\n// --- implementation ---\nn := n + 1;\n// n := 0;\nEND_PROGRAM\n");
                File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "FB_Old.st"),
                    "(* cds-text-sync: ExcludeFromBuild *)\nFUNCTION_BLOCK FB_Old\nVAR\n    nUnused : INT;\nEND_VAR\n// --- implementation ---\n// nUnused := 0;\nEND_FUNCTION_BLOCK\n\n"
                    + "METHOD M_Old : BOOL\n// --- implementation ---\n// M_Old := TRUE;\nEND_METHOD\n");
                var (code, output, _) = CliTests.RunLocal("analyze", "--workspace", folder);
                Assert.True(code == 1, output);
                Assert.StartsWith("error analyze findings=1 ", output);
                Assert.Contains(" excluded=1", output.Split('\n')[0]);
                Assert.Contains("[CTS0001] suspicious  POUs/PRG_Main.st:8:1", output);
                Assert.DoesNotContain("FB_Old", output);
                var summary = (IDictionary<string, object>)((IDictionary<string, object>)Json.Parse(CliTests.RunLocal("analyze", "--workspace", folder, "--json").output))["summary"];
                Assert.Equal(1, Convert.ToInt32(summary["excluded_from_build"]));
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Analyze_takes_its_settings_from_the_sync_folder_and_refuses_a_wrong_one()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analyze-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "POUs"));
            try
            {
                File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "PRG_Main.st"),
                    "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    nUnused : INT;\nEND_VAR\n// --- implementation ---\n// n := 0;\n");
                File.WriteAllText(Path.Combine(folder, "cds-text-sync.json"), "{\"analyze\": {\"fail_on\": \"danger\", \"rules\": {\"CTS0013\": {\"enabled\": false}}}}");
                var (code, output, _) = CliTests.RunLocal("analyze", "--workspace", folder);
                Assert.Equal(0, code);
                Assert.Contains("ok analyze findings=2 ", output);
                Assert.Contains("fail_on=danger", output);
                Assert.Equal(1, CliTests.RunLocal("analyze", "--workspace", folder, "--fail-on", "style").code);
                Assert.Equal(0, CliTests.RunLocal("analyze", "--workspace", folder, "--fail-on", "never").code);
                var analyzed = (IDictionary<string, object>)Json.Parse(CliTests.RunLocal("analyze", "--workspace", folder, "--json").output);
                Assert.Equal(Path.GetFullPath(folder), analyzed["workspace"]);
                Assert.Equal(Path.Combine(Path.GetFullPath(folder), "project-view"), analyzed["project_view"]);
                var rules = (IDictionary<string, object>)Json.Parse(CliTests.RunLocal("analyze", "rules", "--workspace", folder, "--doc", "--json").output);
                Assert.Equal(Path.GetFullPath(folder), rules["workspace"]);
                var unused = ((IList<object>)rules["rules"]).Cast<IDictionary<string, object>>().Single(rule => Equals(rule["id"], "CTS0013"));
                Assert.Equal(false, unused["enabled"]);
                Assert.Contains("```st bad", (string)unused["doc"]);

                File.WriteAllText(Path.Combine(folder, "cds-text-sync.json"), "{\"analyze\": {\"rules\": {\"CTS9999\": {}}}}");
                var (refused, _, error) = CliTests.RunLocal("analyze", "--workspace", folder);
                Assert.Equal(2, refused);
                Assert.Contains("unknown rule: CTS9999", error);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Rules_enable_and_disable_write_the_switch_and_keep_the_rest_of_the_settings()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analyze-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view"));
            try
            {
                File.WriteAllText(Path.Combine(folder, "cds-text-sync.json"), "{\"profile\": \"default\", \"analyze\": {\"rules\": {\"CTS0013\": {\"severity\": \"style\"}}}}");
                var (code, output, _) = CliTests.RunLocal("analyze", "rules", "--workspace", folder, "--disable", "cts0013", "--enable", "CTS0001");
                Assert.Equal(0, code);
                Assert.StartsWith("ok analyze-rules rules=", output);
                Assert.Contains("CTS0013=off", output);
                Assert.Contains("CTS0001=on", output);
                var settings = (IDictionary<string, object>)Json.Parse(File.ReadAllText(Path.Combine(folder, "cds-text-sync.json")));
                Assert.Equal("default", settings["profile"]);
                var rules = (IDictionary<string, object>)((IDictionary<string, object>)settings["analyze"])["rules"];
                Assert.Equal("style", ((IDictionary<string, object>)rules["CTS0013"])["severity"]);
                Assert.Equal(false, ((IDictionary<string, object>)rules["CTS0013"])["enabled"]);
                Assert.Equal(true, ((IDictionary<string, object>)rules["CTS0001"])["enabled"]);

                var (unknown, _, said) = CliTests.RunLocal("analyze", "rules", "--workspace", folder, "--enable", "CTS9999");
                Assert.Equal(2, unknown);
                Assert.Contains("unknown rule CTS9999", said);
                var (twice, _, both) = CliTests.RunLocal("analyze", "rules", "--workspace", folder, "--enable", "CTS0001", "--disable", "CTS0001");
                Assert.Equal(2, twice);
                Assert.Contains("CTS0001 is both enabled and disabled", both);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Explain_shows_the_rule_document_and_rules_lists_the_catalog()
        {
            var (code, output, _) = CliTests.RunLocal("analyze", "explain", "cts0013");
            Assert.Equal(0, code);
            Assert.Contains("CTS0013 - Declared symbol not referenced", output);
            Assert.Contains("```st bad", output);
            var (_, rules, _) = CliTests.RunLocal("analyze", "rules");
            Assert.Contains("CTS0001 [suspicious] Commented-out code", rules);
            Assert.Equal(2, CliTests.RunLocal("analyze", "explain", "CTS9999").code);
        }

        [Fact]
        public void A_copy_larger_than_its_destination_is_reported_and_a_matching_size_is_not()
        {
            var rule = RuleCatalog.All.Single(candidate => candidate.Id == "CTS0063");
            Assert.Single(Snippet(rule, "PROGRAM Main\nVAR\n    smallBuffer : ARRAY[0..3] OF BYTE;\n    source : ARRAY[0..7] OF BYTE;\nEND_VAR\nIMPLEMENTATION\nMEMCPY(ADR(smallBuffer), ADR(source), SIZEOF(source));\n"));
            Assert.Empty(Snippet(rule, "PROGRAM Main\nVAR\n    destination : ARRAY[0..7] OF BYTE;\n    source : ARRAY[0..7] OF BYTE;\nEND_VAR\nIMPLEMENTATION\nMEMCPY(ADR(destination), ADR(source), SIZEOF(destination));\n"));
        }

        [Fact]
        public void A_CONCAT_longer_than_its_target_string_is_reported()
        {
            var rule = RuleCatalog.All.Single(candidate => candidate.Id == "CTS0080");
            Assert.Single(Snippet(rule, "PROGRAM Main\nVAR\n    prefix : STRING(8);\n    suffix : STRING(8);\n    message : STRING(10);\nEND_VAR\nIMPLEMENTATION\nmessage := CONCAT(prefix, suffix);\n"));
            Assert.Empty(Snippet(rule, "PROGRAM Main\nVAR\n    prefix : STRING(8);\n    suffix : STRING(8);\n    message : STRING(16);\nEND_VAR\nIMPLEMENTATION\nmessage := CONCAT(prefix, suffix);\n"));
            Assert.Equal(new[] { "CONCAT result can contain 11 characters but message is limited to STRING(10)" },
                Snippet(rule, "PROGRAM Main\nVAR\n    prefix : STRING(8);\n    message : STRING(10);\nEND_VAR\nIMPLEMENTATION\nmessage := CONCAT(prefix, ', $N');\nmessage := CONCAT(prefix, '$N');\n").Select(f => f.Message));
        }

        [Fact]
        public void A_call_a_referenced_library_can_hold_is_not_unresolved()
        {
            var rule = RuleCatalog.All.Single(candidate => candidate.Id == "CTS0053");
            var snapshot = Snapshot.Build(".", new Dictionary<string, string>
            {
                ["Main.st"] = "PROGRAM Main\nVAR\n    t : ULINT;\nEND_VAR\nIMPLEMENTATION\nt := SysTimeGetNs();\nIecTaskResetStatistics();\nDED.GetStatus();\nMissingCall();\nTimeGetNs();\n",
            });
            snapshot.Libraries.Add(new Cts.Docs.LibraryReference { Name = "SysTimeCore", Namespace = "SysTimeCore" });
            snapshot.Libraries.Add(new Cts.Docs.LibraryReference { Name = "CmpIecTask", Namespace = "CmpIecTask" });
            snapshot.Libraries.Add(new Cts.Docs.LibraryReference { Name = "CAA Device Diagnosis", Namespace = "DED" });
            var context = new RuleContext(snapshot, new AnalyzeConfig()) { Active = rule };
            Assert.Equal(new[] { "MissingCall", "TimeGetNs" }, rule.Check(context).Select(finding => finding.Anchor));
        }

        [Fact]
        public void FB_Init_calling_an_overridden_method_is_reported_but_not_through_SUPER()
        {
            var rule = RuleCatalog.All.Single(candidate => candidate.Id == "CTS0090");
            const string header = "METHOD FB_Init : BOOL\n// cts:owner FB_Base\n// cts:fb FB_Base\n// cts:fb FB_Derived extends FB_Base\n// cts:method FB_Base: Configure\n// cts:method FB_Derived: Configure\n";
            Assert.Single(Snippet(rule, header + "IMPLEMENTATION\nConfigure();\nEND_METHOD\n"));
            Assert.Single(Snippet(rule, header + "IMPLEMENTATION\nTHIS^.Configure();\nConfigure();\nEND_METHOD\n"));
            Assert.Empty(Snippet(rule, header + "IMPLEMENTATION\nSUPER^.Configure();\nSUPER^. Configure();\nEND_METHOD\n"));
        }
    }
}
