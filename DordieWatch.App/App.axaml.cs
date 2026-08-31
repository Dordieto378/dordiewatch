using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using DordieWatch.App.Data;
using DordieWatch.App.Services;
using DordieWatch.App.ViewModels;
using DordieWatch.App.Views;
using LibVLCSharp.Shared;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using System;

namespace DordieWatch.App;

public partial class App : Application
{
    private ServiceProvider? _services;

    public override void Initialize()
    {
        Program.WriteStartupLog("App Initialize start");
        AvaloniaXamlLoader.Load(this);
        Program.WriteStartupLog("App Initialize end");
    }

    public override void OnFrameworkInitializationCompleted()
    {
        Program.WriteStartupLog("Framework init start");
        _services = ConfigureServices();
        Program.WriteStartupLog("Services configured");
        using (var db = _services.GetRequiredService<IDbContextFactory<AppDbContext>>().CreateDbContext())
        {
            db.Database.EnsureCreated();
            EnsureSchema(db);
        }
        Program.WriteStartupLog("Database ready");

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new MainWindow
            {
                DataContext = _services.GetRequiredService<MainWindowViewModel>()
            };
            Program.WriteStartupLog("MainWindow assigned");
            desktop.ShutdownRequested += (_, _) => _services.Dispose();

            var launchService = _services.GetRequiredService<IDordieWatchLaunchService>();
            _ = launchService.HandleStartupArgsAsync(Program.StartupArgs, CancellationToken.None);
            _ = WarmPlaybackEngineAsync(_services);
        }

        base.OnFrameworkInitializationCompleted();
        Program.WriteStartupLog("Framework init end");
    }

    private static ServiceProvider ConfigureServices()
    {
        var services = new ServiceCollection();
        services.AddSingleton<IAppPaths, AppPaths>();
        services.AddDbContextFactory<AppDbContext>((provider, options) =>
        {
            var paths = provider.GetRequiredService<IAppPaths>();
            options.UseSqlite($"Data Source={paths.DatabasePath}");
        });

        services.AddSingleton<IMediaFileScanner, MediaFileScanner>();
        services.AddSingleton<IDordieListClient, DordieListClient>();
        services.AddSingleton(_ =>
        {
            Core.Initialize();
            return new LibVLC(
                "--avcodec-hw=any",
                "--no-video-title-show",
                "--no-osd");
        });
        services.AddSingleton<IVideoPreviewService, VideoPreviewService>();
        services.AddSingleton<IPreviewPlayerService, PreviewPlayerService>();
        services.AddSingleton<IImageCache, ImageCache>();
        services.AddSingleton<ILibraryService, LibraryService>();
        services.AddSingleton<IDordieWatchLaunchService, DordieWatchLaunchService>();
        services.AddSingleton<IPlayerService, VlcPlayerService>();
        services.AddSingleton<INavigationService, NavigationService>();
        services.AddSingleton<MainWindowViewModel>();
        services.AddTransient<LibraryViewModel>();
        services.AddTransient<PlayerViewModel>();

        return services.BuildServiceProvider();
    }

    private static async Task WarmPlaybackEngineAsync(IServiceProvider services)
    {
        try
        {
            await Task.Delay(750).ConfigureAwait(false);
            await Task.Run(() => services.GetRequiredService<IPlayerService>()).ConfigureAwait(false);
            Program.WriteStartupLog("Playback engine ready");
        }
        catch (ObjectDisposedException)
        {
            // The app was closed before the delayed warmup started.
        }
        catch (Exception exception)
        {
            Program.WriteCrashLog(exception);
        }
    }

    private static void EnsureSchema(AppDbContext db)
    {
        try
        {
            db.Database.ExecuteSqlRaw("ALTER TABLE MediaItems ADD COLUMN Category TEXT NOT NULL DEFAULT 'anime'");
        }
        catch
        {
            // Column already exists or the DB was freshly created with the current schema.
        }
    }
}
