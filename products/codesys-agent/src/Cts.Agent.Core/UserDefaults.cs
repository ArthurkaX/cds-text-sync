using System;

namespace Cts.Agent
{
    // The user's defaults.json, the layer between cts's own defaults and a
    // sync folder's cds-text-sync.json: %APPDATA%\cds-text-sync on Windows,
    // $XDG_CONFIG_HOME (else ~/.config)/cds-text-sync elsewhere.
    public static class UserDefaults
    {
        public static string Path
        {
            get
            {
                var windows = System.IO.Path.DirectorySeparatorChar == '\\';
                var config = Environment.GetEnvironmentVariable(windows ? "APPDATA" : "XDG_CONFIG_HOME");
                if (string.IsNullOrEmpty(config))
                    config = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), windows ? "AppData/Roaming" : ".config");
                return System.IO.Path.Combine(config, "cds-text-sync", "defaults.json");
            }
        }
    }
}
