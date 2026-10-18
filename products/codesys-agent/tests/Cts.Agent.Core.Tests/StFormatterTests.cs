using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class StFormatterTests
    {
        [Fact]
        public void AlignsDeclarationNames()
        {
            const string source = "VAR\na : BOOL;\nlong_name : INT;\nEND_VAR";
            Assert.Equal("VAR\na         : BOOL;\nlong_name : INT;\nEND_VAR", StFormatter.Format(source, true));
        }

        [Fact]
        public void IndentsNestedBlocks()
        {
            const string source = "IF ready THEN\nrun();\nEND_IF";
            Assert.Equal("IF ready THEN\n    run();\nEND_IF", StFormatter.Format(source, false));
        }

        [Fact]
        public void KeepsCrLf()
        {
            const string source = "IF ready THEN\r\nrun();\r\nEND_IF";
            Assert.Equal("IF ready THEN\r\n    run();\r\nEND_IF", StFormatter.Format(source, false));
        }

        [Fact]
        public void SplitsTopLevelLogicalConditions()
        {
            const string source = "IF ready AND (a OR b) THEN\nrun();\nEND_IF";
            Assert.Equal("IF ready\n    AND (a OR b)\nTHEN\n    run();\nEND_IF", StFormatter.Format(source, false));
        }

        [Fact]
        public void KeepsLogicalWordsInsideStringsCommentsAndParentheses()
        {
            const string source = "IF text = 'a AND b' AND (ready OR forced) THEN // AND ignored\nrun();\nEND_IF";
            Assert.Equal("IF text = 'a AND b'\n    AND (ready OR forced)\nTHEN // AND ignored\n    run();\nEND_IF", StFormatter.Format(source, false));
        }

        [Fact]
        public void AlignsCaseLabelsAndKeepsContinuationIndent()
        {
            const string source = "CASE state OF\n1:\nresult := first +\nsecond;\n2:\nresult := other;\nEND_CASE";
            Assert.Equal("CASE state OF\n1:\n    result := first +\n    second;\n2:\n    result := other;\nEND_CASE", StFormatter.Format(source, false));
        }

        [Fact]
        public void A_tab_reaches_the_column_four_spaces_do()
        {
            const string source = "CASE s OF\n    1:\n\t\tx := 1;\n\t\tIF a THEN\n\t\t\ty := 2;\n\t\tEND_IF\nEND_CASE";
            Assert.Equal(source, StFormatter.Format(source, false));
        }

        [Fact]
        public void SplitsInlineElseStatements()
        {
            const string source = "IF ready THEN\nrun();\nELSE stop();\nEND_IF";
            Assert.Equal("IF ready THEN\n    run();\nELSE\n    stop();\nEND_IF", StFormatter.Format(source, false));
        }

        [Fact]
        public void PutsEachStatementOnItsOwnLine()
        {
            const string source = "IF fault THEN\nrun := FALSE;   fault := TRUE; // both\nEND_IF\nmsg := 'a; b'; f(x := 1; );";
            Assert.Equal("IF fault THEN\n    run := FALSE;\n    fault := TRUE; // both\nEND_IF\nmsg := 'a; b';\nf(x := 1; );", StFormatter.Format(source, false));
        }

        [Fact]
        public void BreaksAConditionWithTheTextsOwnIndent()
        {
            const string source = "IF a THEN\n\tIF ready AND go THEN\n\t\trun();\n\tEND_IF\nEND_IF";
            Assert.Equal("IF a THEN\n\tIF ready\n\t\tAND go\n\tTHEN\n\t\trun();\n\tEND_IF\nEND_IF", StFormatter.Format(source, false));
        }

        [Fact]
        public void KeepsABlockOnOneLineAsItIs()
        {
            const string source = "IF a THEN b := 1; c := 2; END_IF";
            Assert.Equal(source, StFormatter.Format(source, false));
        }

        [Fact]
        public void A_declaration_table_aligned_with_tabs_stays()
        {
            const string source = "VAR\n\tcount\t\t: INT;\t// items\n\tnext_state\t: INT;\t// after\nEND_VAR";
            Assert.Equal(source, StFormatter.Format(source, true));
        }

        [Fact]
        public void An_unaligned_table_aligns_to_its_longest_name()
        {
            const string source = "VAR\n\tcount\t\t: INT;\n\tnext_state : INT;\nEND_VAR";
            Assert.Equal("VAR\n\tcount      : INT;\n\tnext_state : INT;\nEND_VAR", StFormatter.Format(source, true));
        }

        [Fact]
        public void A_column_most_rows_share_stays_and_a_long_row_stays_apart()
        {
            const string source = "VAR\n    state   : INT;    // now\n    next    : INT;    // then\n    mode    : INT;    // how\n    address : IPv4 := (ip := host); // where\n    n : INT; // count\nEND_VAR";
            Assert.Equal("VAR\n    state   : INT;    // now\n    next    : INT;    // then\n    mode    : INT;    // how\n    address : IPv4 := (ip := host); // where\n    n       : INT;    // count\nEND_VAR", StFormatter.Format(source, true));
        }

        [Fact]
        public void AlignsTrailingDeclarationComments()
        {
            const string source = "VAR\na : BOOL; // first\nlong_name : INT; // second\nEND_VAR";
            Assert.Equal("VAR\na         : BOOL;  // first\nlong_name : INT;   // second\nEND_VAR", StFormatter.Format(source, true));
        }

        [Fact]
        public void CountsChangedRunsByTheirLongerSide()
        {
            const string before = "IF a AND b THEN\nx := 1;\nEND_IF\ny := 2;\nz := 3;\n";
            const string after = "IF a\n    AND b\nTHEN\n    x := 1;\nEND_IF\ny := 2;\nz := 3;\n";
            Assert.Equal(4, Cts.Cli.FmtCommand.ChangedLines(before, after));
        }

        [Fact]
        public void CountsAFewChangedLinesOfAHugeObjectWithoutASquareTable()
        {
            var lines = Enumerable.Range(0, 60000).Select(i => "x" + i + " := " + i + ";").ToList();
            var before = string.Join("\n", lines);
            lines[30000] = "x30000 := 0;";
            Assert.Equal(1, Cts.Cli.FmtCommand.ChangedLines(before, string.Join("\n", lines)));
            Assert.Equal(0, Cts.Cli.FmtCommand.ChangedLines(before, before));
        }

        [Fact]
        public void AWriteInAProjectWithASyncFolderPointsToSync()
        {
            var data = new Dictionary<string, object> { { "objects", 1 }, { "to_fix", 1 }, { "lines", 3 }, { "items", new List<object>() }, { "written", 1 }, { "sync_folder", @"C:\work" } };
            Assert.Equal("Next: only the IDE changed; cts sync writes the new layout into the sync folder's files", Cts.Cli.FmtCommand.Build(data).Details.Last());
            data.Remove("sync_folder");
            Assert.Empty(Cts.Cli.FmtCommand.Build(data).Details);
        }
    }
}
