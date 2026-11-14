using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Xunit;
using Cts.Sync;
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
        public void A_project_without_a_global_text_list_gets_one_import_can_create()
        {
            File.Delete(Path.Combine(root, "POUs", "GlobalTextList.csv"));
            var log = new List<string>();
            Assert.Equal("1", TextListWriter.Allocate(root, "Start", log.Add));
            Assert.Equal("2", TextListWriter.Allocate(root, "Stop", log.Add));
            Assert.Equal(new[] { "[OK] Created POUs/GlobalTextList: cts import brings it into the IDE" }, log);
            Assert.Equal(new[] { "TextID,TextDefault", "1,Start", "2,Stop" }, File.ReadAllLines(Path.Combine(root, "POUs", "GlobalTextList.csv")));
            var xml = File.ReadAllText(Path.Combine(root, "POUs", "GlobalTextList.xml"));
            var guids = XDocument.Parse(xml).Descendants().Where(element => (string)element.Attribute("Type") == "System.Guid").ToDictionary(element => (string)element.Attribute("Name"), element => element.Value);
            Assert.Equal("b5430773-3042-47d6-a6d3-28650a6ce532", guids["Guid"]);
            Assert.Equal("63784cbb-9ba0-45e6-9d69-babf3f040511", guids["TypeGuid"]);
            Assert.Equal(3, new[] { guids["GuidInit"], guids["GuidReInit"], guids["GuidExitX"] }.Select(Guid.Parse).Distinct().Count());
            // What import hands the IDE when it creates the list.
            Assert.Contains("Stop", TextListRows.With(xml, Csv()));
        }

        [Fact]
        public void A_missing_csv_beside_the_list_keeps_its_xml()
        {
            File.Delete(Path.Combine(root, "POUs", "GlobalTextList.csv"));
            File.WriteAllText(Path.Combine(root, "POUs", "GlobalTextList.xml"), "<kept/>");
            Assert.Equal("1", TextListWriter.Allocate(root, "Start", _ => { }));
            Assert.Equal("<kept/>", File.ReadAllText(Path.Combine(root, "POUs", "GlobalTextList.xml")));
        }
    }
}
