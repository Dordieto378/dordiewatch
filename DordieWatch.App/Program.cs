using Avalonia;
using DordieWatch.App.Services;
using System;
using System.IO;

namespace DordieWatch.App;

internal static class Program
{
    public static IReadOnlyList<string> StartupArgs { get; private set; } = [];

    [STAThread]
    public static void Main(string[] args)
    {
        try
        {
            StartupArgs = args;
            WriteStartupLog("Main start");
            WindowsProtocolRegistration.TryRegister(Environment.ProcessPath);
            AppDomain.CurrentDomain.UnhandledException += (_, e) => WriteCrashLog(e.ExceptionObject);
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
            WriteStartupLog("Main exit");
        }
        catch (Exception ex)
        {
            WriteCrashLog(ex);
            throw;
        }
    }

    public static AppBuilder BuildAvaloniaApp()
    {
        return AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .LogToTrace();
    }

    internal static void WriteCrashLog(object? exception)
    {
        try
        {
            var directory = GetLogDirectory();
            Directory.CreateDirectory(directory);
            File.AppendAllText(
                Path.Combine(directory, "crash.log"),
                $"{DateTimeOffset.Now:u}{Environment.NewLine}{exception}{Environment.NewLine}{Environment.NewLine}");
        }
        catch
        {
            // Last-resort logging must never cause another crash.
        }
    }

    internal static void WriteStartupLog(string message)
    {
        try
        {
            var directory = GetLogDirectory();
            Directory.CreateDirectory(directory);
            File.AppendAllText(
                Path.Combine(directory, "startup.log"),
                $"{DateTimeOffset.Now:u} {message}{Environment.NewLine}");
        }
        catch
        {
            // Last-resort logging must never cause another crash.
        }
    }

    private static string GetLogDirectory()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "DordieWatch");
    }
}
