using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Models;
using ObotControl.Core.Protocol;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

/// <summary>
/// First-run / device setup: API key, COM port, Ollama SSH, microphone (with a live
/// level test), STT engine, and TTS voices (with a "speak a test sentence" button).
/// Reads/writes the shared <see cref="ConfigStore"/>; the engine persists the file.
/// </summary>
public partial class SetupViewModel : ObservableObject
{
    private readonly EngineApi _api;
    private readonly ConfigStore _store;
    private readonly LogsViewModel _logs;
    private readonly VoskModelSetupService _voskService;
    private string _repoRoot = "";
    private CancellationTokenSource? _voskCts;
    // Suppresses the auto-persist reaction while we populate fields from config.
    private bool _loading;

    public SetupViewModel(
        EngineApi api, ConfigStore store, LogsViewModel logs, PythonSetupViewModel python, VoskModelSetupService voskService)
    {
        _api = api;
        _store = store;
        _logs = logs;
        _voskService = voskService;
        Python = python;
        _store.Changed += (_, _) => LoadFrom(_store.Current);
    }

    /// <summary>Step 0: guarantees a working Python environment before the engine can even
    /// be launched. Runs standalone, independent of the engine connection this page
    /// otherwise gates everything else on.</summary>
    public PythonSetupViewModel Python { get; }

    /// <summary>Repo root, needed to place downloaded Vosk models under ohbotData/vosk/. Set
    /// once by the shell after the repo root is resolved (mirrors Python.Initialize).</summary>
    public void SetRepoRoot(string repoRoot) => _repoRoot = repoRoot;

    public string[] SttEngines { get; } = { "google", "vosk" };
    public string[] TtsEngines { get; } = { "auto", "edge", "kokoro", "gtts", "gemini", "piper", "local" };

    public ObservableCollection<MicDevice> Mics { get; } = new();
    public ObservableCollection<string> GeminiVoices { get; } = new();
    public ObservableCollection<string> PiperVoices { get; } = new();
    public ObservableCollection<string> LocalVoices { get; } = new();
    public ObservableCollection<string> EdgeVoices { get; } = new();
    public ObservableCollection<string> KokoroVoices { get; } = new();
    public ObservableCollection<string> GttsAccents { get; } = new();

    [ObservableProperty] private bool _connected;

    // Credentials & device fields (mirrors of config sections).
    [ObservableProperty] private string _ohbotPort = OperatingSystem.IsWindows() ? "COM7" : "/dev/ttyACM0";
    [ObservableProperty] private string _geminiApiKey = "";
    [ObservableProperty] private string _sshHost = "";
    [ObservableProperty] private int _sshPort = 22;
    [ObservableProperty] private string _sshUser = "";
    [ObservableProperty] private string _sshKeyPath = "";
    [ObservableProperty] private string _remoteOllamaHost = "localhost";
    [ObservableProperty] private int _remoteOllamaPort = 11434;

    [ObservableProperty] private MicDevice? _selectedMic;
    [ObservableProperty] private string _sttEngine = "google";
    [ObservableProperty] private string _voskModelPath = "";

    public IReadOnlyList<VoskModelOption> VoskModelOptions => VoskModelSetupService.Catalog;
    [ObservableProperty] private VoskModelOption? _selectedVoskModelOption = VoskModelSetupService.Catalog[0];
    [ObservableProperty] private bool _voskSetupBusy;
    [ObservableProperty] private double _voskSetupPercent;
    [ObservableProperty] private bool _voskSetupIndeterminate;
    [ObservableProperty] private string _voskSetupStatus = "";

    [ObservableProperty] private string _ttsEngine = "auto";
    [ObservableProperty] private string? _geminiVoice;
    [ObservableProperty] private string? _piperVoice;
    [ObservableProperty] private string? _localVoice;
    [ObservableProperty] private string? _edgeVoice;
    [ObservableProperty] private string? _kokoroVoice;
    [ObservableProperty] private string? _gttsAccent;
    [ObservableProperty] private string _testText = "Hello, I am Ms. Mimic. This is a voice test.";

    [ObservableProperty] private double _micLevel;
    [ObservableProperty] private double _micPeak;
    [ObservableProperty] private bool _micTesting;
    [ObservableProperty] private string _status = "";

    // -- config <-> fields -------------------------------------------------------------

    public void LoadFrom(ObotConfig cfg)
    {
        bool prev = _loading;
        _loading = true;
        try
        {
        OhbotPort = cfg.OhbotPort;
        GeminiApiKey = cfg.GeminiApiKey;
        SshHost = cfg.OllamaSsh.Host;
        SshPort = cfg.OllamaSsh.Port;
        SshUser = cfg.OllamaSsh.User;
        SshKeyPath = cfg.OllamaSsh.KeyPath;
        RemoteOllamaHost = cfg.OllamaSsh.RemoteOllamaHost;
        RemoteOllamaPort = cfg.OllamaSsh.RemoteOllamaPort;
        SttEngine = string.IsNullOrEmpty(cfg.Audio.SttEngine) ? "google" : cfg.Audio.SttEngine;
        VoskModelPath = cfg.Audio.VoskModelPath;
        TtsEngine = cfg.Speech.Tts.Engine;
        GeminiVoice = cfg.Speech.Tts.Gemini.Voice;
        PiperVoice = cfg.Speech.Tts.Piper.Voice;
        LocalVoice = cfg.Speech.Tts.Local.Voice;
        EdgeVoice = cfg.Speech.Tts.Edge.Voice;
        KokoroVoice = cfg.Speech.Tts.Kokoro.Voice;
        GttsAccent = cfg.Speech.Tts.Gtts.Tld;
        SelectSavedMic(cfg.Audio.InputDeviceIndex);
        }
        finally { _loading = prev; }
    }

    partial void OnSelectedMicChanged(MicDevice? value)
    {
        // A microphone is a device setting: persist it immediately (like the console app's
        // picker) so the very next session actually uses it  no separate Save step needed.
        if (_loading || value is null || !Connected) return;
        _ = SaveAsync();
    }

    private void ApplyTo(ObotConfig cfg)
    {
        cfg.OhbotPort = OhbotPort;
        cfg.GeminiApiKey = GeminiApiKey;
        cfg.OllamaSsh.Host = SshHost;
        cfg.OllamaSsh.Port = SshPort;
        cfg.OllamaSsh.User = SshUser;
        cfg.OllamaSsh.KeyPath = SshKeyPath;
        cfg.OllamaSsh.RemoteOllamaHost = RemoteOllamaHost;
        cfg.OllamaSsh.RemoteOllamaPort = RemoteOllamaPort;
        cfg.Audio.InputDeviceIndex = SelectedMic is null || SelectedMic.Index < 0
            ? null
            : SelectedMic.Index;
        cfg.Audio.SttEngine = SttEngine;
        cfg.Audio.VoskModelPath = VoskModelPath;
        cfg.Speech.Tts.Engine = TtsEngine;
        if (GeminiVoice is not null) cfg.Speech.Tts.Gemini.Voice = GeminiVoice;
        if (PiperVoice is not null) cfg.Speech.Tts.Piper.Voice = PiperVoice;
        if (LocalVoice is not null) cfg.Speech.Tts.Local.Voice = LocalVoice;
        if (EdgeVoice is not null) cfg.Speech.Tts.Edge.Voice = EdgeVoice;
        if (KokoroVoice is not null) cfg.Speech.Tts.Kokoro.Voice = KokoroVoice;
        if (GttsAccent is not null) cfg.Speech.Tts.Gtts.Tld = GttsAccent;
    }

    /// <summary>Sentinel mic row: PortAudio / OS default input (config stores null).</summary>
    private static readonly MicDevice SystemDefaultMic = new()
    {
        Index = -1,
        Name = "System default",
    };

    private void SelectSavedMic(int? index)
    {
        if (index is null)
        {
            // Keep "System default" selected — do not leave Avalonia on the first physical mic.
            SelectedMic = Mics.FirstOrDefault(m => m.Index < 0) ?? SystemDefaultMic;
            return;
        }
        SelectedMic = Mics.FirstOrDefault(m => m.Index == index.Value)
            ?? Mics.FirstOrDefault(m => m.Index < 0)
            ?? SystemDefaultMic;
    }

    // -- commands ----------------------------------------------------------------------

    [RelayCommand]
    private async Task RefreshDevicesAsync()
    {
        _loading = true;  // populating device/voice lists must not trigger auto-persist
        try
        {
            var mics = await _api.ListMicsAsync();
            Mics.Clear();
            Mics.Add(SystemDefaultMic);
            foreach (var m in mics) Mics.Add(m);
            SelectSavedMic(_store.Current.Audio.InputDeviceIndex);

            var voices = await _api.ListTtsVoicesAsync();
            Fill(GeminiVoices, voices.Gemini);
            Fill(PiperVoices, voices.Piper);
            Fill(LocalVoices, voices.Local);
            Fill(EdgeVoices, voices.Edge);
            Fill(KokoroVoices, voices.Kokoro);
            Fill(GttsAccents, voices.Gtts);
            LoadFrom(_store.Current); // re-select saved voices now the lists exist
            Status = $"{mics.Count} mic(s), voices loaded";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"refresh devices failed: {ex.Message}");
        }
        finally { _loading = false; }
    }

    [RelayCommand]
    private async Task TestMicAsync()
    {
        if (SelectedMic is null) { Status = "pick a microphone first"; return; }
        MicTesting = true;
        MicLevel = MicPeak = 0;
        try
        {
            int? index = SelectedMic.Index < 0 ? null : SelectedMic.Index;
            var result = await _api.TestMicAsync(index);
            Status = result.Ok ? $"mic OK (peak {result.Peak:0})"
                               : $"very low signal (peak {result.Peak:0})  check the mic";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"mic test failed: {ex.Message}");
        }
        finally { MicTesting = false; }
    }

    partial void OnVoskSetupBusyChanged(bool value) => SetupVoskCommand.NotifyCanExecuteChanged();

    private bool CanSetupVosk() => !VoskSetupBusy;

    /// <summary>Downloads the selected Vosk model into ohbotData/vosk/ and points
    /// audio.vosk_model_path/stt_engine at it  no manual download/unzip/config-edit needed.
    /// Saves immediately if connected (like the mic picker); otherwise just sets the fields
    /// so a later Save applies them.</summary>
    [RelayCommand(CanExecute = nameof(CanSetupVosk))]
    private async Task SetupVoskAsync()
    {
        if (SelectedVoskModelOption is null) { VoskSetupStatus = "pick a model first"; return; }
        if (string.IsNullOrWhiteSpace(_repoRoot)) { VoskSetupStatus = "could not locate the repo root"; return; }

        var option = SelectedVoskModelOption;
        VoskSetupBusy = true;
        VoskSetupIndeterminate = true;
        VoskSetupPercent = 0;
        _voskCts = new CancellationTokenSource();
        var progress = new Progress<SetupProgress>(p =>
        {
            if (p.PercentComplete is { } pct) { VoskSetupPercent = pct; VoskSetupIndeterminate = false; }
            else { VoskSetupIndeterminate = true; }
            VoskSetupStatus = p.Message;
            _logs.Append(p.IsError ? "error" : "info", $"[vosk-setup:{p.Stage}] {p.Message}");
        });

        try
        {
            var modelDir = await _voskService.DownloadAndInstallAsync(option, _repoRoot, progress, _voskCts.Token)
                .ConfigureAwait(true);
            SttEngine = "vosk";
            VoskModelPath = modelDir;
            if (Connected)
            {
                await SaveAsync();
                VoskSetupStatus = $"{option.DisplayName} ready and saved";
            }
            else
            {
                VoskSetupStatus = $"{option.DisplayName} ready  connect and Save to apply";
            }
        }
        catch (OperationCanceledException)
        {
            VoskSetupStatus = "Vosk setup cancelled.";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"vosk model setup failed: {ex.Message}");
            VoskSetupStatus = $"setup failed: {ex.Message}";
        }
        finally
        {
            VoskSetupBusy = false;
            _voskCts = null;
        }
    }

    [RelayCommand]
    private void CancelVoskSetup() => _voskCts?.Cancel();

    [RelayCommand]
    private async Task TestVoiceAsync(string engine)
    {
        var voice = engine switch
        {
            "gemini" => GeminiVoice,
            "piper" => PiperVoice,
            "edge" => EdgeVoice,
            "kokoro" => KokoroVoice,
            "gtts" => GttsAccent,
            _ => LocalVoice,
        } ?? "";
        try
        {
            Status = $"synthesizing with {engine}…";
            var used = await _api.SpeakTestAsync(engine, voice, TestText);
            Status = $"played via {used}";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"voice test failed: {ex.Message}");
            Status = $"voice test failed: {ex.Message}";
        }
    }

    [RelayCommand]
    private async Task SaveAsync()
    {
        try
        {
            var cfg = _store.Current.Clone();
            ApplyTo(cfg);
            await _store.SaveAsync(cfg);
            Status = "saved to config.json";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"save failed: {ex.Message}");
            Status = $"save failed: {ex.Message}";
        }
    }

    /// <summary>Re-read the settings currently saved on the engine (discards page edits).</summary>
    [RelayCommand]
    private async Task ReloadAsync()
    {
        try
        {
            await _store.LoadAsync();       // fires Changed -> LoadFrom
            await RefreshDevicesAsync();
            Status = "reloaded from config.json";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"reload failed: {ex.Message}");
            Status = $"reload failed: {ex.Message}";
        }
    }

    public void HandleEvent(EngineEvent evt)
    {
        if (evt.Topic != Topics.MicLevel) return;
        var level = ObotJson.Deserialize<MicLevelEvent>(evt.Data);
        if (level is null) return;
        MicLevel = level.Level;
        MicPeak = level.Peak;
    }

    public void OnConnectionChanged(bool connected) => Connected = connected;

    private static void Fill(ObservableCollection<string> target, List<string> source)
    {
        target.Clear();
        foreach (var s in source) target.Add(s);
    }
}
