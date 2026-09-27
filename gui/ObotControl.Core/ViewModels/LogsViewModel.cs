using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

public sealed record LogLine(DateTimeOffset Time, string Level, string Message)
{
    public string Display => $"{Time:HH:mm:ss}  {Message}";
}

/// <summary>
/// The log pane: engine stdout/stderr lines plus <c>log</c>/<c>error</c> events, capped so
/// a long session cannot grow without bound. Supports a simple level filter.
/// </summary>
public partial class LogsViewModel : ObservableObject
{
    private const int MaxLines = 2000;
    private readonly List<LogLine> _all = new();
    private LogFileService? _logFile;

    public ObservableCollection<LogLine> Lines { get; } = new();

    [ObservableProperty] private bool _showInfo = true;
    [ObservableProperty] private bool _showWarnings = true;
    [ObservableProperty] private bool _showErrors = true;

    public string? LogDirectory => _logFile?.LogDirectory;

    public void SetLogDirectory(string guiRoot)
    {
        _logFile ??= new LogFileService(guiRoot);
    }

    public void Append(string level, string message)
    {
        _logFile?.Write(level, message);
        var line = new LogLine(DateTimeOffset.Now, level, message);
        _all.Add(line);
        if (_all.Count > MaxLines) _all.RemoveRange(0, _all.Count - MaxLines);
        if (Passes(line))
        {
            Lines.Add(line);
            if (Lines.Count > MaxLines) Lines.RemoveAt(0);
        }
    }

    /// <summary>Classify a raw engine stdout line into a level by its inline tag.</summary>
    public void AppendRaw(string raw)
    {
        var level = raw.Contains("error", StringComparison.OrdinalIgnoreCase) ? "error"
            : raw.Contains("warn", StringComparison.OrdinalIgnoreCase) ? "warn"
            : "info";
        Append(level, raw);
    }

    private bool Passes(LogLine line) => line.Level switch
    {
        "error" => ShowErrors,
        "warn" => ShowWarnings,
        _ => ShowInfo,
    };

    private void Refilter()
    {
        Lines.Clear();
        foreach (var line in _all.Where(Passes))
        {
            Lines.Add(line);
        }
    }

    partial void OnShowInfoChanged(bool value) => Refilter();
    partial void OnShowWarningsChanged(bool value) => Refilter();
    partial void OnShowErrorsChanged(bool value) => Refilter();

    [RelayCommand]
    private void Clear()
    {
        _all.Clear();
        Lines.Clear();
    }
}
