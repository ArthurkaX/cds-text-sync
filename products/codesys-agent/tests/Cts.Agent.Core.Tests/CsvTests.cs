using System.Text;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CsvTests
    {
        [Fact]
        public void A_row_written_reads_back_as_it_was()
        {
            var values = new[] { "Id1", "a, b", "say \"hi\"", "two\nlines", "" };
            var text = new StringBuilder();
            Csv.AppendRow(text, new[] { "TextID", "TextDefault", "en", "de", "fr" });
            Csv.AppendRow(text, values);

            var rows = Csv.Parse("﻿" + text.ToString().Replace("\n" + "Id1", "\r\n\r\nId1"));

            Assert.Equal(2, rows.Count);
            Assert.Equal(new[] { "TextID", "TextDefault", "en", "de", "fr" }, rows[0]);
            Assert.Equal(values, rows[1]);
        }
    }
}
