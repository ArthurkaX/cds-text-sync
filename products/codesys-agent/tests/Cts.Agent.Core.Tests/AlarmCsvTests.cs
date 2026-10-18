using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class AlarmCsvTests
    {
        const string Folder = "c0a56ce5-14a3-4757-ac56-3eab44c974b3";
        const string GroupType = "21f4ed1d-ec95-4666-820e-4abf64d93d6b";
        const string ListType = "2bef0454-1bd3-412a-ac2c-af0f31dbc40f";
        const string FolderGuid = "a1000000-0000-0000-0000-000000000000";
        const string GroupGuid = "b2000000-0000-0000-0000-000000000000";
        const string MessagesGuid = "c3000000-0000-0000-0000-000000000000";
        const string TextsGuid = "d4000000-0000-0000-0000-000000000000";

        const string Expected = "AlarmID,Message,Message (de),Expression,Comparison,ExpressionToCompare,AlarmClass,LatchVariable1,LatchVariable2,Deactivation,MinPendingTime,OffDelayTime,HigherPrioAlarm,AdditionalMessageIDs\n"
            + "0,Pump fault,Pumpenfehler,GVL.xFault,Equal,TRUE,Error,,,,,,,\n"
            + "1,Low level,,GVL.xLow,Equal,TRUE,Warning,,,,,,,\n";

        [Fact]
        public void An_alarm_group_csv_carries_its_messages_and_their_list_has_no_csv()
        {
            var files = Render(Model());
            var csvs = files.Paths.Where(path => path.EndsWith(".csv", StringComparison.Ordinal)).OrderBy(path => path, StringComparer.Ordinal).ToList();
            Assert.Equal(new[] { "Pumps__b2000000.csv", "Texts.csv" }, csvs);
            Assert.Equal(Expected, Read(files, csvs[0]).Replace("\r\n", "\n"));
        }

        [Fact]
        public void A_text_list_xml_has_no_rows_but_the_message_lists_keeps_them()
        {
            var files = Render(Model());
            string Xml(string guid) => files.Paths.Where(path => path.EndsWith(".xml", StringComparison.Ordinal)).Select(path => Read(files, path)).Single(xml => xml.Contains(guid) && xml.Contains(">" + ListType + "<"));
            Assert.DoesNotContain("TextDefault", Xml(TextsGuid));
            Assert.Contains("<List Name=\"TextList\" Type=\"System.Collections.ArrayList\" />", Xml(TextsGuid));
            Assert.Contains("Pumpenfehler", Xml(MessagesGuid));
        }

        [Fact]
        public void A_text_lists_rows_come_back_from_its_csv()
        {
            var entry = Model().Nodes[MessagesGuid].Entry;
            var csv = Encoding.UTF8.GetString(ViewExport.CsvBytes(entry, null));
            var rowless = TextListRows.Without(entry).ToString(SaveOptions.DisableFormatting);
            Assert.DoesNotContain("TextDefault", rowless);
            static IEnumerable<string> Cells(XElement root) => root.Descendants().Where(element => (string)element.Attribute("Name") == "TextList")
                .SelectMany(list => list.Descendants()).Where(element => !element.HasElements).Select(element => element.Value);
            Assert.Equal(Cells(entry).OrderBy(cell => cell), Cells(XElement.Parse(TextListRows.With(rowless, csv))).OrderBy(cell => cell));
            // The IDE holds row 1 first; the file lists them by TextID.
            Assert.True(csv.IndexOf("\n0,", StringComparison.Ordinal) < csv.IndexOf("\n1,", StringComparison.Ordinal));
            Assert.Null(TextListRows.With(rowless, "ID,TextDefault\n1,One\n"));
        }

        [Fact]
        public void A_partial_render_fetches_a_group_and_its_messages_together()
        {
            var model = Model();
            Assert.Contains(GroupGuid, ViewExport.ExpandFetchGuids(model, new[] { MessagesGuid }));
            Assert.Contains(MessagesGuid, ViewExport.ExpandFetchGuids(model, new[] { GroupGuid }));
            Assert.DoesNotContain(GroupGuid, ViewExport.ExpandFetchGuids(model, new[] { TextsGuid }));
        }

        [Fact]
        public void An_edited_message_becomes_the_message_lists_fields()
        {
            var plan = ImportCommand.PlanAlarmMessages(Expected.Replace("Low level,,", "Tank low,Tank leer,"), Encoding.UTF8.GetBytes(Expected), Leaves());
            Assert.Null(plan.Error);
            Assert.Equal(new Dictionary<string, string> { { "TextList[0].TextDefault", "Tank low" }, { "TextList[0].LanguageTexts[0]", "Tank leer" } }, plan.DiskLeaves);
        }

        [Theory]
        [InlineData("GVL.xLow,Equal", "GVL.xEmpty,Equal", "alarm 1 differs outside its message")]
        [InlineData("1,Low level,,GVL.xLow,Equal,TRUE,Warning,,,,,,,\n", "", "other alarms than the IDE")]
        [InlineData("Message (de)", "Message (fr)", "Message columns")]
        public void Anything_but_a_message_is_left_to_the_ide(string from, string to, string reason)
        {
            var plan = ImportCommand.PlanAlarmMessages(Expected.Replace(from, to), Encoding.UTF8.GetBytes(Expected), Leaves());
            Assert.Contains(reason, plan.Error);
        }

        static IDictionary<string, object> Leaves() => new Dictionary<string, object>
        {
            { "Languages[0]", "de" },
            { "TextList[0].TextID", "1" }, { "TextList[0].TextDefault", "Low level" }, { "TextList[0].LanguageTexts[0]", "" },
            { "TextList[1].TextID", "0" }, { "TextList[1].TextDefault", "Pump fault" }, { "TextList[1].LanguageTexts[0]", "Pumpenfehler" },
        };

        static ProjectModel Model()
        {
            return SnapshotReader.FromSkeleton(new[]
            {
                new SnapshotNodeFields { Guid = FolderGuid, Name = "Alarm Configuration", Type = Folder, Path = new List<string>(), Entry = Entry(FolderGuid, null, "Alarm Configuration", Folder, "") },
                new SnapshotNodeFields { Guid = GroupGuid, ParentGuid = FolderGuid, Name = "Pumps", Type = GroupType, Path = new List<string>(), Entry = Entry(GroupGuid, FolderGuid, "Pumps", GroupType, Group()) },
                new SnapshotNodeFields { Guid = MessagesGuid, ParentGuid = FolderGuid, Name = "Pumps", Type = ListType, Path = new List<string>(), Entry = Entry(MessagesGuid, FolderGuid, "Pumps", ListType, List(new[] { "de" }, new[] { "1", "Low level", "" }, new[] { "0", "Pump fault", "Pumpenfehler" })) },
                new SnapshotNodeFields { Guid = TextsGuid, ParentGuid = FolderGuid, Name = "Texts", Type = ListType, Path = new List<string>(), Entry = Entry(TextsGuid, FolderGuid, "Texts", ListType, List(new string[0], new[] { "7", "Seven" })) },
            }, "");
        }

        static MemoryViewFiles Render(ProjectModel model)
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-alarm-csv-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var files = new MemoryViewFiles();
                ViewExport.WriteSubset(model, root, files, model.Nodes.Keys);
                return files;
            }
            finally { Directory.Delete(root, true); }
        }

        static string Read(MemoryViewFiles files, string path) => Encoding.UTF8.GetString(files.Read(path));

        static XElement Entry(string guid, string parent, string name, string type, string body) => XElement.Parse(
            "<Single Type=\"{" + type + "}\" Method=\"IArchivable\"><Single Name=\"MetaObject\" Type=\"x\" Method=\"IArchivable\">"
            + "<Single Name=\"Guid\" Type=\"System.Guid\">" + guid + "</Single>"
            + (parent == null ? "" : "<Single Name=\"ParentGuid\" Type=\"System.Guid\">" + parent + "</Single>")
            + "<Single Name=\"Name\" Type=\"string\">" + name + "</Single><Single Name=\"TypeGuid\" Type=\"System.Guid\">" + type + "</Single></Single>"
            + "<Single Name=\"Object\" Type=\"{" + type + "}\" Method=\"IArchivable\">" + body + "</Single></Single>");

        static string Group() =>
            "<Dictionary Name=\"Alarms\" Type=\"x\">" + Alarm("1", "GVL.xLow", "Warning") + Alarm("0", "GVL.xFault", "Error") + "</Dictionary>"
            + "<Single Name=\"TextListReference\" Type=\"x\" Method=\"IArchivable\"><Single Name=\"Guid\" Type=\"System.Guid\">" + MessagesGuid + "</Single>"
            + "<Single Name=\"Name\" Type=\"string\">Pumps</Single></Single>";

        static string Alarm(string id, string expression, string alarmClass) =>
            "<Entry><Key><Single Type=\"string\">" + id + "</Single></Key><Value><Single Type=\"x\" Method=\"IArchivable\">"
            + "<Single Name=\"ID\" Type=\"string\">" + id + "</Single>"
            + "<Single Name=\"ObservationType\" Type=\"x\" Method=\"IArchivable\"><Single Name=\"Comparison\" Type=\"x\">Equal</Single>"
            + "<Single Name=\"ExpressionToCompare\" Type=\"string\">TRUE</Single><Single Name=\"Expression\" Type=\"string\">" + expression + "</Single></Single>"
            + "<Single Name=\"AlarmClass\" Type=\"x\" Method=\"IArchivable\"><Single Name=\"Name\" Type=\"string\">" + alarmClass + "</Single></Single>"
            + "</Single></Value></Entry>";

        static string List(string[] languages, params string[][] rows) =>
            "<List Name=\"TextList\" Type=\"System.Collections.ArrayList\">"
            + string.Concat(rows.Select(row => "<Single Type=\"x\" Method=\"IArchivable\"><Single Name=\"TextID\" Type=\"string\">" + row[0] + "</Single>"
                + "<Single Name=\"TextDefault\" Type=\"string\">" + row[1] + "</Single><List Name=\"LanguageTexts\" Type=\"System.Collections.ArrayList\">"
                + string.Concat(row.Skip(2).Select(text => "<Single Type=\"string\">" + text + "</Single>")) + "</List></Single>"))
            + "</List><List Name=\"Languages\" Type=\"System.Collections.ArrayList\">" + string.Concat(languages.Select(language => "<Single Type=\"string\">" + language + "</Single>")) + "</List>";
    }
}
