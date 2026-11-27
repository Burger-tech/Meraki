using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows.Forms;

internal static class FoxhoundLauncher
{
    [STAThread]
    private static int Main()
    {
        try
        {
            var package = InstallPackage();
            var script = Path.Combine(package, "scripts", "foxhound-launcher.ps1");
            var shell = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");
            using (Process.Start(new ProcessStartInfo(shell,
                "-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File \"" + script + "\"")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = package
            })) { }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Foxhound Launcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string InstallPackage()
    {
        using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("Foxhound.Package"))
        using (var sha = SHA256.Create())
        {
            if (payload == null) throw new InvalidOperationException("The launcher package is missing.");
            var version = BitConverter.ToString(sha.ComputeHash(payload)).Replace("-", "").ToLowerInvariant();
            var localData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (String.IsNullOrWhiteSpace(localData))
                localData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var installs = Path.GetFullPath(Path.Combine(localData, "Foxhound", "packages"));
            var destination = Path.Combine(installs, version);
            if (Directory.Exists(destination)) return destination;

            var staging = Path.Combine(installs, Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(staging);
            try
            {
                payload.Position = 0;
                using (var archive = new ZipArchive(payload, ZipArchiveMode.Read, true))
                    archive.ExtractToDirectory(staging);
                try { Directory.Move(staging, destination); }
                catch (IOException) { if (!Directory.Exists(destination)) throw; }
            }
            finally
            {
                if (staging.StartsWith(installs + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(staging))
                    Directory.Delete(staging, true);
            }
            return destination;
        }
    }
}
