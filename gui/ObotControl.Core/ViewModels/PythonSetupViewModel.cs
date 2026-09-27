using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

public enum PythonSetupStatusKind { Pending, Busy, Ready, Error }

/// <summary>
/// Owns Python environment discovery/provisioning so the engine can be launched without
/// anyone touching a terminal. Prefers an existing venv or system Python 3.12 already on
/// this machine (surfaced as a picker when more than one is found); "set up automatically"
///  download + silent-install a private Python, then build a venv from it  is always the
/// last option in the list. Runs standalone, before any engine connection exists.
/// </summary>
public partial class PythonSetupViewModel : ObservableObject
{
    private readonly PythonEnvironmentService _service;
    private readonly GuiSettingsStore _settings;
    private readonly LogsViewModel _logs;
    private string _repoRoot = "";
    private CancellationTokenSource? _cts;
    // Suppresses the auto-persist/auto-prepare reaction while candidates are (re)populated.
    private bool _loading;

    public PythonSetupViewModel(PythonEnvironmentService service, GuiSettingsStore settings, LogsViewModel logs)
    {
        _service = service;
        _settings = settings;
        _logs = logs;
    }

    public bool IsSupported => _service.IsSupported;

    public ObservableCollection<PythonCandidate> Candidates { get; } = new();
    public ObservableCollection<string> RecentLines { get; } = new();

    [ObservableProperty] private PythonCandidate? _selectedCandidate;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(StatusKind))]
    private bool _isReady;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(StatusKind))]
    private bool _isBusy;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(StatusKind))]
    private bool _isError;

    [ObservableProperty] private string _statusText = "Checking for an existing Python environment…";
    [ObservableProperty] private double _percent;
    [ObservableProperty] private bool _indeterminate = true;

    public PythonSetupStatusKind StatusKind =>
        IsBusy ? PythonSetupStatusKind.Busy :
        IsError ? PythonSetupStatusKind.Error :
        IsReady ? PythonSetupStatusKind.Ready :
        PythonSetupStatusKind.Pending;

    /// <summary>Fast local-only check + kick off the fuller background discovery. Called once
    /// by the shell after the repo root is resolved.</summary>
    public void Initialize(string repoRoot)
    {
        _repoRoot = repoRoot;
        var remembered = _settings.Load().SelectedPythonPath;
        var status = _service.CheckStatus(repoRoot, remembered);
        IsReady = status.IsReady;
        IsError = false;
        StatusText = status.Message;
        _ = RefreshAsync();
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        if (string.IsNullOrWhiteSpace(_repoRoot)) return;
        try
        {
            var found = await _service.DiscoverCandidatesAsync(_repoRoot).ConfigureAwait(true);
            _loading = true;
            try
            {
                Candidates.Clear();
                foreach (var c in found) Candidates.Add(c);
            }
            finally { _loading = false; }
            SelectDefault(found);
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"python environment discovery failed: {ex.Message}");
        }
    }

    private void SelectDefault(List<PythonCandidate> found)
    {
        var remembered = _settings.Load().SelectedPythonPath;
        var byRemembered = remembered is null ? null : found.FirstOrDefault(c => c.PythonExePath == remembered);
        var readyVenvs = found.Where(c => c.Kind == PythonCandidateKind.ExistingVenv && c.ObotInstalled == true).ToList();

        var pick = byRemembered
            ?? (readyVenvs.Count == 1 ? readyVenvs[0] : null)
            ?? found.FirstOrDefault(c => c.Kind == PythonCandidateKind.ExistingVenv)
            ?? found.FirstOrDefault(c => c.Kind == PythonCandidateKind.SystemInterpreter)
            ?? found.FirstOrDefault();

        _loading = true;
        try { SelectedCandidate = pick; }
        finally { _loading = false; }

        ApplySelectionStatus(pick);
    }

    private void ApplySelectionStatus(PythonCandidate? candidate)
    {
        if (candidate is { Kind: PythonCandidateKind.ExistingVenv, ObotInstalled: true })
        {
            IsReady = true;
            IsError = false;
            StatusText = $"Ready  using {candidate.DisplayName}";
        }
        else if (candidate is null)
        {
            IsReady = false;
            StatusText = "No Python 3.12 environment found yet.";
        }
        else
        {
            IsReady = false;
            StatusText = $"{candidate.DisplayName} needs to be prepared.";
        }
    }

    partial void OnSelectedCandidateChanged(PythonCandidate? value)
    {
        if (_loading || value is null) return;
        var settings = _settings.Load();
        settings.SelectedPythonPath = value.PythonExePath;
        _settings.Save(settings);
        ApplySelectionStatus(value);
        if (!IsReady) _ = PrepareAsync();
    }

    partial void OnIsBusyChanged(bool value) => PrepareCommand.NotifyCanExecuteChanged();

    [RelayCommand(CanExecute = nameof(CanPrepare))]
    private async Task PrepareAsync()
    {
        if (SelectedCandidate is null || IsBusy) return;
        var candidate = SelectedCandidate;
        IsBusy = true;
        IsError = false;
        RecentLines.Clear();
        _cts = new CancellationTokenSource();
        var progress = new Progress<SetupProgress>(p =>
        {
            if (p.PercentComplete is { } pct) { Percent = pct; Indeterminate = false; }
            else { Indeterminate = true; }
            StatusText = p.Message;
            RecentLines.Add(p.Message);
            while (RecentLines.Count > 200) RecentLines.RemoveAt(0);
            _logs.Append(p.IsError ? "error" : "info", $"[python-setup:{p.Stage}] {p.Message}");
        });

        try
        {
            var result = await _service.EnsureAsync(candidate, _repoRoot, progress, _cts.Token).ConfigureAwait(true);
            IsReady = result.IsReady;
            IsError = !result.IsReady;
            StatusText = result.Message;
            if (result.IsReady && result.Active is { } active)
            {
                ReplaceCandidate(candidate, active);
                var settings = _settings.Load();
                settings.SelectedPythonPath = active.PythonExePath;
                _settings.Save(settings);
            }
        }
        catch (OperationCanceledException)
        {
            StatusText = "Setup cancelled.";
        }
        catch (Exception ex)
        {
            IsError = true;
            StatusText = $"Setup failed: {ex.Message}";
            _logs.Append("error", $"python environment setup failed: {ex.Message}");
        }
        finally
        {
            IsBusy = false;
            _cts = null;
        }
    }

    private bool CanPrepare() => !IsBusy;

    [RelayCommand]
    private void Cancel() => _cts?.Cancel();

    private void ReplaceCandidate(PythonCandidate previous, PythonCandidate replacement)
    {
        _loading = true;
        try
        {
            var idx = Candidates.IndexOf(previous);
            if (idx >= 0) Candidates[idx] = replacement; else Candidates.Add(replacement);
            SelectedCandidate = replacement;
        }
        finally { _loading = false; }
    }
}
