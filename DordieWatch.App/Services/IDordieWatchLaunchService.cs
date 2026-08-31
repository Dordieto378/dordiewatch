namespace DordieWatch.App.Services;

public interface IDordieWatchLaunchService
{
    Task HandleStartupArgsAsync(IReadOnlyList<string> args, CancellationToken cancellationToken);
}
