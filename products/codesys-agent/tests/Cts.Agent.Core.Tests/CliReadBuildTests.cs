using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        static Dictionary<string, object> Row(string name, bool ok, string text = null, string code = null, string message = null)
        {
            var row = new Dictionary<string, object> { { "name", name }, { "ok", ok } };
            if (ok) row["text"] = text;
            else row["error"] = new Dictionary<string, object> { { "code", code }, { "message", message } };
            return row;
        }

        [Fact]
        public void Read_returns_the_ide_spelling_for_one_name()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                Assert.Equal("vars.read", method);
                Assert.Equal(new[] { "GVL.word" }, ((IEnumerable<object>)p["names"]).Cast<string>());
                return new Dictionary<string, object> { { "logged_in", true }, { "results", new object[] { Row("GVL.word", true, "WORD#5") } } };
            });
            var (code, output, _) = Run(host, "read", "GVL.word");
            Assert.Equal(0, code);
            Assert.StartsWith("ok read value=WORD#5\n", output);
        }

        [Fact]
        public void Read_reports_not_connected_as_an_actionable_failure()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object> { { "logged_in", false } });
            var (code, output, error) = Run(host, "read", "GVL.x");
            Assert.Equal(1, code);
            Assert.Contains("error read cause=\"Not connected", output);
            Assert.Contains("cts connect", error);
        }

        [Fact]
        public void Read_keeps_rows_in_order_and_marks_a_not_exported_name_partial()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "logged_in", true }, { "results", new object[] { Row("GVL.a", true, "1"), Row("GVL.gone", false, code: "not_exported", message: "missing") } },
            });
            var (code, output, _) = Run(host, "read", "GVL.a", "GVL.gone");
            Assert.Equal(1, code);
            Assert.StartsWith("partial read count=2 failed=1\nGVL.a = 1\nGVL.gone: Invalid expression: 'GVL.gone' is not exported", output);
        }

        [Fact]
        public void Read_suggests_a_declared_fb_member_from_the_sync_view()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-read-suggest-" + Guid.NewGuid().ToString("N"));
            var view = Path.Combine(root, "project-view");
            Directory.CreateDirectory(view);
            File.WriteAllText(Path.Combine(view, "GVL_Motors.st"), "VAR_GLOBAL\n    fbMotor1 : FB_Motor;\nEND_VAR");
            File.WriteAllText(Path.Combine(view, "FB_Motor.st"), "FUNCTION_BLOCK FB_Motor\nVAR\n    tFbTimeout : TIME;\nEND_VAR\nEND_FUNCTION_BLOCK");
            try
            {
                var host = new FakeHost();
                host.Agents[1] = Agent("project", root, (method, p) => new Dictionary<string, object>
                {
                    { "logged_in", true }, { "results", new object[] { Row("GVL_Motors.fbMotor1.tFeedbackTimeout", false, code: "not_exported", message: "missing") } },
                });
                var (code, output, _) = Run(host, "read", "GVL_Motors.fbMotor1.tFeedbackTimeout");
                Assert.Equal(1, code);
                Assert.Contains("did you mean: GVL_Motors.fbMotor1.tFbTimeout", output);
                host.Agents[1] = Agent("project", root, (method, p) => new Dictionary<string, object>
                {
                    { "logged_in", true }, { "results", new object[] { Row("GVL_Motors.fbMotr1", false, code: "not_exported", message: "missing") } },
                });
                Assert.Contains("did you mean: GVL_Motors.fbMotor1", Run(host, "read", "GVL_Motors.fbMotr1").Item2);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Read_until_reports_reached_first_and_uses_exit_two_when_it_times_out()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "logged_in", true }, { "results", new object[] { Row("GVL.mode", true, "E_Mode.Run") } },
            });
            var (code, output, _) = Run(host, "read", "GVL.mode", "--until", "Idle", "--interval", "0", "--within", "0");
            Assert.True(code == 2, output);
            Assert.StartsWith("partial read reached=false value=E_Mode.Run", output);
        }

        [Fact]
        public void Read_until_reports_a_reached_value()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "logged_in", true }, { "results", new object[] { Row("GVL.mode", true, "E_Mode.Run") } },
            });
            var (code, output, _) = Run(host, "read", "GVL.mode", "--until", "Run");
            Assert.Equal(0, code);
            Assert.StartsWith("ok read reached=true value=E_Mode.Run", output);
        }

        [Theory]
        [InlineData("'Ready'", true)]
        [InlineData("'READY'", false)]
        public void Read_until_compares_a_string_with_its_case_as_write_confirms_it(string until, bool reached)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "logged_in", true }, { "results", new object[] { Row("GVL.state", true, "'Ready'") } },
            });
            var (code, output, _) = Run(host, "read", "GVL.state", "--until", until, "--interval", "0", "--within", "0");
            Assert.True(code == (reached ? 0 : 2), output);
            Assert.Contains("reached=" + (reached ? "true" : "false"), output);
        }

        [Fact]
        public void Read_expands_a_structure_and_its_array_fields_into_leaf_reads()
        {
            var host = new FakeHost(); var reads = 0;
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                if (method == "objects.texts") return new Dictionary<string, object> { { "objects", new object[]
                {
                    new Dictionary<string, object> { { "name", "GVL" }, { "declaration", "VAR_GLOBAL\nitem : Pair;\nEND_VAR" } },
                    new Dictionary<string, object> { { "name", "Pair" }, { "declaration", "TYPE Pair : STRUCT left : INT; samples : ARRAY[0..1] OF BOOL; END_STRUCT END_TYPE" } },
                } } };
                Assert.Equal("vars.read", method); reads++;
                var names = ((IEnumerable<object>)p["names"]).Cast<string>().ToArray();
                if (reads == 1)
                {
                    Assert.Equal(new[] { "GVL.item" }, names);
                    return new Dictionary<string, object> { { "logged_in", true }, { "results", new object[] { Row("GVL.item", false, code: "not_scalar", message: "composite") } } };
                }
                Assert.Equal(new[] { "GVL.item.left", "GVL.item.samples[0]", "GVL.item.samples[1]" }, names);
                return new Dictionary<string, object> { { "logged_in", true }, { "results", names.Select(n => (object)Row(n, true, "1")).ToArray() } };
            });
            var (code, output, _) = Run(host, "read", "GVL.item");
            Assert.True(code == 0, output);
            Assert.StartsWith("ok read count=3 failed=0\n", output);
            Assert.Contains("GVL.item.left = 1", output);
            Assert.Contains("GVL.item.samples[1] = 1", output);
        }

        [Fact]
        public void Build_reports_error_and_warning_counts()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                if (method == "project.status") return new Dictionary<string, object>();
                Assert.Equal("app.build", method);
                return new Dictionary<string, object>
                {
                    { "application", "Application" }, { "compiled", true },
                    { "messages", new object[]
                        {
                            new Dictionary<string, object> { { "severity", "Error" }, { "code", "C0046" }, { "text", "not defined" }, { "object", "MAIN" } },
                            new Dictionary<string, object> { { "severity", "Warning" }, { "code", "C0195" }, { "text", "conversion" }, { "object", "MAIN" } },
                        } },
                };
            });
            var (code, output, _) = Run(host, "build", "--install");
            Assert.Equal(1, code);
            Assert.StartsWith("error build cause=\"not defined\" errors=1 warnings=1 error_codes=C0046:1", output);
            Assert.Contains("[C0046] not defined (in MAIN)", output);
            Assert.Contains("warning [C0195] conversion (in MAIN)", output);
        }

        [Fact]
        public void Build_json_marks_failed_build_and_omits_empty_pending_files()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "application", "Application" }, { "compiled", true },
                { "messages", new object[] { new Dictionary<string, object> { { "severity", "Error" }, { "code", "C0046" }, { "text", "not defined" }, { "object", "MAIN" } } } },
            });
            var (code, output, _) = Run(host, "build", "--json");
            Assert.Equal(1, code);
            Assert.Contains("\"ok\": false", output);
            Assert.Contains("\"errors\": 1", output);
            Assert.DoesNotContain("not_imported", output);
        }

        [Fact]
        public void Build_all_objects_marks_diagnostics_of_objects_no_task_calls()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "application", "Application" }, { "compiled", true }, { "messages", new object[0] },
                { "checked_messages", new object[] { new Dictionary<string, object> { { "severity", "Error" }, { "code", "C0046" }, { "text", "not defined" }, { "object", "F_Scale" } } } },
            });
            var (code, output, _) = Run(host, "build", "--all-objects");
            Assert.Equal(1, code);
            Assert.Contains("(in F_Scale, not called by any task)", output);
        }

        // A library referenced qualified-only hides its names: unknown-name
        // errors come with the namespaces that need the prefix.
        [Fact]
        public void Build_names_the_qualified_only_libraries_behind_unknown_names()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-build-lib-" + Guid.NewGuid().ToString("N"));
            var app = Path.Combine(folder, "project-view", "Dev", "Plc Logic", "Application");
            Directory.CreateDirectory(app);
            string Library(string ns, string qualified) => "<Single><Single Name=\"Namespace\" Type=\"string\">" + ns + "</Single><Single Name=\"QualifiedOnly\" Type=\"bool\">" + qualified + "</Single></Single>";
            File.WriteAllText(Path.Combine(app, "Library Manager.xml"), "<Single>" + Library("Standard", "True") + Library("Util", "False") + Library("CmpLog", "True") + "</Single>");
            try
            {
                var host = new FakeHost();
                host.Agents[1] = Agent(Path.Combine(folder, "Plant.project"), folder, (method, p) => new Dictionary<string, object>
                {
                    { "application", "Application" }, { "compiled", true },
                    { "messages", new object[]
                        {
                            new Dictionary<string, object> { { "severity", "Error" }, { "code", "C0077" }, { "text", "Unknown type: 'TON'" }, { "object", "PRG" } },
                            new Dictionary<string, object> { { "severity", "Error" }, { "code", "C0046" }, { "text", "Identifier 'CONCAT' not defined" }, { "object", "PRG" } },
                        } },
                });
                var (code, output, _) = Run(host, "build");
                Assert.Equal(1, code);
                Assert.Contains("2 errors name an unknown type or identifier; the Library Manager references these libraries qualified-only, so their names need the namespace in front (Standard.TON): Standard, CmpLog.", output);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Build_places_errors_before_warnings_with_file_line_and_column()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "application", "Application" }, { "compiled", true }, { "messages", new object[]
                {
                    new Dictionary<string, object> { { "severity", "Warning" }, { "code", "C0195" }, { "text", "conversion : Possible change of sign" }, { "object", "F_Scale" }, { "file", "project-view/App/F_Scale.st" }, { "line", 12 }, { "column", 1 } },
                    new Dictionary<string, object> { { "severity", "Error" }, { "code", "C0046" }, { "text", "not defined" }, { "object", "F_Scale" }, { "file", "project-view/App/F_Scale.st" }, { "line", 8 }, { "column", 1 } },
                } },
            });
            var (code, output, _) = Run(host, "build");
            Assert.Equal(1, code);
            Assert.Contains("[C0046] not defined (in F_Scale at project-view/App/F_Scale.st:8:1)", output);
            Assert.Contains("warning [C0195] conversion : Possible change of sign (in F_Scale at project-view/App/F_Scale.st:12:1)", output);
            Assert.True(output.IndexOf("[C0046]", StringComparison.Ordinal) < output.IndexOf("warning [C0195]", StringComparison.Ordinal), output);
        }

        [Fact]
        public void A_clean_library_check_reports_its_install_reply()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                if (method == "project.status") return new Dictionary<string, object>();
                Assert.Equal("app.build", method);
                Assert.Equal(true, p["install"]);
                return new Dictionary<string, object>
                {
                    { "kind", "library" }, { "library", "Demo, 1.0.0" }, { "installed", true }, { "compiled", true },
                    { "messages", new object[0] },
                };
            });
            var (code, output, _) = Run(host, "build", "--install");
            Assert.Equal(0, code);
            Assert.StartsWith("ok build errors=0 warnings=0 installed=true library=\"Demo, 1.0.0\"", output);
        }

        static Dictionary<string, object> TwoApplications(bool firstActive) => new Dictionary<string, object>
        {
            { "devices", new object[] { new Dictionary<string, object> { { "path", "Device" }, { "applications", new object[]
            {
                new Dictionary<string, object> { { "name", "Application" }, { "guid", "g1" }, { "active", firstActive } },
                new Dictionary<string, object> { { "name", "HMI_Application" }, { "guid", "g2" }, { "active", !firstActive } },
            } } } } },
        };

        [Fact]
        public void Build_app_makes_the_named_application_active_before_it_compiles()
        {
            var host = new FakeHost();
            var calls = new List<string>();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                calls.Add(method);
                if (method == "project.devices") return TwoApplications(true);
                if (method == "app.activate")
                {
                    Assert.Equal("g2", p["application"]);
                    return new Dictionary<string, object> { { "application", "HMI_Application" }, { "previous", "Application" } };
                }
                return new Dictionary<string, object> { { "application", "HMI_Application" }, { "compiled", true }, { "messages", new object[0] } };
            });
            var (code, output, _) = Run(host, "build", "--app", "hmi_application");
            Assert.Equal(0, code);
            Assert.Equal(new[] { "project.devices", "app.activate", "app.build" }, calls.Where(method => method != "project.status"));
            Assert.Contains("HMI_Application is the active application now, instead of Application", output);
        }

        [Fact]
        public void Build_app_leaves_an_active_application_alone_and_refuses_an_unknown_one()
        {
            var host = new FakeHost();
            var calls = new List<string>();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                calls.Add(method);
                if (method == "project.devices") return TwoApplications(true);
                return new Dictionary<string, object> { { "application", "Application" }, { "compiled", true }, { "messages", new object[0] } };
            });
            var (code, output, _) = Run(host, "build", "--app", "Application");
            Assert.Equal(0, code);
            Assert.DoesNotContain("app.activate", calls);
            Assert.DoesNotContain("active application", output);

            calls.Clear();
            var (refused, refusal, error) = Run(host, "build", "--app", "Visu");
            Assert.Equal(1, refused);
            Assert.Contains("No application 'Visu' in the project; applications: Device/Application, Device/HMI_Application", error);
            Assert.Contains("Next: cts project list-devices", refusal);
            Assert.DoesNotContain("app.build", calls);
        }

        [Fact]
        public void A_clean_application_build_has_a_success_verdict()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "application", "Application" }, { "project_path", "C:/plant.project" }, { "compiled", true },
                { "elapsed_seconds", 2.5 }, { "messages", new object[0] },
            });
            var (code, output, _) = Run(host, "build");
            Assert.Equal(0, code);
            Assert.StartsWith("ok build errors=0 warnings=0\n", output);
        }
    }
}
