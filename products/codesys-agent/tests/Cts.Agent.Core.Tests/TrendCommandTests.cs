using System;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Xunit;

namespace Cts.Agent.Tests
{
    // cts trend set writes the Trend Recording CtsTrend, and the first time
    // the objects it needs, as cts export would have written them.
    public sealed class TrendCommandTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-trend-" + Guid.NewGuid().ToString("N"));
        readonly string _app;

        public TrendCommandTests()
        {
            var golden = Directory.GetDirectories(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "expected"), "Application", SearchOption.AllDirectories).Single();
            _app = Path.Combine(_root, "project-view", "Dev", "Plc Logic", "Application");
            foreach (var file in Directory.GetFiles(golden, "*", SearchOption.AllDirectories))
            {
                var copy = Path.Combine(_app, file.Substring(golden.Length + 1));
                Directory.CreateDirectory(Path.GetDirectoryName(copy));
                File.Copy(file, copy);
            }
        }

        public void Dispose() => Directory.Delete(_root, true);

        string Recording => Path.Combine(_app, "Trend Recording Manager", "CtsTrend.xml");

        [Fact]
        public void TheFirstSetWritesTheRecordingWithWhatItNeeds()
        {
            var (code, output, _) = Trend("trend", "set", "GVL_Bench.rLevel", "MAIN.fbPump.xRun");

            Assert.Equal(0, code);
            Assert.StartsWith("ok trend-set app=Application changed=5 task=Task every=1 interval_ms=200 slots=10 limit_mb=16\n", output);
            foreach (var file in new[] { "Trend Recording Manager/.cds-object.xml", "Task Configuration/TrendRecordingTask.xml", "Trend Recording Manager/CtsTrend.xml", "GVL_CtsTrend.st", "Library Manager.xml" })
                Assert.Contains("\nDev/Plc Logic/Application/" + file + "\n", output);
            Assert.Contains("\nVal1  GVL_Bench.rLevel\nVal2  MAIN.fbPump.xRun\n", output);
            Assert.Contains("(it asks a full download: cts download), then cts trend on", output);

            var recording = File.ReadAllText(Recording);
            Assert.Equal(new[] { "GVL_Bench.rLevel", "MAIN.fbPump.xRun" }.Concat(Enumerable.Repeat("GVL_CtsTrend.xRecord", 8)),
                Regex.Matches(recording, "<Single Name=\"VariableName\" Type=\"string\">([^<]*)<").Cast<Match>().Select(match => match.Groups[1].Value));
            Assert.Contains("<Single Name=\"Condition\" Type=\"string\">GVL_CtsTrend.xRecord</Single>", recording);
            Assert.Contains("<Single Name=\"TaskName\" Type=\"string\">Task</Single>", recording);
            var manager = File.ReadAllText(Path.Combine(_app, "Trend Recording Manager", ".cds-object.xml"));
            Assert.Contains("<Single Name=\"ParentGuid\" Type=\"System.Guid\">" + GuidOf(manager, "Guid") + "</Single>", recording);
            Assert.Equal(GuidOf(File.ReadAllText(Path.Combine(_app, ".cds-object.xml")), "Guid"), GuidOf(manager, "ParentGuid"));
            Assert.Contains("xRecord : BOOL;", File.ReadAllText(Path.Combine(_app, "GVL_CtsTrend.st")));
            Assert.Contains("VisuTrendStorageAccess, ", File.ReadAllText(Path.Combine(_app, "Library Manager.xml")));

            // Its objects are its own, not the template's.
            using (var stream = typeof(Cts.Cli.CliCommand).Assembly.GetManifestResourceStream("Cts.Trend.Templates.Recording.xml"))
            using (var reader = new StreamReader(stream))
                Assert.Empty(Guids(recording).Intersect(Guids(reader.ReadToEnd())));
            Assert.NotEmpty(Guids(recording));
        }

        [Fact]
        public void ANewListTakesTheSameSlotsAndAsksNoFullDownload()
        {
            Trend("trend", "set", "GVL_Bench.rLevel", "--every", "5");
            var manager = File.ReadAllText(Path.Combine(_app, "Trend Recording Manager", ".cds-object.xml"));

            var (code, output, _) = Trend("trend", "set", "GVL_Bench.xRun", "GVL_Bench.iCount", "GVL_Bench.rLevel");

            Assert.Equal(0, code);
            Assert.StartsWith("ok trend-set app=Application changed=1 task=Task every=5 interval_ms=1000 slots=10", output);
            Assert.Contains("\nDev/Plc Logic/Application/Trend Recording Manager/CtsTrend.xml\nNext: cts import, cts build, then cts download --online-change, then cts trend on", output);
            Assert.Equal(manager, File.ReadAllText(Path.Combine(_app, "Trend Recording Manager", ".cds-object.xml")));
            Assert.Contains("nothing changed", Trend("trend", "set").output);
            Assert.Contains("full download", Trend("trend", "set", "--slots", "4").output);

            var shown = Trend("trend").output;
            Assert.StartsWith("ok trend app=Application task=Task every=5 interval_ms=1000 slots=4 limit_mb=16\n", shown);
            Assert.Contains("\nVal1  GVL_Bench.xRun\nVal2  GVL_Bench.iCount\nVal3  GVL_Bench.rLevel\n", shown);
            Assert.Equal(4, Regex.Matches(File.ReadAllText(Recording), "Name=\"VariableName\"").Count);
        }

        [Fact]
        public void WithoutATrendShowSaysHowToMakeOne()
        {
            var output = Trend("trend").output;
            Assert.StartsWith("ok trend app=Application trend=none\n", output);
            Assert.Contains("cts trend set VAR", output);
        }

        [Fact]
        public void WhatTheRecordingCannotHoldIsRefused()
        {
            Assert.Contains("--slots 3", Trend("trend", "set", "GVL.a", "GVL.b", "GVL.c", "--slots", "2").error);
            Assert.Contains("no task Fast; its tasks: ", Trend("trend", "set", "GVL.a", "--task", "Fast").error);
            Assert.Contains("'rLevel' is no variable", Trend("trend", "set", "rLevel").error);
            Assert.Contains("name the variables", Trend("trend", "set").error);
            Assert.Contains("no application Other", Trend("trend", "--app", "Other").error);
            Assert.False(File.Exists(Recording));
        }

        static string GuidOf(string xml, string name) => Regex.Match(xml, "<Single Name=\"" + name + "\" Type=\"System.Guid\">([^<]*)<").Groups[1].Value;

        static string[] Guids(string xml) => Regex.Matches(xml, "<Single Name=\"(?!TypeGuid\")[^\"]*\" Type=\"System.Guid\">([^<]*)<").Cast<Match>()
            .Select(match => match.Groups[1].Value).Where(guid => guid != Guid.Empty.ToString("D")).ToArray();

        (int code, string output, string error) Trend(params string[] args) => CliTests.RunLocal(args.Concat(new[] { "--workspace", _root }).ToArray());
    }
}
