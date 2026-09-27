using System.IO.Compression;

namespace ObotControl.Core.Services;

/// <summary>One downloadable Vosk model offered by the auto-setup button.</summary>
public sealed record VoskModelOption(string DisplayName, string Url, string FolderName)
{
    public override string ToString() => DisplayName;
}

/// <summary>
/// Downloads a prebuilt Vosk speech-to-text model from alphacephei.com and unzips it into
/// <c>ohbotData/vosk/</c> (alongside the Piper/Kokoro TTS assets, which use the same
/// repo-root-relative convention)  no terminal, no manual unzip-and-point-config-at-it
/// dance. Mirrors <see cref="PythonEnvironmentService"/>'s download+progress shape so the
/// GUI can reuse the same <see cref="SetupProgress"/> record and progress-bar pattern.
/// </summary>
public sealed class VoskModelSetupService
{
    private static readonly HttpClient Http = new();

    public static IReadOnlyList<VoskModelOption> Catalog { get; } = new[]
    {
        new VoskModelOption(
            "English/fast (~40 MB, good for the Pi)",
            "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
            "vosk-model-small-en-us-0.15"),
        new VoskModelOption(
            "English/accurate (~1.8 GB)",
            "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
            "vosk-model-en-us-0.22"),
        new VoskModelOption(
            "German/fast (~45 MB, good for the Pi)",
            "https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip",
            "vosk-model-small-de-0.15"),
        new VoskModelOption(
            "German/accurate (~1.9 GB)",
            "https://alphacephei.com/vosk/models/vosk-model-de-0.21.zip",
            "vosk-model-de-0.21"),
    };

    /// <summary>Downloads (if not already cached) and unzips <paramref name="option"/> under
    /// <c>&lt;repoRoot&gt;/ohbotData/vosk/</c>, returning the folder to put in
    /// <c>audio.vosk_model_path</c> (contains <c>am/</c>, <c>conf/</c>, <c>graph/</c>).</summary>
    public async Task<string> DownloadAndInstallAsync(
        VoskModelOption option, string repoRoot, IProgress<SetupProgress> progress, CancellationToken ct)
    {
        var voskRoot = Path.Combine(repoRoot, "ohbotData", "vosk");
        Directory.CreateDirectory(voskRoot);
        var modelDir = Path.Combine(voskRoot, option.FolderName);

        if (Directory.Exists(Path.Combine(modelDir, "am")))
        {
            progress.Report(new SetupProgress("done", $"{option.FolderName} already downloaded", 100));
            return modelDir;
        }

        var cacheDir = Path.Combine(voskRoot, "cache");
        Directory.CreateDirectory(cacheDir);
        var zipPath = Path.Combine(cacheDir, option.FolderName + ".zip");

        if (!File.Exists(zipPath))
        {
            progress.Report(new SetupProgress("download", $"downloading {option.FolderName}…", 0));
            await DownloadFileAsync(option.Url, zipPath, progress, ct).ConfigureAwait(false);
        }
        else
        {
            progress.Report(new SetupProgress("download", "using cached archive", 100));
        }

        progress.Report(new SetupProgress("extract", $"unzipping {option.FolderName}…"));
        var extractTmp = Path.Combine(cacheDir, option.FolderName + "_extract_tmp");
        if (Directory.Exists(extractTmp)) Directory.Delete(extractTmp, recursive: true);
        ZipFile.ExtractToDirectory(zipPath, extractTmp);
        ct.ThrowIfCancellationRequested();

        // Vosk archives normally contain one top-level "<model-name>/" folder; fall back to
        // "whatever single directory came out" so an unexpected archive layout still works.
        var topLevelDirs = Directory.GetDirectories(extractTmp);
        var source = topLevelDirs.FirstOrDefault(d =>
                string.Equals(Path.GetFileName(d), option.FolderName, StringComparison.OrdinalIgnoreCase))
            ?? (topLevelDirs.Length == 1 ? topLevelDirs[0] : extractTmp);

        if (!Directory.Exists(Path.Combine(source, "am")))
        {
            Directory.Delete(extractTmp, recursive: true);
            File.Delete(zipPath);
            throw new InvalidOperationException(
                $"extracted archive did not contain the expected 'am/' folder  got: {string.Join(", ", topLevelDirs.Select(Path.GetFileName))}");
        }

        if (Directory.Exists(modelDir)) Directory.Delete(modelDir, recursive: true);
        Directory.Move(source, modelDir);
        if (Directory.Exists(extractTmp)) Directory.Delete(extractTmp, recursive: true);
        File.Delete(zipPath);

        progress.Report(new SetupProgress("done", $"{option.FolderName} ready", 100));
        return modelDir;
    }

    private static async Task DownloadFileAsync(
        string url, string destPath, IProgress<SetupProgress> progress, CancellationToken ct)
    {
        var tmpPath = destPath + ".tmp";
        using var response = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        var total = response.Content.Headers.ContentLength;

        await using (var httpStream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false))
        await using (var fileStream = File.Create(tmpPath))
        {
            var buffer = new byte[81920];
            long read = 0;
            int n;
            while ((n = await httpStream.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
            {
                await fileStream.WriteAsync(buffer.AsMemory(0, n), ct).ConfigureAwait(false);
                read += n;
                double? pct = total is > 0 ? Math.Round(read * 100.0 / total.Value, 1) : null;
                progress.Report(new SetupProgress("download", $"downloading… {read / 1_000_000.0:0.0} MB", pct));
            }
        }
        File.Move(tmpPath, destPath, overwrite: true);
    }
}
