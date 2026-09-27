using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Models;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

/// <summary>
/// The full config editor: Speech (engine mode + per-engine voice settings + mouth-tuning
/// sliders), Motion, and Behaviors. Mouth-tuning sliders apply <em>live</em> (debounced
/// ~250 ms) so you can dial in lip-sync while the robot is talking  the engine reads
/// speech.mouth live. Everything else is Save/Revert with a dirty indicator.
/// </summary>
public partial class ConfigurationViewModel : ObservableObject
{
    private static readonly TimeSpan LiveApplyDebounce = TimeSpan.FromMilliseconds(250);
    private static readonly HashSet<string> MouthProps = new()
    {
        nameof(Fps), nameof(Gate), nameof(Gamma), nameof(Attack), nameof(Release),
        nameof(TopGain), nameof(BottomGain), nameof(TopMaxDelta), nameof(BottomMaxDelta),
        nameof(SyncOffset),
    };

    private readonly EngineApi _api;
    private readonly ConfigStore _store;
    private readonly LogsViewModel _logs;
    private bool _loading;
    private CancellationTokenSource? _liveApplyCts;

    public ConfigurationViewModel(EngineApi api, ConfigStore store, LogsViewModel logs)
    {
        _api = api;
        _store = store;
        _logs = logs;
        _store.Changed += (_, _) => LoadFrom(_store.Current);
        PropertyChanged += OnAnyPropertyChanged;
    }

    public string[] TtsEngines { get; } = { "auto", "edge", "kokoro", "gtts", "gemini", "piper", "local" };

    [ObservableProperty] private bool _connected;
    [ObservableProperty] private bool _isDirty;
    [ObservableProperty] private string _status = "";

    // Speech / TTS
    [ObservableProperty] private string _ttsEngine = "auto";
    [ObservableProperty] private string _geminiStyle = "";
    [ObservableProperty] private double _piperLengthScale = 1.0;
    [ObservableProperty] private int _localRateWpm = 175;

    // Mouth (live-applied)
    [ObservableProperty] private double _fps = 25;
    [ObservableProperty] private double _gate = 0.06;
    [ObservableProperty] private double _gamma = 0.65;
    [ObservableProperty] private double _attack = 0.65;
    [ObservableProperty] private double _release = 0.4;
    [ObservableProperty] private double _topGain = 3.5;
    [ObservableProperty] private double _bottomGain = 4.5;
    [ObservableProperty] private double _topMaxDelta = 5.0;
    [ObservableProperty] private double _bottomMaxDelta = 5.0;
    [ObservableProperty] private double _syncOffset;

    // Motion
    [ObservableProperty] private double _tickS = 0.05;
    [ObservableProperty] private double _rateLimit = 30;
    [ObservableProperty] private double _lipRateLimit = 200;
    [ObservableProperty] private double _writeEpsilon = 0.05;
    [ObservableProperty] private int _moveSpeed = 10;

    // Behaviors (four modules)
    public BehaviorModuleViewModel AutoBlink { get; } = new("Auto-blink");
    public BehaviorModuleViewModel ListeningNod { get; } = new("Listening nod");
    public BehaviorModuleViewModel SpeakingSway { get; } = new("Speaking sway");
    public BehaviorModuleViewModel IdleWander { get; } = new("Idle wander");

    /// <summary>All four modules, for the view to template uniformly.</summary>
    public IReadOnlyList<BehaviorModuleViewModel> BehaviorModules =>
        new[] { AutoBlink, ListeningNod, SpeakingSway, IdleWander };

    // -- load / apply ------------------------------------------------------------------

    public void LoadFrom(ObotConfig cfg)
    {
        _loading = true;
        try
        {
            TtsEngine = cfg.Speech.Tts.Engine;
            GeminiStyle = cfg.Speech.Tts.Gemini.Style;
            PiperLengthScale = cfg.Speech.Tts.Piper.LengthScale;
            LocalRateWpm = cfg.Speech.Tts.Local.RateWpm;

            var m = cfg.Speech.Mouth;
            Fps = m.Fps; Gate = m.Gate; Gamma = m.Gamma; Attack = m.Attack; Release = m.Release;
            TopGain = m.TopGain; BottomGain = m.BottomGain;
            TopMaxDelta = m.TopMaxDelta; BottomMaxDelta = m.BottomMaxDelta; SyncOffset = m.SyncOffsetS;

            var mo = cfg.Motion;
            TickS = mo.TickS; RateLimit = mo.RateLimit; LipRateLimit = mo.LipRateLimit;
            WriteEpsilon = mo.WriteEpsilon; MoveSpeed = mo.MoveSpeed;

            AutoBlink.LoadFrom(cfg.Behaviors.AutoBlink);
            ListeningNod.LoadFrom(cfg.Behaviors.ListeningNod);
            SpeakingSway.LoadFrom(cfg.Behaviors.SpeakingSway);
            IdleWander.LoadFrom(cfg.Behaviors.IdleWander);

            IsDirty = false;
        }
        finally { _loading = false; }
    }

    private ObotConfig BuildConfig()
    {
        var cfg = _store.Current.Clone();
        cfg.Speech.Tts.Engine = TtsEngine;
        cfg.Speech.Tts.Gemini.Style = GeminiStyle;
        cfg.Speech.Tts.Piper.LengthScale = PiperLengthScale;
        cfg.Speech.Tts.Local.RateWpm = LocalRateWpm;

        var m = cfg.Speech.Mouth;
        m.Fps = Fps; m.Gate = Gate; m.Gamma = Gamma; m.Attack = Attack; m.Release = Release;
        m.TopGain = TopGain; m.BottomGain = BottomGain;
        m.TopMaxDelta = TopMaxDelta; m.BottomMaxDelta = BottomMaxDelta; m.SyncOffsetS = SyncOffset;

        var mo = cfg.Motion;
        mo.TickS = TickS; mo.RateLimit = RateLimit; mo.LipRateLimit = LipRateLimit;
        mo.WriteEpsilon = WriteEpsilon; mo.MoveSpeed = MoveSpeed;

        AutoBlink.ApplyTo(cfg.Behaviors.AutoBlink);
        ListeningNod.ApplyTo(cfg.Behaviors.ListeningNod);
        SpeakingSway.ApplyTo(cfg.Behaviors.SpeakingSway);
        IdleWander.ApplyTo(cfg.Behaviors.IdleWander);
        return cfg;
    }

    private void OnAnyPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (_loading || e.PropertyName is null) return;
        if (e.PropertyName is nameof(IsDirty) or nameof(Status) or nameof(Connected)) return;

        IsDirty = true;
        if (MouthProps.Contains(e.PropertyName))
        {
            ScheduleLiveApply();
        }
    }

    private void ScheduleLiveApply()
    {
        _liveApplyCts?.Cancel();
        var cts = new CancellationTokenSource();
        _liveApplyCts = cts;
        _ = LiveApplyAsync(cts.Token);
    }

    private async Task LiveApplyAsync(CancellationToken ct)
    {
        try
        {
            await Task.Delay(LiveApplyDebounce, ct).ConfigureAwait(false);
            if (ct.IsCancellationRequested || !Connected) return;
            await _store.SaveAsync(BuildConfig());
            Status = "mouth tuning applied live";
        }
        catch (OperationCanceledException) { /* superseded by a newer edit */ }
        catch (Exception ex) { _logs.Append("error", $"live apply failed: {ex.Message}"); }
    }

    [RelayCommand]
    private async Task SaveAsync()
    {
        try
        {
            await _store.SaveAsync(BuildConfig());
            IsDirty = false;
            Status = "saved";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"save failed: {ex.Message}");
            Status = $"save failed: {ex.Message}";
        }
    }

    [RelayCommand]
    private void Revert()
    {
        LoadFrom(_store.Current);
        Status = "reverted";
    }

    /// <summary>Re-read config from the engine (config.json), discarding edits.</summary>
    [RelayCommand]
    private async Task ReloadAsync()
    {
        try
        {
            await _store.LoadAsync();   // fires Changed -> LoadFrom
            Status = "reloaded from config.json";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"reload failed: {ex.Message}");
            Status = $"reload failed: {ex.Message}";
        }
    }

    public void OnConnectionChanged(bool connected) => Connected = connected;
}

/// <summary>One ambient behavior module's tunables (enable + interval + intensity).</summary>
public partial class BehaviorModuleViewModel : ObservableObject
{
    public BehaviorModuleViewModel(string title) => Title = title;

    public string Title { get; }

    [ObservableProperty] private bool _enabled = true;
    [ObservableProperty] private double _minIntervalS = 2.0;
    [ObservableProperty] private double _maxIntervalS = 6.0;
    [ObservableProperty] private double _intensity = 1.0;

    public void LoadFrom(ModuleConfig m)
    {
        Enabled = m.Enabled;
        MinIntervalS = m.MinIntervalS;
        MaxIntervalS = m.MaxIntervalS;
        Intensity = m.Intensity;
    }

    public void ApplyTo(ModuleConfig m)
    {
        m.Enabled = Enabled;
        m.MinIntervalS = MinIntervalS;
        m.MaxIntervalS = MaxIntervalS;
        m.Intensity = Intensity;
    }
}
