using System.Collections.ObjectModel;
using System.Diagnostics;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Models;
using ObotControl.Core.Protocol;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

/// <summary>
/// The session dashboard: pick a backend/model/controller, start/stop a conversation,
/// type turns, interrupt, flip the mic, and watch the live transcript, state indicator,
/// active TTS engine and face preview  all driven by engine events.
/// </summary>
public partial class DashboardViewModel : ObservableObject
{
    private readonly EngineApi _api;
    private readonly LogsViewModel _logs;
    private readonly GuiSettingsStore _settings;

    public DashboardViewModel(EngineApi api, LogsViewModel logs, GuiSettingsStore settings)
    {
        _api = api;
        _logs = logs;
        _settings = settings;

        // Restore the last-used backend/controller so a restart doesn't reset the
        // session picker back to the defaults (config.json only remembers per-backend
        // model MRUs, not which backend/controller/model was last selected).
        var remembered = _settings.Load();
        if (remembered.DashboardBackend is { } backend && Backends.Contains(backend))
            SelectedBackend = backend;
        if (remembered.DashboardController is { } controller && Controllers.Contains(controller))
            SelectedController = controller;
    }

    public string[] Backends { get; } = { "scripted", "gemini", "ollama" };
    public string[] Controllers { get; } = { "virtual", "sim", "console", "hardware" };
    public string[] MicModes { get; } = { "muted", "vad", "ptt" };

    public ObservableCollection<string> Models { get; } = new();
    public ObservableCollection<TranscriptItem> Transcript { get; } = new();
    public JointPose Pose { get; } = new();

    [ObservableProperty] private string _selectedBackend = "scripted";
    [ObservableProperty] private string _selectedController = "virtual";
    [ObservableProperty] private string? _selectedModel;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsPtt))]
    private string _micMode = "muted";

    [ObservableProperty] private string _inputText = "";

    // Push-to-talk hotkey (window-focused). Default Space; configurable via "Set…".
    [ObservableProperty] private string _pttKey = "Space";
    [ObservableProperty] private bool _capturingHotkey;

    public bool IsPtt => MicMode == "ptt";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanStart))]
    [NotifyPropertyChangedFor(nameof(CanConverse))]
    private bool _sessionActive;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanStart))]
    [NotifyPropertyChangedFor(nameof(CanConverse))]
    private bool _connected;
    [ObservableProperty] private BotState _state = BotState.Idle;
    [ObservableProperty] private string _activeEngine = "";

    /// <summary>Emotion currently active on the engine  mirrors get_state/session_start/stop
    /// so a reconnect to an already-running session shows the real pose, not just "Neutral".
    /// Kept in sync live too, via the "emotion" event (see HandleEvent below).</summary>
    [ObservableProperty] private string _emotion = "Neutral";

    // Live "as you talk" line: the interim transcript while the user is still speaking.
    // Empty/null hides it; committed on the final transcript event.
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasPendingUser))]
    private string? _pendingUserText;

    public bool HasPendingUser => !string.IsNullOrEmpty(PendingUserText);

    /// <summary>A session start is in flight. Drives the progress panel on the dashboard:
    /// starting a session takes ~15 s (backend handshake, TTS model warm-up, mic ambient
    /// calibration), which looks like a hang without visible feedback.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanStart))]
    private bool _isStarting;

    /// <summary>Seconds since the current start began, so the wait shows visible movement.</summary>
    [ObservableProperty] private double _startElapsedSeconds;

    public bool RequiresModel => SelectedBackend is "gemini" or "ollama";
    public bool CanStart => Connected && !SessionActive && !IsStarting;
    public bool CanConverse => Connected && SessionActive;

    // -- session control ---------------------------------------------------------------

    [RelayCommand]
    private async Task RefreshModelsAsync()
    {
        try
        {
            List<string> models = SelectedBackend switch
            {
                "gemini" => await _api.ListGeminiModelsAsync(),
                "ollama" => await _api.ListOllamaModelsAsync(),
                _ => new List<string>(),
            };
            Models.Clear();
            foreach (var m in models) Models.Add(m);
            if (SelectedModel is null && Models.Count > 0)
            {
                var remembered = SelectedBackend switch
                {
                    "gemini" => _settings.Load().DashboardGeminiModel,
                    "ollama" => _settings.Load().DashboardOllamaModel,
                    _ => null,
                };
                SelectedModel = remembered is not null && Models.Contains(remembered) ? remembered : Models[0];
            }
            _logs.Append("info", $"{SelectedBackend}: {models.Count} model(s)");
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"list models failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private async Task StartSessionAsync()
    {
        if (IsStarting) return;

        IsStarting = true;
        StartElapsedSeconds = 0;
        using var done = new CancellationTokenSource();
        var ticker = TrackStartElapsedAsync(done.Token);
        try
        {
            var desiredMic = MicMode;
            var state = await _api.StartSessionAsync(
                SelectedBackend, SelectedModel ?? "", SelectedController);
            ApplyState(state);
            // Session always starts muted; re-apply a mode the user already chose.
            if (!string.Equals(desiredMic, "muted", StringComparison.OrdinalIgnoreCase))
                MicMode = desiredMic;
            Transcript.Add(new TranscriptItem
            {
                Kind = TranscriptKind.System,
                Text = $"Session started · {SelectedBackend} · {SelectedController}",
            });
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"session_start failed: {ex.Message}");
        }
        finally
        {
            done.Cancel();
            await ticker;
            IsStarting = false;
        }
    }

    /// <summary>Ticks the elapsed counter while a start is in flight. An indeterminate bar
    /// alone still reads as "stuck" over a 15 s wait; a moving number does not.</summary>
    private async Task TrackStartElapsedAsync(CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(250, ct);
                StartElapsedSeconds = sw.Elapsed.TotalSeconds;
            }
        }
        catch (OperationCanceledException)
        {
            // Expected: the start finished.
        }
    }

    [RelayCommand]
    private async Task StopSessionAsync()
    {
        try
        {
            var state = await _api.StopSessionAsync();
            ApplyState(state);
            Transcript.Add(new TranscriptItem { Kind = TranscriptKind.System, Text = "Session stopped" });
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"session_stop failed: {ex.Message}");
        }
    }

    /// <summary>Quick-switch model/backend without a manual stop: restart the session.</summary>
    [RelayCommand]
    private async Task SwitchAsync()
    {
        if (!SessionActive) { await StartSessionAsync(); return; }
        await StopSessionAsync();
        await StartSessionAsync();
    }

    // -- conversation ------------------------------------------------------------------

    [RelayCommand]
    private async Task SendAsync()
    {
        var text = InputText.Trim();
        if (text.Length == 0 || !SessionActive) return;
        InputText = "";
        try { await _api.SendTextAsync(text); }
        catch (Exception ex) { _logs.Append("error", $"send_text failed: {ex.Message}"); }
    }

    [RelayCommand]
    private async Task InterruptAsync()
    {
        try { await _api.InterruptAsync(); }
        catch (Exception ex) { _logs.Append("error", $"interrupt failed: {ex.Message}"); }
    }

    partial void OnMicModeChanged(string value) => _ = ApplyMicModeAsync(value);

    private async Task ApplyMicModeAsync(string mode)
    {
        if (!SessionActive) return;
        try { await _api.SetMicModeAsync(mode); }
        catch (Exception ex) { _logs.Append("error", $"set_mic_mode failed: {ex.Message}"); }
    }

    // -- push-to-talk ------------------------------------------------------------------

    /// <summary>Arm one push-to-talk capture (the Talk button or the hotkey).</summary>
    [RelayCommand]
    private async Task TriggerPttAsync()
    {
        if (!SessionActive) return;
        try { await _api.TriggerPttAsync(); }
        catch (Exception ex) { _logs.Append("error", $"push-to-talk failed: {ex.Message}"); }
    }

    /// <summary>Begin capturing the next key press as the new push-to-talk hotkey.</summary>
    [RelayCommand]
    private void StartCaptureHotkey() => CapturingHotkey = true;

    /// <summary>Handle a window key press. Returns true if consumed (rebinding, or a PTT trigger).</summary>
    public bool HandleHotkey(string key)
    {
        if (CapturingHotkey)
        {
            PttKey = key;
            CapturingHotkey = false;
            return true;
        }
        if (SessionActive && IsPtt && string.Equals(key, PttKey, StringComparison.OrdinalIgnoreCase))
        {
            _ = TriggerPttAsync();
            return true;
        }
        return false;
    }

    partial void OnSelectedBackendChanged(string value)
    {
        Models.Clear();
        SelectedModel = null;
        OnPropertyChanged(nameof(RequiresModel));
        UpdateSettings(s => s.DashboardBackend = value);
    }

    partial void OnSelectedControllerChanged(string value) =>
        UpdateSettings(s => s.DashboardController = value);

    partial void OnSelectedModelChanged(string? value)
    {
        if (value is null) return;
        UpdateSettings(s =>
        {
            if (SelectedBackend == "gemini") s.DashboardGeminiModel = value;
            else if (SelectedBackend == "ollama") s.DashboardOllamaModel = value;
        });
    }

    private void UpdateSettings(Action<GuiSettings> mutate)
    {
        var settings = _settings.Load();
        mutate(settings);
        _settings.Save(settings);
    }

    // -- event handling ----------------------------------------------------------------

    public void HandleEvent(EngineEvent evt)
    {
        switch (evt.Topic)
        {
            case Topics.State:
                var s = ObotJson.Deserialize<StateEvent>(evt.Data);
                if (s is not null) State = s.Parsed;
                break;
            case Topics.Transcript:
                HandleTranscript(ObotJson.Deserialize<TranscriptEvent>(evt.Data));
                break;
            case Topics.Speech:
                HandleSpeech(ObotJson.Deserialize<SpeechEvent>(evt.Data));
                break;
            case Topics.Action:
                var a = ObotJson.Deserialize<ActionEvent>(evt.Data);
                if (a is not null) Transcript.Add(new TranscriptItem { Kind = TranscriptKind.Action, Text = a.Name });
                break;
            case Topics.Emotion:
                var em = ObotJson.Deserialize<EmotionEvent>(evt.Data);
                if (em is not null)
                {
                    Transcript.Add(new TranscriptItem { Kind = TranscriptKind.Emotion, Text = em.Name });
                    Emotion = em.Name;
                }
                break;
            case Topics.Joints:
                var j = ObotJson.Deserialize<JointsEvent>(evt.Data);
                if (j is not null) Pose.Update(j);
                break;
        }
    }

    private void HandleTranscript(TranscriptEvent? t)
    {
        if (t is null) return;
        if (t.Partial)
        {
            // Interim: show a live line ("listening…" until words arrive from streaming STT).
            PendingUserText = string.IsNullOrEmpty(t.Text) ? "🎤 listening…" : t.Text;
        }
        else
        {
            // Final: commit a real utterance; an empty final just clears the live line.
            if (!string.IsNullOrWhiteSpace(t.Text))
            {
                Transcript.Add(new TranscriptItem { Kind = TranscriptKind.User, Text = t.Text });
            }
            PendingUserText = null;
        }
    }

    private void HandleSpeech(SpeechEvent? speech)
    {
        if (speech is null) return;
        if (!string.IsNullOrEmpty(speech.Engine)) ActiveEngine = speech.Engine!;
        switch (speech.Event)
        {
            case "spoken" when !string.IsNullOrEmpty(speech.Text):
                Transcript.Add(new TranscriptItem { Kind = TranscriptKind.Bot, Text = speech.Text! });
                break;
            case "cutoff":
            case "interrupted":
                MarkLastBotCutOff();
                break;
        }
    }

    private void MarkLastBotCutOff()
    {
        for (var i = Transcript.Count - 1; i >= 0; i--)
        {
            if (Transcript[i].Kind == TranscriptKind.Bot)
            {
                Transcript[i].CutOff = true;
                return;
            }
        }
    }

    public void ApplyState(SessionState state)
    {
        SessionActive = state.Session;
        if (!state.Session) PendingUserText = null;
        // Set the backing field so we do not fire set_mic_mode (ApplyState is a
        // mirror of engine state, not a user gesture — and racing muted/vad RPCs
        // after StartSession left the engine muted while the UI showed vad).
        if (!string.Equals(_micMode, state.MicMode, StringComparison.Ordinal))
        {
            _micMode = state.MicMode;
            OnPropertyChanged(nameof(MicMode));
            OnPropertyChanged(nameof(IsPtt));
        }
        ActiveEngine = state.TtsEngineActive ?? "";
        Emotion = state.Emotion;
        State = state.State switch
        {
            "speaking" => BotState.Speaking,
            "listening" => BotState.Listening,
            _ => BotState.Idle,
        };
    }

    public void OnConnectionChanged(bool connected)
    {
        Connected = connected;
        if (!connected)
        {
            SessionActive = false;
            State = BotState.Idle;
            PendingUserText = null;
        }
    }
}
