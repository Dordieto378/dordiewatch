using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;

namespace DordieWatch.App.Services;

public sealed class VideoPreviewService(IAppPaths paths) : IVideoPreviewService
{
    private static readonly SemaphoreSlim FfmpegGate = new(1, 1);
    private readonly string? _ffmpegPath = ResolveFfmpegPath();

    public Task<EpisodePreview> EnsurePreviewAsync(string videoPath, CancellationToken cancellationToken)
    {
        return Task.Run(() => EnsurePreview(videoPath, cancellationToken), cancellationToken);
    }

    private EpisodePreview EnsurePreview(string videoPath, CancellationToken cancellationToken)
    {
        if (!File.Exists(videoPath) || string.IsNullOrWhiteSpace(_ffmpegPath))
        {
            return new EpisodePreview(null, []);
        }

        var video = new FileInfo(videoPath);
        var key = Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes($"{video.FullName}|{video.Length}|{video.LastWriteTimeUtc.Ticks}"))).ToLowerInvariant();
        var outputDirectory = Path.Combine(paths.PreviewCacheDirectory, key);
        Directory.CreateDirectory(outputDirectory);

        var thumbnail = Path.Combine(outputDirectory, "thumbnail.jpg");
        var frames = Enumerable.Range(1, 6)
            .Select(index => Path.Combine(outputDirectory, $"preview-{index:00}.jpg"))
            .ToArray();

        if (File.Exists(thumbnail) && frames.All(File.Exists))
        {
            return new EpisodePreview(thumbnail, frames.Where(File.Exists).ToArray());
        }

        for (var index = 0; index < frames.Length; index++)
        {
            var frame = frames[index];
            if (File.Exists(frame))
            {
                continue;
            }

            cancellationToken.ThrowIfCancellationRequested();
            ExtractFrame(video.FullName, frame, 30 + (index * 60), cancellationToken);
        }

        var firstFrame = frames.FirstOrDefault(File.Exists);
        if (File.Exists(firstFrame) && !File.Exists(thumbnail))
        {
            File.Copy(firstFrame, thumbnail, overwrite: true);
        }

        return new EpisodePreview(
            File.Exists(thumbnail) ? thumbnail : File.Exists(firstFrame) ? firstFrame : null,
            frames.Where(File.Exists).ToArray());
    }

    private bool ExtractFrame(string videoPath, string outputPath, int seekSeconds, CancellationToken cancellationToken)
    {
        var arguments =
            "-hide_banner -loglevel error " +
            $"-ss {seekSeconds} -i {Quote(videoPath)} " +
            "-map 0:v:0 -frames:v 1 " +
            "-vf \"scale=640:360:force_original_aspect_ratio=increase,crop=640:360\" " +
            "-q:v 3 -y " +
            Quote(outputPath);

        if (RunFfmpeg(arguments, cancellationToken))
        {
            return File.Exists(outputPath) && new FileInfo(outputPath).Length > 0;
        }

        arguments =
            "-hide_banner -loglevel error " +
            $"-ss 5 -i {Quote(videoPath)} " +
            "-map 0:v:0 -frames:v 1 " +
            "-vf \"scale=640:360:force_original_aspect_ratio=increase,crop=640:360\" " +
            "-q:v 3 -y " +
            Quote(outputPath);

        return RunFfmpeg(arguments, cancellationToken)
            && File.Exists(outputPath)
            && new FileInfo(outputPath).Length > 0;
    }

    private bool RunFfmpeg(string arguments, CancellationToken cancellationToken)
    {
        try
        {
            FfmpegGate.Wait(cancellationToken);
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = _ffmpegPath!,
                Arguments = arguments,
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardError = true,
                RedirectStandardOutput = true
            });
            if (process is null)
            {
                return false;
            }

            try
            {
                // Preview extraction must yield CPU time to active video playback.
                process.PriorityClass = ProcessPriorityClass.BelowNormal;
            }
            catch
            {
                // Some environments do not allow changing process priority.
            }

            if (!process.WaitForExit(12_000))
            {
                try
                {
                    process.Kill(entireProcessTree: true);
                }
                catch
                {
                    // Ignore kill failure.
                }

                return false;
            }

            cancellationToken.ThrowIfCancellationRequested();
            return process.ExitCode == 0;
        }
        catch
        {
            return false;
        }
        finally
        {
            try
            {
                FfmpegGate.Release();
            }
            catch (SemaphoreFullException)
            {
                // The gate was not acquired.
            }
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static string? ResolveFfmpegPath()
    {
        var candidates = new[]
        {
            Environment.GetEnvironmentVariable("DORDIEWATCH_FFMPEG"),
            Path.Combine(AppContext.BaseDirectory, "ffmpeg.exe"),
            @"C:\ffmpeg\bin\ffmpeg.exe",
            "ffmpeg"
        };

        return candidates.FirstOrDefault(candidate =>
            !string.IsNullOrWhiteSpace(candidate)
            && (candidate == "ffmpeg" || File.Exists(candidate)));
    }
}
