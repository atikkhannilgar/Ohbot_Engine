using System.Globalization;

namespace ObotControl.Core.Services;

/// <summary>
/// Writes log lines to a daily rotating file under <c>gui/logs/</c> in the repo.
/// Files older than <see cref="RetentionDays"/> are pruned on startup.
/// </summary>
public sealed class LogFileService : IDisposable
{
    private const int RetentionDays = 14;

    private readonly string _logDir;
    private readonly object _lock = new();
    private StreamWriter? _writer;
    private string? _currentDate;

    public string LogDirectory => _logDir;

    public LogFileService(string guiRoot)
    {
        _logDir = Path.Combine(guiRoot, "logs");
        Directory.CreateDirectory(_logDir);
        PruneOldFiles();
    }

    public void Write(string level, string message)
    {
        var now = DateTimeOffset.Now;
        var date = now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        var timestamp = now.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        var line = $"{timestamp} [{level.ToUpperInvariant()}] {message}";

        lock (_lock)
        {
            if (_currentDate != date)
            {
                _writer?.Dispose();
                _writer = null;
                _currentDate = date;
            }

            _writer ??= new StreamWriter(
                Path.Combine(_logDir, $"obotcontrol-{date}.log"), append: true)
            {
                AutoFlush = true,
            };

            _writer.WriteLine(line);
        }
    }

    public void Dispose()
    {
        lock (_lock)
        {
            _writer?.Dispose();
            _writer = null;
        }
    }

    private void PruneOldFiles()
    {
        try
        {
            var cutoff = DateTime.Today.AddDays(-RetentionDays);
            foreach (var file in Directory.EnumerateFiles(_logDir, "obotcontrol-*.log"))
            {
                var name = Path.GetFileNameWithoutExtension(file);
                var datePart = name.Replace("obotcontrol-", "");
                if (DateTime.TryParseExact(datePart, "yyyy-MM-dd",
                        CultureInfo.InvariantCulture, DateTimeStyles.None, out var fileDate)
                    && fileDate < cutoff)
                {
                    File.Delete(file);
                }
            }
        }
        catch
        {
            // Best-effort cleanup; don't prevent app launch.
        }
    }
}
