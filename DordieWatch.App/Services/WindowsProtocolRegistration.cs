using Microsoft.Win32;
using System.Runtime.InteropServices;

namespace DordieWatch.App.Services;

public static class WindowsProtocolRegistration
{
    public static void TryRegister(string? executablePath)
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows)
            || string.IsNullOrWhiteSpace(executablePath))
        {
            return;
        }

        try
        {
            var expectedCommand = $"\"{executablePath}\" \"%1\"";
            using (var existingCommandKey = Registry.CurrentUser.OpenSubKey(@"Software\Classes\dordiewatch\shell\open\command"))
            {
                if (string.Equals(existingCommandKey?.GetValue("") as string, expectedCommand, StringComparison.Ordinal))
                {
                    return;
                }
            }

            using var protocolKey = Registry.CurrentUser.CreateSubKey(@"Software\Classes\dordiewatch");
            protocolKey?.SetValue("", "URL:DordieWatch Protocol");
            protocolKey?.SetValue("URL Protocol", "");

            using var commandKey = Registry.CurrentUser.CreateSubKey(@"Software\Classes\dordiewatch\shell\open\command");
            commandKey?.SetValue("", expectedCommand);
        }
        catch
        {
            // Protocol registration is best-effort; the app can still run normally.
        }
    }
}
