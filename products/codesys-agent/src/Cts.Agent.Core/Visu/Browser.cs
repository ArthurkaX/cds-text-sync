using System;
using System.Diagnostics;
using System.IO;
using System.Linq;

namespace Cts.Visu
{
    internal static class Browser
    {
        // Where Chrome and Edge install; CHROME_PATH names another, PATH is last.
        static readonly string[] Candidates =
        {
            @"C:\Program Files\Google\Chrome\Application\chrome.exe",
            @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            @"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        };

        static string Find()
        {
            var configured = Environment.GetEnvironmentVariable("CHROME_PATH");
            if (!string.IsNullOrWhiteSpace(configured) && File.Exists(configured)) return configured;
            var onPath = (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator)
                .Select(directory => directory.Trim().Trim('"')).Where(directory => directory.Length > 0 && directory.IndexOfAny(Path.GetInvalidPathChars()) < 0)
                .SelectMany(directory => new[] { "chrome.exe", "msedge.exe" }.Select(name => Path.Combine(directory, name)));
            return Candidates.Concat(onPath).FirstOrDefault(File.Exists);
        }

        internal static string Rasterize(string svg, string png, int width, int height)
        {
            var browser = Find();
            if (browser == null) return null;
            var fullSvg = Path.GetFullPath(svg);
            var fullPng = Path.GetFullPath(png);
            var directory = Path.GetDirectoryName(fullPng);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            var start = new ProcessStartInfo
            {
                FileName = browser,
                Arguments = "--headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 "
                    + "--default-background-color=00000000 --window-size=" + width + "," + height
                    + " --screenshot=\"" + fullPng + "\" \"" + new Uri(fullSvg).AbsoluteUri + "\"",
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            try
            {
                using (var process = Process.Start(start))
                {
                    if (process == null || !process.WaitForExit(60000))
                    {
                        if (process != null) process.Kill();
                        return null;
                    }
                }
            }
            catch (Exception error) when (error is InvalidOperationException || error is IOException || error is System.ComponentModel.Win32Exception)
            {
                return null;
            }
            return File.Exists(fullPng) ? fullPng : null;
        }

        // Opens the page *file* in the default browser, else in Chrome or Edge
        // (a PC whose .html still belongs to the removed Internet Explorer);
        // false when neither starts.  The shell starts it: a child of cts
        // would hold the pipe the quick window reads cts' answer from.
        internal static bool Open(string file)
        {
            foreach (var start in new[] { new ProcessStartInfo(file), Find() is string browser ? new ProcessStartInfo(browser, "\"" + new Uri(file).AbsoluteUri + "\"") : null })
            {
                if (start == null) continue;
                start.UseShellExecute = true;
                try { Process.Start(start); return true; }
                catch (Exception error) when (error is System.ComponentModel.Win32Exception || error is InvalidOperationException) { }
            }
            return false;
        }
    }
}
