using System.Linq;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class XmlMergeTests
    {
        static string Task(string priority = "1", string interval = "200", params string[] programs)
        {
            if (programs.Length == 0) programs = new[] { "MAIN" };
            return "<?xml version='1.0' encoding='utf-8'?>\n"
                + "<Single Type=\"{6198ad31}\" Method=\"IArchivable\">\n"
                + "      <Single Name=\"Object\" Type=\"{98a2708a}\" Method=\"IArchivable\">\n"
                + "        <Single Name=\"Priority\" Type=\"string\">" + priority + "</Single>\n"
                + "        <Single Name=\"Interval\" Type=\"{68e48988}\" Method=\"IArchivable\">\n"
                + "          <Single Name=\"Time\" Type=\"string\">" + interval + "</Single>\n"
                + "          <Single Name=\"Unit\" Type=\"string\">ms</Single>\n"
                + "        </Single>\n"
                + "        <List Name=\"PouList\" Type=\"{33f568bb}\">\n"
                + string.Concat(programs.Select(program =>
                    "          <Single Type=\"{f194d1ef}\" Method=\"IArchivable\">\n"
                    + "            <Single Name=\"Name\" Type=\"string\">" + program.Split('|')[0] + "</Single>\n"
                    + "            <Single Name=\"Comment\" Type=\"string\">" + (program.Contains('|') ? program.Split('|')[1] : "") + "</Single>\n"
                    + "          </Single>\n"))
                + "        </List>\n"
                + "      </Single>\n"
                + "    </Single>";
        }

        static string Merge(string b, string o, string t)
        {
            var merged = XmlMerge.Merge(b, o, t, out var conflict);
            Assert.True(merged != null, conflict);
            return merged;
        }

        [Fact]
        public void ProgramsAddedToOneTaskOnBothSidesAreBothCalled()
        {
            var merged = Merge(Task(), Task(programs: new[] { "MAIN", "PRG_A" }), Task(programs: new[] { "MAIN", "PRG_B" }));
            Assert.Equal(Task(programs: new[] { "MAIN", "PRG_A", "PRG_B" }), merged);
        }

        [Fact]
        public void EachSidesSettingIsKept()
        {
            Assert.Equal(Task("5", "100"), Merge(Task(), Task("5"), Task(interval: "100")));
        }

        [Fact]
        public void OneSettingChangedTwoWaysIsAConflictNamingIt()
        {
            Assert.Null(XmlMerge.Merge(Task(), Task("5"), Task("7"), out var conflict));
            Assert.Equal("both sides changed Object/Priority differently", conflict);
        }

        [Fact]
        public void ACallRemovedOnOneSideAndEditedOnTheOtherIsAConflict()
        {
            var b = Task(programs: new[] { "MAIN", "PRG_A" });
            Assert.Null(XmlMerge.Merge(b, Task(programs: new[] { "MAIN" }), Task(programs: new[] { "MAIN", "PRG_A|slow" }), out var conflict));
            Assert.Equal("both sides changed Object/PouList/PRG_A differently", conflict);
            Assert.Equal(Task(programs: new[] { "MAIN", "PRG_B" }), Merge(b, Task(programs: new[] { "MAIN" }), Task(programs: new[] { "MAIN", "PRG_A", "PRG_B" })));
        }

        [Fact]
        public void TheCallOrderOneSideChangedIsKept()
        {
            var b = Task(programs: new[] { "MAIN", "PRG_A" });
            Assert.Equal(Task(programs: new[] { "PRG_A", "PRG_B", "MAIN" }),
                Merge(b, Task(programs: new[] { "PRG_A", "MAIN" }), Task(programs: new[] { "MAIN", "PRG_A", "PRG_B" })));
        }

        [Fact]
        public void LibrariesAddedOnBothSidesAreBothKeptWithTheirResolutions()
        {
            string Libraries(params string[] names) => "<?xml version='1.0' encoding='utf-8'?>\r\n<Single Name=\"Object\">\r\n"
                + "  <List Name=\"Items\">\r\n"
                + string.Concat(names.Select(name => "    <Single Type=\"{4723ebe7}\">\r\n      <Single Name=\"PlaceholderName\" Type=\"string\">" + name + "</Single>\r\n      <Single Name=\"Id\" Type=\"long\">" + name.Length + "</Single>\r\n    </Single>\r\n"))
                + "  </List>\r\n  <Dictionary Name=\"Resolutions\">\r\n"
                + string.Concat(names.Select(name => "    <Entry>\r\n      <Key>\r\n        <Single Type=\"string\">" + name + "</Single>\r\n      </Key>\r\n      <Value>\r\n        <Single Type=\"string\">" + name + ", 1.0</Single>\r\n      </Value>\r\n    </Entry>\r\n"))
                + "  </Dictionary>\r\n</Single>\r\n";
            Assert.Equal(Libraries("Standard", "Util", "Collections"), Merge(Libraries("Standard"), Libraries("Standard", "Util"), Libraries("Standard", "Collections")));
        }

        [Fact]
        public void TextThatIsNotXmlIsAConflict()
        {
            Assert.Null(XmlMerge.Merge(Task(), Task("5"), "<Single", out var conflict));
            Assert.Equal("a side is not XML in the view's form", conflict);
        }
    }
}
