using System;
using System.IO;
using Xunit;
using Cts.Visu;

namespace Cts.Agent.Tests
{
    public class TextListWriterTests : IDisposable
    {
        readonly string root = Path.Combine(Path.GetTempPath(), "cts-textlist-" + Guid.NewGuid().ToString("N"));

        public TextListWriterTests()
        {
            Directory.CreateDirectory(Path.Combine(root, "POUs"));
            File.WriteAllText(Path.Combine(root, "POUs", "GlobalTextList.csv"), "TextID,TextDefault\n");
        }

        public void Dispose()
        {
            Directory.Delete(root, true);
        }

        string Csv() => File.ReadAllText(Path.Combine(root, "POUs", "GlobalTextList.csv"));

        [Fact]
        public void New_text_gets_an_id_and_is_quoted_in_the_csv()
        {
            Assert.Equal("1", TextListWriter.Allocate(root, "Tea, <hot> & \"fresh\"", _ => { }));
            Assert.Contains("1,\"Tea, <hot> & \"\"fresh\"\"\"", Csv());
        }

        [Fact]
        public void Existing_text_reuses_its_id_and_new_text_increments_it()
        {
            File.WriteAllText(Path.Combine(root, "POUs", "GlobalTextList.csv"), "TextID,TextDefault,en\n7,Ready,Ready\n");
            Assert.Equal("7", TextListWriter.Allocate(root, "Ready", _ => { }));
            Assert.Equal("8", TextListWriter.Allocate(root, "Stopped", _ => { }));
            Assert.Equal("8", TextListWriter.Allocate(root, "Stopped", _ => { }));
            Assert.Equal(new[] { "TextID,TextDefault,en", "7,Ready,Ready", "8,Stopped," }, File.ReadAllLines(Path.Combine(root, "POUs", "GlobalTextList.csv")));
        }

        [Fact]
        public void A_missing_csv_is_a_warning()
        {
            File.Delete(Path.Combine(root, "POUs", "GlobalTextList.csv"));
            string warning = null;
            Assert.Equal("1", TextListWriter.Allocate(root, "Start", text => warning = text));
            Assert.Contains("GlobalTextList.csv not found", warning);
        }
    }
}
