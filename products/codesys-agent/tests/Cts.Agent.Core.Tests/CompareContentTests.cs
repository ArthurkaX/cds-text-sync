using System.Text;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Cts.Sync;
using System.Xml.Linq;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CompareContentTests
    {
        [Fact]
        public void StAndCsvIgnoreOnlyLineEndingDifferences()
        {
            Assert.True(ExportCommand.SameContent("A.st", Bytes("PROGRAM A\r\nEND_PROGRAM"), Bytes("PROGRAM A\nEND_PROGRAM")));
            Assert.False(ExportCommand.SameContent("A.csv", Bytes("a,b\nx,y"), Bytes("a,b\nx,z")));
        }

        [Fact]
        public void XmlUsesExportNormalization()
        {
            Assert.True(ExportCommand.SameContent("A.xml", Bytes("<Root><Property Name='Timestamp'>1</Property><Value>same</Value></Root>"), Bytes("<Root><Property Name='Timestamp'>2</Property><Value>same</Value></Root>")));
            // The IDE writes an empty value as <x></x>, the view as <x />.
            Assert.True(ExportCommand.SameContent("A.xml", Bytes("<Root><Single Name='Comment' /></Root>"), Bytes("<Root><Single Name='Comment'></Single></Root>")));
        }

        // A Library Manager saved by SP16 and exported again by SP22: the
        // versions write an unset field differently, and the content is one.
        [Fact]
        public void AFieldWithoutAValueIsOneWhateverTheVersionWritesForIt()
        {
            const string older = "<Root><Single Name='Object'><List Name='Items'><Single><Array Name='Params' Type='{e38d}' /><Single Name='Id'>1</Single></Single></List></Single></Root>";
            const string newer = "<Root><Single Name='Object'><List2 Name='ParameterTable' /><List Name='Items'><Single><Null Name='Params' /><Single Name='Id'>1</Single></Single></List></Single></Root>";
            Assert.True(ExportCommand.SameContent("Library Manager.xml", Bytes(older), Bytes(newer)));
            Assert.False(ExportCommand.SameContent("Library Manager.xml", Bytes(older), Bytes(newer.Replace("<Null Name='Params' />", "<Array Name='Params'><Single>x</Single></Array>"))));
            Assert.False(ExportCommand.SameContent("Library Manager.xml", Bytes(older), Bytes(newer.Replace("<List Name='Items'>", "<List Name='Items'><Null />"))));
        }

        // The id and the source label are the .project's: a copy's files name
        // no id, so its import cannot make it the original.
        [Fact]
        public void TheIdAndTheSourceLabelStayOutOfTheViewAndItsCompare()
        {
            const string bare = "<Root><Dictionary Name='Properties'><Entry><Key><Single Type='string'>Title</Single></Key><Value><Single Type='string'>demo</Single></Value></Entry></Dictionary></Root>";
            var labelled = bare.Replace("</Dictionary>", "<Entry><Key><Single Type='string'>cts-project-id</Single></Key><Value><Single Type='string'>id</Single></Value></Entry>"
                + "<Entry><Key><Single Type='string'>cts-source</Single></Key><Value><Single Type='string'>master@0123abcd \u00b7 2026-10-16 20:32</Single></Value></Entry></Dictionary>");
            Assert.True(ExportCommand.SameContent("POUs/Project Information.xml", Bytes(bare), Bytes(labelled)));
            Assert.Equal(ViewExport.NativeBytes(XElement.Parse(bare), false), ViewExport.NativeBytes(XElement.Parse(labelled), false));
            Assert.False(ExportCommand.SameContent("POUs/Project Information.xml", Bytes(bare), Bytes(bare.Replace(">demo<", ">other<"))));
        }

        [Fact]
        public void ContentKeysMatchSameContentAcrossComparisonInputs()
        {
            var pairs = new[]
            {
                new ContentPair("A.xml", Bytes("<Root><Property Name='Timestamp'>1</Property><Value>same</Value></Root>"), Bytes("<Root><Property Name='Timestamp'>2</Property><Value>same</Value></Root>"), true),
                new ContentPair("A.xml", Bytes("<Root><Value>one</Value></Root>"), Bytes("<Root><Value>two</Value></Root>"), false),
                new ContentPair("A.st", Bytes("PROGRAM A\r\nEND_PROGRAM"), Bytes("PROGRAM A\nEND_PROGRAM"), true),
                new ContentPair("A.st", Bytes("PROGRAM A"), Bytes("PROGRAM B"), false),
                new ContentPair("A.xml", Bytes("<Root>"), Bytes("<Root> "), false),
                new ContentPair("A.bin", new byte[] { 0xff, 0xfe }, new byte[] { 0xff, 0xfd }, false),
            };
            foreach (var pair in pairs)
            {
                Assert.Equal(pair.Equal, ExportCommand.SameContent(pair.Path, pair.Left, pair.Right));
                Assert.Equal(pair.Equal, ExportCommand.ContentKey(pair.Path, pair.Left) == ExportCommand.ContentKey(pair.Path, pair.Right));
            }
            Assert.Null(ExportCommand.ContentKey("A.xml", null));
        }

        [Fact]
        public void XmlDeepEqualsMatchesSerializedEqualityForNormalizationCases()
        {
            var pairs = new[]
            {
                new XmlPair("<Root a='1' b='2' />", "<Root b='2' a='1' />"),
                new XmlPair("<Root><A /><B /></Root>", "<Root><B /><A /></Root>"),
                new XmlPair("<Root> text </Root>", "<Root>text</Root>"),
                new XmlPair("<Root><A /></Root>", "<Root><A></A></Root>"),
            };
            foreach (var pair in pairs)
            {
                var left = XElement.Parse(pair.Left);
                var right = XElement.Parse(pair.Right);
                Assert.Equal(XElement.DeepEquals(left, right), left.ToString(SaveOptions.DisableFormatting) == right.ToString(SaveOptions.DisableFormatting));
            }
        }

        [Fact]
        public void CompareReusesContentKeysFromPersistedCache()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-keys-" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var cachePath = Path.Combine(root, "content-keys");
                var leftBytes = Bytes("<Root><Value>left</Value></Root>");
                var rightBytes = Bytes("<Root><Value>right</Value></Root>");
                var left = new CountingViewFiles(leftBytes, ViewExport.BlobId(leftBytes));
                var right = new CountingViewFiles(rightBytes, ViewExport.BlobId(rightBytes));
                var first = new ComparePlanner.ContentKeyCache(cachePath);
                Assert.False(ComparePlanner.SameViewContent("A.xml", left, right, first));
                first.Save();
                Assert.Equal(1, left.ReadCount);
                Assert.Equal(1, right.ReadCount);

                var second = new ComparePlanner.ContentKeyCache(cachePath);
                Assert.False(ComparePlanner.SameViewContent("A.xml", left, right, second));
                second.Save();
                Assert.Equal(1, left.ReadCount);
                Assert.Equal(1, right.ReadCount);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void CorruptContentKeyCacheIsIgnored()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-keys-" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var cachePath = Path.Combine(root, "content-keys");
                File.WriteAllText(cachePath, "not a valid cache entry\n");
                var cache = new ComparePlanner.ContentKeyCache(cachePath);
                Assert.Null(cache.Get("blob", "xml"));
                cache.Put("blob", "xml", "xml:key");
                cache.Save();
                Assert.Equal("build " + CliRun.Build() + "\nblob xml xml:key", File.ReadAllText(cachePath).Trim().Replace("\r\n", "\n"));
            }
            finally { Directory.Delete(root, true); }
        }

        // A key an older build made for a blob may follow a rule since
        // changed; the blob never changes, so the key would stay wrong.
        [Fact]
        public void KeysAnotherBuildMadeAreNotUsed()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-keys-" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var cachePath = Path.Combine(root, "content-keys");
                File.WriteAllText(cachePath, "build other\nblob xml xml:key\n");
                Assert.Null(new ComparePlanner.ContentKeyCache(cachePath).Get("blob", "xml"));
                File.WriteAllText(cachePath, "build " + CliRun.Build() + "\nblob xml xml:key\n");
                Assert.Equal("xml:key", new ComparePlanner.ContentKeyCache(cachePath).Get("blob", "xml"));
            }
            finally { Directory.Delete(root, true); }
        }

        sealed class ContentPair
        {
            internal ContentPair(string path, byte[] left, byte[] right, bool equal)
            {
                Path = path;
                Left = left;
                Right = right;
                Equal = equal;
            }
            internal string Path { get; }
            internal byte[] Left { get; }
            internal byte[] Right { get; }
            internal bool Equal { get; }
        }

        sealed class XmlPair
        {
            internal XmlPair(string left, string right) { Left = left; Right = right; }
            internal string Left { get; }
            internal string Right { get; }
        }

        sealed class CountingViewFiles : IViewFiles
        {
            readonly byte[] bytes;
            readonly string blob;
            internal CountingViewFiles(byte[] bytes, string blob) { this.bytes = bytes; this.blob = blob; }
            internal int ReadCount { get; private set; }
            public IEnumerable<string> Paths => new[] { "A.xml" };
            public string BlobId(string path) => blob;
            public byte[] Read(string path) { ReadCount++; return bytes; }
            public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths) => paths.ToDictionary(path => path, Read);
        }

        [Fact]
        public void StReaderReusesParsedObjectsByBlobIdAndRelativePath()
        {
            var bytes = Bytes("PROGRAM A\nEND_PROGRAM\n");
            var shared = new Dictionary<string, StViewResult>();
            var baselineFiles = new FixedViewFiles(bytes, "blob-id");
            var baseline = StViewReader.Read(baselineFiles, shared);
            var diskFiles = new FixedViewFiles(bytes, "blob-id");
            var disk = StViewReader.Read(diskFiles, shared);
            Assert.Equal(1, baselineFiles.ReadCount);
            Assert.Equal(0, diskFiles.ReadCount);
            Assert.Same(Assert.Single(baseline.Objects), Assert.Single(disk.Objects));
        }

        [Fact]
        public void StFileDifferenceIsReportedByObjectAndPart()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-compare-" + System.Guid.NewGuid().ToString("N"));
            var b = Path.Combine(root, "base"); var d = Path.Combine(root, "disk"); var i = Path.Combine(root, "ide");
            Directory.CreateDirectory(b); Directory.CreateDirectory(d); Directory.CreateDirectory(i);
            try
            {
                File.WriteAllText(Path.Combine(b, "A.st"), "PROGRAM A\nVAR x : INT;\nEND_VAR\nEND_PROGRAM\n");
                File.WriteAllText(Path.Combine(d, "A.st"), "PROGRAM A\nVAR x : BOOL;\nEND_VAR\nEND_PROGRAM\n");
                File.Copy(Path.Combine(b, "A.st"), Path.Combine(i, "A.st"));
                var records = new List<CompareRecord>();
                var counts = new Dictionary<string, int>();
                var disk = StViewReader.Read(d); var baseline = StViewReader.Read(b); var ide = StViewReader.Read(i);
                ComparePlanner.CompareSt(disk, baseline, ide, new HashSet<string>(), new HashSet<string>(), records, counts, false, null);
                var record = Assert.Single(records);
                Assert.Equal("modified", record.Category);
                Assert.Equal("A", record.Name);
                Assert.Equal(new[] { "declaration" }, record.Parts);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void MethodInAFileOfItsOwnMatchesTheSameMethodInItsOwnersFile()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-compare-" + System.Guid.NewGuid().ToString("N"));
            var d = Path.Combine(root, "disk"); var i = Path.Combine(root, "ide");
            Directory.CreateDirectory(d); Directory.CreateDirectory(i);
            try
            {
                File.WriteAllText(Path.Combine(d, "I_A.st"), "INTERFACE I_A\nEND_INTERFACE\n");
                File.WriteAllText(Path.Combine(d, "I_A.M_A.st"), "METHOD M_A : BOOL\nVAR_INPUT\n\tx : BOOL;\nEND_VAR\n");
                File.WriteAllText(Path.Combine(i, "I_A.st"), "INTERFACE I_A\nEND_INTERFACE\n\nMETHOD M_A : BOOL\nVAR_INPUT\n\tx : BOOL;\nEND_VAR\nEND_METHOD\n");
                var records = new List<CompareRecord>();
                var counts = new Dictionary<string, int> { { "unchanged", 0 } };
                var disk = StViewReader.Read(d); var ide = StViewReader.Read(i); var baseline = new StViewResult();
                ComparePlanner.CompareSt(disk, baseline, ide, new HashSet<string>(), new HashSet<string>(), records, counts, true, null);
                Assert.All(records, record => Assert.Equal("unchanged", record.Category));
                Assert.Equal(2, counts["unchanged"]);
            }
            finally { Directory.Delete(root, true); }
        }

        static byte[] Bytes(string value) => new UTF8Encoding(false).GetBytes(value);

        sealed class FixedViewFiles : IViewFiles
        {
            readonly byte[] bytes;
            readonly string blobId;

            internal FixedViewFiles(byte[] bytes, string blobId)
            {
                this.bytes = bytes;
                this.blobId = blobId;
            }

            internal int ReadCount { get; private set; }
            public IEnumerable<string> Paths => new[] { "A.st" };
            public string BlobId(string path) => blobId;

            public byte[] Read(string path)
            {
                ReadCount++;
                return bytes;
            }

            public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
            {
                return paths.ToDictionary(path => path, Read);
            }
        }
    }
}
