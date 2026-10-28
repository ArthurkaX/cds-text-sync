using System;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Cts.Trend;
using Xunit;

namespace Cts.Agent.Tests
{
    // cts trend pull decodes the PLC's trend file into this PC's database;
    // cts trend query asks it.
    [Collection("Local command settings")]
    public sealed class TrendDataTests : IDisposable
    {
        const string Gate = "GVL_CtsTrend.xRecord";
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-trend-data-" + Guid.NewGuid().ToString("N"));
        readonly string _oldXdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");

        // Off Windows the tests reach SQLite as the system's libsqlite3.
        [ModuleInitializer]
        internal static void MapSqlite()
        {
            if (OperatingSystem.IsWindows()) return;
            NativeLibrary.SetDllImportResolver(typeof(Sqlite).Assembly,
                (name, assembly, path) => name == Sqlite.Library ? NativeLibrary.Load("libsqlite3.so.0") : IntPtr.Zero);
        }

        public TrendDataTests()
        {
            Directory.CreateDirectory(_root);
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "xdg"));
        }

        public void Dispose()
        {
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", _oldXdg);
            Directory.Delete(_root, true);
        }

        // Two configurations, as an online change leaves them: rLevel drops
        // out, xRun takes the column the gate had; a cycle in between has no values.
        string PlcFile()
        {
            var file = Path.Combine(_root, "plc.sqlite");
            File.Delete(file);
            using (var plc = Sqlite.Open(file, true))
            {
                plc.Run("CREATE TABLE TblTrendConfiguration(Id INTEGER, VarIdx INTEGER, VarName TEXT, VarType INTEGER, ColId INTEGER)");
                plc.Run("CREATE TABLE TblTrendConfigurationDuration(TSFrom INTEGER, TsTo INTEGER, Id INTEGER)");
                plc.Run("CREATE TABLE TblTrendData(TS INTEGER, Val1 INTEGER, Val2 INTEGER, Val3 INTEGER, Val4 INTEGER)");
                foreach (var row in new object[][]
                {
                    new object[] { 0, 0, "GVL.rLevel", 14, 1 }, new object[] { 0, 1, "GVL.iTemp", 7, 2 }, new object[] { 0, 2, Gate, 0, 3 }, new object[] { 0, 3, Gate, 0, 4 },
                    new object[] { 1, 0, "GVL.iTemp", 7, 2 }, new object[] { 1, 1, "GVL.xRun", 0, 3 }, new object[] { 1, 2, Gate, 0, 4 }, new object[] { 1, 3, Gate, 0, 4 },
                })
                    plc.Run("INSERT INTO TblTrendConfiguration VALUES (?, ?, ?, ?, ?)", row);
                plc.Run("INSERT INTO TblTrendConfigurationDuration VALUES (1000, 2500, 0)");
                plc.Run("INSERT INTO TblTrendConfigurationDuration VALUES (3000, NULL, 1)");
                plc.Run("INSERT INTO TblTrendData VALUES (1000, 1144754176, 65535, 1, 1)");
                plc.Run("INSERT INTO TblTrendData VALUES (2000, NULL, NULL, NULL, NULL)");
                plc.Run("INSERT INTO TblTrendData VALUES (3000, NULL, 5, 1, 1)");
            }
            return file;
        }

        [Fact]
        public void A_pull_decodes_each_value_in_the_column_its_configuration_names()
        {
            var local = Path.Combine(_root, "local.sqlite");

            var merged = TrendData.Merge(PlcFile(), local, Gate);

            Assert.Equal(3, merged.Rows);
            Assert.Equal(1, merged.Gaps);
            Assert.Equal(4, merged.Added);
            Assert.Equal(new[] { "GVL.iTemp", "GVL.rLevel", "GVL.xRun" }, merged.Variables.OrderBy(name => name));
            using (var database = Sqlite.Open(local, false))
            {
                Assert.Equal(new[] { "1000 GVL.iTemp -1", "1000 GVL.rLevel 750.25", "3000 GVL.iTemp 5", "3000 GVL.xRun 1" },
                    database.Rows("SELECT ts, name, value FROM samples ORDER BY ts, name").Select(row => string.Join(" ", row)));
                Assert.Equal(2000L, database.Rows("SELECT ts FROM gaps")[0][0]);
                Assert.Equal("INT", database.Rows("SELECT type FROM variables WHERE name = 'GVL.iTemp'")[0][0]);
                Assert.Equal("1970-01-01 00:00:00.001", database.Rows("SELECT at FROM samples_at LIMIT 1")[0][0]);
            }

            // The same file again adds nothing.
            Assert.Equal(0, TrendData.Merge(PlcFile(), local, Gate).Added);
        }

        [Theory]
        [InlineData(0xFFFFFFF6L, 8L, -10L)]
        [InlineData(0xFFFFL, 11L, 65535L)]
        [InlineData(0x80L, 6L, -128L)]
        [InlineData(4611686018427387904L, 15L, 2.0)]
        public void Raw_bits_read_as_the_variables_type(long raw, long type, object value)
        {
            Assert.Equal(Convert.ToDouble(value), Convert.ToDouble(TrendData.Decode(raw, type)));
        }

        [Fact]
        public void A_query_shows_rows_of_one_read_only_statement()
        {
            var golden = Directory.GetDirectories(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "expected"), "Application", SearchOption.AllDirectories).Single();
            var app = Path.Combine(_root, "project-view", "Dev", "Plc Logic", "Application");
            Directory.CreateDirectory(app);
            File.Copy(Path.Combine(golden, ".cds-object.xml"), Path.Combine(app, ".cds-object.xml"));
            Assert.Contains("cts trend pull", Query("SELECT 1").error);
            var local = TrendData.LocalFile(_root, "Application");
            Directory.CreateDirectory(Path.GetDirectoryName(local));
            TrendData.Merge(PlcFile(), local, Gate);

            var (code, output, _) = Query("SELECT name, value FROM samples WHERE ts = 1000 ORDER BY name");

            Assert.Equal(0, code);
            Assert.Equal("ok trend-query rows=2 more=false\nname\tvalue\nGVL.iTemp\t-1\nGVL.rLevel\t750.25\n", output.Replace("\r\n", "\n"));
            Assert.StartsWith("ok trend-query rows=1 more=true\n", Query("SELECT * FROM samples", "--limit", "1").output);
            Assert.Contains("readonly", Query("DELETE FROM samples").error);
            Assert.Contains("one statement at a time", Query("SELECT 1; SELECT 2").error);
        }

        (int code, string output, string error) Query(string sql, params string[] more) =>
            CliTests.RunLocal(new[] { "trend", "query", sql }.Concat(more).Concat(new[] { "--workspace", _root }).ToArray());
    }
}
