using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using DordieWatch.App.Data;
using DordieWatch.App.Services;
using DordieWatch.App.ViewModels;
using DordieWatch.App.Views;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using System;

namespace DordieWatch.App;

public partial class App : Application
{
    private ServiceProvider? _services;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        _services = ConfigureServices();
        using (var db = _services.GetRequiredService<IDbContextFactory<AppDbContext>>().CreateDbContext())
        {
            db.Database.EnsureCreated();
            EnsureSchema(db);
        }

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new MainWindow
            {
                DataContext = _services.GetRequiredService<MainWindowViewModel>()
            };
            desktop.ShutdownRequested += (_, _) => _services.Dispose();
        }

        base.OnFrameworkInitializationCompleted();
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
        services.AddSingleton<IVideoPreviewService, VideoPreviewService>();
        services.AddSingleton<IPreviewPlayerService, PreviewPlayerService>();
        services.AddSingleton<IImageCache, ImageCache>();
        services.AddSingleton<ILibraryService, LibraryService>();
        services.AddSingleton<IPlayerService, VlcPlayerService>();
        services.AddSingleton<INavigationService, NavigationService>();
        services.AddSingleton<MainWindowViewModel>();
        services.AddTransient<LibraryViewModel>();
        services.AddTransient<PlayerViewModel>();

        return services.BuildServiceProvider();
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
