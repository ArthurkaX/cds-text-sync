using System;
using Xunit;

namespace Cts.Agent.Tests
{
    public class PlcPathsTests
    {
        [Theory]
        [InlineData(".")]
        [InlineData("")]
        [InlineData(null)]
        [InlineData("/")]
        [InlineData("\\")]
        [InlineData("/.")]
        [InlineData(".\\")]
        public void EveryRootTokenIsTheDeviceRoot(string token)
        {
            Assert.Equal("", PlcPaths.Normal("path", token));
        }

        [Fact]
        public void APosixOrRelativePathIsSentAsTyped()
        {
            Assert.Equal("/usr/", PlcPaths.Normal("path", "/usr/"));
            Assert.Equal("PlcLogic/Application", PlcPaths.Normal("path", "PlcLogic/Application"));
        }

        [Theory]
        [InlineData("C:/Program Files/Git/")]
        [InlineData("c:\\temp")]
        [InlineData("\\\\server\\share")]
        [InlineData("//server/share")]
        public void AHostPathIsRefusedAsAnMsysRewrite(string path)
        {
            var error = Assert.Throws<ProtocolException>(() => PlcPaths.Normal("path", path));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
            Assert.Contains("MSYS_NO_PATHCONV=1", error.Message);
        }

        [Fact]
        public void AnEntryCarriesTheDirectoryBitAndUtcTimes()
        {
            var created = new DateTime(2026, 9, 26, 21, 40, 8);
            var entry = PlcPaths.Entry("cert", 2, 0, created, created.AddDays(1));
            Assert.Equal(true, entry["is_directory"]);
            Assert.Equal("2026-09-26T21:40:08Z", entry["creation_time"]);
            Assert.Equal("2026-09-27T21:40:08Z", entry["last_write_time"]);
            Assert.Equal(false, PlcPaths.Entry("3S.dat", 0, 62, created, created)["is_directory"]);
        }

        [Fact]
        public void TheCrcIsZlibsCrc32()
        {
            using (var stream = new System.IO.MemoryStream(System.Text.Encoding.ASCII.GetBytes("123456789")))
                Assert.Equal("cbf43926", PlcPaths.Hex(PlcPaths.Crc32(stream)));
        }

        [Fact]
        public void OnlyADirectoryListingHoldsTheDot()
        {
            Assert.True(PlcPaths.IsSelfOrParent(".") && PlcPaths.IsSelfOrParent(".."));
            Assert.False(PlcPaths.IsSelfOrParent("..."));
            PlcPaths.RequireDirectory("PlcLogic", new[] { ".", "..", "a.app" });
            var error = Assert.Throws<ProtocolException>(() => PlcPaths.RequireDirectory("nope", new string[0]));
            Assert.Contains("No directory 'nope'", error.Message);
        }

        [Theory]
        [InlineData("codesyscontrol.log", ".")]
        [InlineData("PlcLogic/Application/Application.crc", "PlcLogic/Application")]
        [InlineData("PlcLogic\\a.log", "PlcLogic")]
        public void AFileLivesInItsParent(string file, string parent)
        {
            Assert.Equal(parent, PlcPaths.Parent(file));
        }

        [Theory]
        [InlineData("C:\\Temp\\a.bin")]
        [InlineData("c:/temp/a.bin")]
        [InlineData("\\\\server\\share\\a.bin")]
        public void AnAbsoluteHostFileIsKept(string path)
        {
            Assert.Equal(path, PlcPaths.HostFile("src", path));
        }

        [Theory]
        [InlineData("a.bin")]
        [InlineData("C:a.bin")]
        [InlineData("\\Temp\\a.bin")]
        [InlineData("/tmp/a.bin")]
        public void ARelativeHostFileIsRefused(string path)
        {
            var error = Assert.Throws<ProtocolException>(() => PlcPaths.HostFile("src", path));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
            Assert.Contains("'src' must be an absolute path on this PC", error.Message);
        }

        [Fact]
        public void AMissingHostFileIsAMissingParameter()
        {
            var error = Assert.Throws<ProtocolException>(() => PlcPaths.HostFile("output", ""));
            Assert.Contains("missing parameter 'output'", error.Message);
        }
    }
}
