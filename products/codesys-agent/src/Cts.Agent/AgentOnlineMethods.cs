// AgentHost's registrations of the application and PLC methods (app.*, plc.*).

namespace Cts.Agent
{
    public sealed partial class AgentHost
    {
        void RegisterOnlineMethods()
        {
            // Compile the active application (`cts build`).
            _router.Register("app.build", (req, s) => _ide.OnUi("app.build", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.Build(req.Bool("install", false), req.Bool("all_objects", false))));
            // Run or stop the logged-in application (`cts start` / `cts stop`).
            _router.Register("app.start", (req, s) => _ide.RunApplication(true, StartTimeout.Parse(req, UiTimeoutMs)));
            _router.Register("app.stop", (req, s) => _ide.RunApplication(false, StartTimeout.Parse(req, UiTimeoutMs)));
            // A full download of the active application, or an online change, logging in when needed (`cts download`).
            _router.Register("app.download", (req, s) => _ide.DownloadApplication(req.Bool("start", true), req.Bool("online_change", false), StartTimeout.Parse(req, UiTimeoutMs)));
            // Store the logged-in application as the PLC's boot application (`cts boot-app`).
            _router.Register("app.bootapp", (req, s) => _ide.OnUi("app.bootapp", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.CreateBootApplication()));
            // Reset the logged-in application (`cts reset`).
            _router.Register("app.reset", (req, s) => _ide.ResetApplication(req.String("kind", "warm"), req.Bool("force", false), StartTimeout.Parse(req, UiTimeoutMs)));
            // Whether the PLC runs the code the IDE generated last (`cts plc-crc`).
            _router.Register("app.crc", (req, s) => _ide.OnUi("app.crc", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.ApplicationChecksums()));
            // The entries of one directory on the PLC (`cts plc ls`).
            _router.Register("plc.files", (req, s) => _ide.PlcFiles(req.String("path", ""), StartTimeout.Parse(req, UiTimeoutMs)));
            // A file of this PC written to the PLC (`cts plc put`).
            _router.Register("plc.upload", (req, s) => _ide.PlcUpload(req.String("src"), req.String("dest", ""), StartTimeout.Parse(req, UiTimeoutMs)));
            // The runtime's loggers, and the entries one of them holds (`cts plc-log`).
            _router.Register("plc.loggers", (req, s) => _ide.PlcLoggers(StartTimeout.Parse(req, UiTimeoutMs)));
            _router.Register("plc.log", (req, s) => _ide.PlcLog(req.String("logger", ""), StartTimeout.Parse(req, UiTimeoutMs)));
            // A PLC file saved on this PC (`cts plc get`).
            _router.Register("plc.fetch", (req, s) => _ide.PlcFetch(req.String("file"), req.String("output"), StartTimeout.Parse(req, UiTimeoutMs)));
            // A file or directory on the PLC removed, made or moved (`cts plc rm|mkdir|mv`).
            _router.Register("plc.remove", (req, s) => _ide.PlcRemove(req.String("path"), req.Bool("recursive", false), StartTimeout.Parse(req, UiTimeoutMs)));
            _router.Register("plc.mkdir", (req, s) => _ide.PlcMakeDirectory(req.String("path"), StartTimeout.Parse(req, UiTimeoutMs)));
            _router.Register("plc.move", (req, s) => _ide.PlcMove(req.String("from"), req.String("to"), StartTimeout.Parse(req, UiTimeoutMs)));
            // The PLC's runtime and the applications it holds (`cts plc info`).
            _router.Register("plc.info", (req, s) => _ide.PlcInfo(StartTimeout.Parse(req, UiTimeoutMs)));
            // Log in without changing the PLC, pointed at `ip` first when given (`cts connect`).
            _router.Register("app.login", (req, s) => _ide.Login(req.String("ip", ""), req.String("gateway", ""), StartTimeout.Parse(req, UiTimeoutMs)));
            _router.Register("app.scan", (req, s) => _ide.Scan(req.String("gateway", ""), StartTimeout.Parse(req, UiTimeoutMs)));
            // End the online sessions (`cts disconnect`).
            _router.Register("app.logout", (req, s) => _ide.OnUi("app.logout", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.Logout(req.String("application", ""))));
            // Make one application the active one (test.app's switch and switch back).
            _router.Register("app.activate", (req, s) => _ide.OnUi("app.activate", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ActivateApplication(req.String("application"))));
        }
    }
}
