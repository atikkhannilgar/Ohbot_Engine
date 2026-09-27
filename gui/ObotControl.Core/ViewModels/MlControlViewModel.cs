using System.Collections.ObjectModel;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Models;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

/// <summary>One checkpoint in the model library, as the page lists it.</summary>
public partial class MlModelViewModel : ObservableObject
{
    public MlModelViewModel(MlModelInfo info)
    {
        Info = info;
        _name = info.Name;
        _notes = info.Notes;
        _isSelected = info.Selected;
    }

    public MlModelInfo Info { get; }

    public string Path => Info.Path;
    public string AbsPath => Info.AbsPath;
    public bool Exists => Info.Exists;

    /// <summary>"registry" (named in config.json), "discovered" (found by the scan) or
    /// "configured" (in use but neither of the above).</summary>
    public string Source => Info.Source;

    /// <summary>True for entries stored in config.json  only those can be renamed/removed.</summary>
    public bool IsRegistered => Info.Source == "registry";

    /// <summary>Editable so a discovered checkpoint can be given a name as it is registered.</summary>
    [ObservableProperty] private string _name;
    [ObservableProperty] private string _notes;

    /// <summary>True for the checkpoint that will drive speech once the page is saved.</summary>
    [ObservableProperty] private bool _isSelected;

    public string SizeText => Info.Exists ? FormatSize(Info.SizeBytes) : "missing";

    public string ModifiedText =>
        DateTimeOffset.TryParse(Info.Modified, out var when)
            ? when.ToLocalTime().ToString("yyyy-MM-dd HH:mm")
            : "";

    /// <summary>One line under the name: where it came from, how big, when it was written.</summary>
    public string Subtitle
    {
        get
        {
            var parts = new List<string> { Path };
            if (!Info.Exists) parts.Add("file missing");
            else
            {
                parts.Add(SizeText);
                if (ModifiedText.Length > 0) parts.Add(ModifiedText);
            }
            return string.Join("  ·  ", parts);
        }
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1024L * 1024 * 1024 => $"{bytes / (1024.0 * 1024 * 1024):0.0} GB",
        >= 1024L * 1024 => $"{bytes / (1024.0 * 1024):0.0} MB",
        >= 1024 => $"{bytes / 1024.0:0} KB",
        _ => $"{bytes} B",
    };
}

/// <summary>
/// ML Control: pick and manage the audio-driven gesture model (the BEAT2-trained
/// checkpoint that moves head/eyes/lids/lips straight from the speech waveform).
///
/// Three things happen on this page. The <b>library</b> lists every checkpoint the engine
/// can see  the named entries in config.json plus everything found under
/// <c>mlBehaviour/runs</c> and <c>src/obot/ml/models</c>  and lets one be selected,
/// named/registered, inspected (axes, hyperparameters, training progress) or dropped.
/// <b>Inference settings</b> are the knobs the speech engine reads: device, control rate,
/// intensity, and whether the lips stay on the scripted mouth track. And <b>preview</b>
/// plays a wav through the selected checkpoint, or replays a recorded training clip as
/// ground truth, on the live robot so a model can be judged before a conversation.
///
/// Intensity and control rate are read per sentence, so they apply live (debounced, like
/// the Configuration page's mouth sliders). Enabling the feature, changing checkpoint or
/// switching device rebuild the model object, which is what Save + <c>ml_reload_model</c>
/// does to a running session  no session restart needed.
/// </summary>
public partial class MlControlViewModel : ObservableObject
{
    private static readonly TimeSpan LiveApplyDebounce = TimeSpan.FromMilliseconds(250);

    /// <summary>Properties backed by config.json: editing one is what makes the page dirty.
    /// Everything else here is view state (selection, busy flags, status text).</summary>
    private static readonly HashSet<string> ConfigProps = new()
    {
        nameof(Enabled), nameof(CheckpointPath), nameof(Device), nameof(ControlHz),
        nameof(Intensity), nameof(ScriptedMouth), nameof(PreviewWav), nameof(ClipManifest),
    };

    /// <summary>The subset the engine re-reads per sentence, so editing them applies live.</summary>
    private static readonly HashSet<string> LiveProps = new()
    {
        nameof(Intensity), nameof(ControlHz),
    };

    private readonly EngineApi _api;
    private readonly ConfigStore _store;
    private readonly LogsViewModel _logs;
    private readonly PythonEnvironmentService _python;
    private bool _loading;
    private CancellationTokenSource? _liveApplyCts;
    private CancellationTokenSource? _installCts;
    private string _repoRoot = "";
    private string _engineHost = "127.0.0.1";

    public MlControlViewModel(
        EngineApi api, ConfigStore store, LogsViewModel logs, PythonEnvironmentService python)
    {
        _api = api;
        _store = store;
        _logs = logs;
        _python = python;
        _store.Changed += (_, _) => LoadFrom(_store.Current);
        PropertyChanged += OnAnyPropertyChanged;
    }

    /// <summary>Repo root of the checkout, needed to resolve requirements/ml.txt for the
    /// installer. Set once by the shell (mirrors SetupViewModel.SetRepoRoot).</summary>
    public void SetRepoRoot(string repoRoot) => _repoRoot = repoRoot;

    /// <summary>Which host the engine is on. Installing dependencies only works when that is
    /// this machine  the GUI runs pip locally, it cannot reach into a remote engine's venv.</summary>
    public void SetEngineHost(string host)
    {
        _engineHost = host ?? "";
        OnPropertyChanged(nameof(CanInstallRequirements));
        OnPropertyChanged(nameof(EngineIsRemote));
    }

    /// <summary>True when the engine is on another machine, so a local pip install would put
    /// the packages in the wrong place. The card says so instead of offering a broken button.</summary>
    public bool EngineIsRemote => !EngineIsLocal;

    private bool EngineIsLocal =>
        _engineHost is "127.0.0.1" or "localhost" or "::1" or "0.0.0.0" or "";

    /// <summary>torch device strings accepted by the engine's inference path.</summary>
    public string[] Devices { get; } = { "cpu", "cuda" };

    public ObservableCollection<MlModelViewModel> Models { get; } = new();
    public ObservableCollection<MlClipInfo> Clips { get; } = new();

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanPreview))]
    [NotifyPropertyChangedFor(nameof(CanInstallRequirements))]
    private bool _connected;
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanPreview))]
    private bool _sessionActive;
    [ObservableProperty] private bool _isDirty;
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private bool _busy;

    // -- gesture settings (config.json speech.gesture) ------------------------------------

    [ObservableProperty] private bool _enabled;
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasCheckpoint))]
    [NotifyPropertyChangedFor(nameof(CanPreview))]
    private string _checkpointPath = "";
    [ObservableProperty] private string _device = "cpu";
    [ObservableProperty] private double _controlHz = 20.0;
    [ObservableProperty] private double _intensity = 1.0;
    [ObservableProperty] private bool _scriptedMouth;

    public bool HasCheckpoint => !string.IsNullOrWhiteSpace(CheckpointPath);

    // -- library / preview inputs ----------------------------------------------------------

    [ObservableProperty] private MlModelViewModel? _selectedModel;

    /// <summary>Path typed (or pasted, or picked with the file dialog) into "Add a model".</summary>
    [ObservableProperty] private string _newModelPath = "";
    [ObservableProperty] private string _newModelName = "";

    [ObservableProperty] private string _previewWav = "";
    [ObservableProperty] private MlClipInfo? _selectedClip;
    [ObservableProperty] private string _clipManifest = "";
    [ObservableProperty] private double _replaySpeed = 1.0;
    [ObservableProperty] private bool _replayAudio = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanPreview))]
    private bool _previewing;
    [ObservableProperty] private string _previewStatus = "";

    /// <summary>Preview needs a live session: it drives that session's controller.</summary>
    public bool CanPreview => Connected && SessionActive && !Previewing && HasCheckpoint;

    // -- runtime / inspection ---------------------------------------------------------------

    [ObservableProperty] private string _runtimeText = "torch: unknown";
    [ObservableProperty] private string _loadedText = "no session";

    /// <summary>True when the running session holds a different checkpoint than the one
    /// configured  i.e. Save-then-Apply is still pending.</summary>
    [ObservableProperty] private bool _reloadPending;

    // -- ML dependencies (requirements/ml.txt on the engine host) -------------------------

    public ObservableCollection<MlRequirementItem> Requirements { get; } = new();

    /// <summary>False while anything the gesture model needs is missing on the engine host.
    /// Drives the install card at the top of the page.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowRequirements))]
    private bool _requirementsReady = true;

    [ObservableProperty] private string _requirementsSummary = "";
    [ObservableProperty] private string _requirementsFile = "requirements/ml.txt";

    /// <summary>The engine's own interpreter, which is what gets pip-installed into.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanInstallRequirements))]
    private string _enginePython = "";

    [ObservableProperty] private string _enginePythonVersion = "";

    /// <summary>True when some missing item is a pip-installable module (as opposed to a
    /// missing mlBehaviour/ file, which an install cannot fix).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanInstallRequirements))]
    private bool _requirementsInstallable;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanInstallRequirements))]
    [NotifyPropertyChangedFor(nameof(ShowRequirements))]
    private bool _installing;

    [ObservableProperty] private string _installStatus = "";
    [ObservableProperty] private double _installPercent;
    [ObservableProperty] private bool _installIndeterminate = true;

    /// <summary>Keep the card up after a failed install so the reason stays on screen even
    /// once the missing-items list changes.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowRequirements))]
    private bool _installFailed;

    /// <summary>The card is only in the way once everything is present.</summary>
    public bool ShowRequirements => !RequirementsReady || Installing || InstallFailed;

    public bool CanInstallRequirements =>
        Connected && !Installing && RequirementsInstallable && EngineIsLocal
        && !string.IsNullOrWhiteSpace(EnginePython);

    [ObservableProperty] private string _inspectionTitle = "";
    [ObservableProperty] private string _inspectionDetails = "";
    [ObservableProperty] private bool _hasInspection;

    // -- config <-> fields --------------------------------------------------------------------

    public void LoadFrom(ObotConfig cfg)
    {
        _loading = true;
        try
        {
            var gesture = cfg.Speech.Gesture;
            Enabled = gesture.Enabled;
            CheckpointPath = gesture.CheckpointPath;
            Device = string.IsNullOrEmpty(gesture.Device) ? "cpu" : gesture.Device;
            ControlHz = gesture.ControlHz;
            Intensity = gesture.Intensity;
            ScriptedMouth = gesture.ScriptedMouth;

            PreviewWav = cfg.Ml.PreviewWav;
            ClipManifest = cfg.Ml.DatasetManifest;
            SyncSelection();
            IsDirty = false;
        }
        finally { _loading = false; }
    }

    private ObotConfig BuildConfig()
    {
        var cfg = _store.Current.Clone();
        var gesture = cfg.Speech.Gesture;
        gesture.Enabled = Enabled;
        gesture.CheckpointPath = CheckpointPath;
        gesture.Device = Device;
        gesture.ControlHz = ControlHz;
        gesture.Intensity = Intensity;
        gesture.ScriptedMouth = ScriptedMouth;

        cfg.Ml.PreviewWav = PreviewWav;
        cfg.Ml.DatasetManifest = ClipManifest;
        // Registered entries are rewritten from the list, so renames and notes typed in
        // the library persist; discovered checkpoints stay out of config.json until the
        // user registers them explicitly.
        cfg.Ml.Models = Models
            .Where(m => m.IsRegistered)
            .Select(m => new MlModelEntry { Name = m.Name, Path = m.Path, Notes = m.Notes })
            .ToList();
        return cfg;
    }

    private void OnAnyPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (_loading || e.PropertyName is null) return;
        if (!ConfigProps.Contains(e.PropertyName)) return;

        IsDirty = true;
        if (LiveProps.Contains(e.PropertyName)) ScheduleLiveApply();
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
            // No ConfigureAwait(false): the store's Changed handlers repopulate UI-bound
            // properties, so this has to resume on the UI thread (same in every command).
            await _store.SaveAsync(BuildConfig());
            Status = "intensity / control rate applied live";
        }
        catch (OperationCanceledException) { /* superseded by a newer edit */ }
        catch (Exception ex) { _logs.Append("error", $"live apply failed: {ex.Message}"); }
    }

    // -- library ----------------------------------------------------------------------------

    /// <summary>Re-scan the engine host for checkpoints and refresh the runtime badge.</summary>
    [RelayCommand]
    private async Task RefreshAsync()
    {
        if (!Connected) return;
        Busy = true;
        try
        {
            var list = await _api.ListMlModelsAsync();
            Models.Clear();
            foreach (var info in list.Models) Models.Add(Track(new MlModelViewModel(info)));
            SyncSelection();
            await RefreshStatusAsync(probe: false);
            Status = $"{Models.Count} checkpoint(s) found in {string.Join(", ", list.ScanDirs)}";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"list_ml_models failed: {ex.Message}");
            Status = $"scan failed: {ex.Message}";
        }
        finally { Busy = false; }
    }

    /// <summary>Make this checkpoint the one that drives speech (applied on Save).</summary>
    [RelayCommand]
    private void UseModel(MlModelViewModel? model)
    {
        if (model is null) return;
        CheckpointPath = model.Path;
        SelectedModel = model;
        SyncSelection();
        Status = model.Exists
            ? $"selected {model.Name}  Save to apply"
            : $"selected {model.Name}, but the file is missing on the engine host";
    }

    /// <summary>Give a discovered checkpoint a name and store it in config.json, so it
    /// survives a rescan and can be documented with a note.</summary>
    [RelayCommand]
    private void RegisterModel(MlModelViewModel? model)
    {
        if (model is null || model.IsRegistered) return;
        var entry = new MlModelInfo
        {
            Name = model.Name,
            Path = model.Path,
            AbsPath = model.AbsPath,
            Notes = model.Notes,
            Source = "registry",
            Exists = model.Exists,
            SizeBytes = model.Info.SizeBytes,
            Modified = model.Info.Modified,
            Selected = model.IsSelected,
        };
        var index = Models.IndexOf(model);
        Models[index] = Track(new MlModelViewModel(entry));
        SelectedModel = Models[index];
        IsDirty = true;
        Status = $"{entry.Name} registered  Save to keep it";
    }

    /// <summary>Add a checkpoint by path (typed, pasted or picked from a file dialog).</summary>
    [RelayCommand]
    private void AddModel()
    {
        var path = (NewModelPath ?? "").Trim().Trim('"');
        if (path.Length == 0)
        {
            Status = "enter a checkpoint path (a train.py .pt file) first";
            return;
        }

        var existing = Models.FirstOrDefault(m =>
            string.Equals(m.Path, path, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(m.AbsPath, path, StringComparison.OrdinalIgnoreCase));
        if (existing is not null)
        {
            SelectedModel = existing;
            Status = $"{existing.Name} is already in the library";
            return;
        }

        var name = (NewModelName ?? "").Trim();
        if (name.Length == 0) name = System.IO.Path.GetFileNameWithoutExtension(path);
        // Exists/size stay unknown until the next Refresh: only the engine host can say,
        // and it may not even be this machine.
        var model = Track(new MlModelViewModel(new MlModelInfo
        {
            Name = name, Path = path, AbsPath = path, Source = "registry", Exists = true,
        }));
        Models.Insert(0, model);
        SelectedModel = model;
        NewModelPath = "";
        NewModelName = "";
        IsDirty = true;
        Status = $"{name} added  Save, then Refresh to confirm the engine can see it";
    }

    /// <summary>Drop a registered entry from config.json. The checkpoint file is untouched,
    /// and a discovered one simply reappears on the next scan.</summary>
    [RelayCommand]
    private void RemoveModel(MlModelViewModel? model)
    {
        if (model is null || !model.IsRegistered) return;
        Models.Remove(model);
        if (ReferenceEquals(SelectedModel, model)) SelectedModel = null;
        IsDirty = true;
        Status = $"{model.Name} removed from the library  Save to keep that";
    }

    /// <summary>Open a checkpoint on the engine host and show what it contains.</summary>
    [RelayCommand]
    private async Task InspectAsync(MlModelViewModel? model)
    {
        var path = model?.Path ?? CheckpointPath;
        if (!Connected || string.IsNullOrWhiteSpace(path)) return;
        Busy = true;
        Status = "reading checkpoint…";
        try
        {
            var info = await _api.InspectMlModelAsync(path);
            InspectionTitle = $"{info.RunName}  ·  {info.Path}";
            InspectionDetails = FormatInspection(info);
            HasInspection = true;
            Status = "checkpoint read";
        }
        catch (Exception ex)
        {
            InspectionTitle = path;
            InspectionDetails = ex.Message;
            HasInspection = true;
            _logs.Append("error", $"inspect_ml_model failed: {ex.Message}");
            Status = "could not read that checkpoint";
        }
        finally { Busy = false; }
    }

    private string FormatInspection(MlCheckpointInfo info)
    {
        var lines = new List<string>
        {
            $"Output axes    {info.NAxes}" +
                (info.AxisNames.Count > 0 ? $"  ({string.Join(", ", info.AxisNames)})" : ""),
            $"Mel bands      {info.NMels}   ·   conv {info.ConvChannels}   ·   GRU {info.GruHidden}",
            $"Parameters     {info.Parameters:N0}",
        };
        if (info.Epoch is not null)
        {
            lines.Add(info.EpochsPlanned is not null
                ? $"Trained        epoch {info.Epoch} of {info.EpochsPlanned}"
                : $"Trained        epoch {info.Epoch}");
        }
        if (info.BestVal is not null) lines.Add($"Best val loss  {info.BestVal:0.0000}");
        if (info.LearningRate is not null || info.BatchSize is not null)
        {
            lines.Add($"Hyperparams    lr {info.LearningRate?.ToString("0.#####") ?? "?"}" +
                      $"   ·   batch {info.BatchSize?.ToString() ?? "?"}");
        }
        if (info.DataDir.Length > 0) lines.Add($"Trained on     {info.DataDir}");
        lines.Add(info.HasOptimizerState
            ? "Kind           checkpoint.pt (carries optimizer state, resumable)"
            : "Kind           best_model.pt (weights only)");

        // The control rate has to match what the data was converted with, and the axis
        // count tells you whether head tilt is driven at all -- worth spelling out.
        if (info.NAxes is > 0 and < 8)
        {
            lines.Add("");
            lines.Add($"Note: {info.NAxes} axes -- this model does not drive every joint " +
                      "(head tilt is excluded when the data was converted with --exclude-head-tilt).");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>Add a library row, watching it so renaming a model (or typing a note) marks
    /// the page dirty  BuildConfig reads those straight off the rows.</summary>
    private MlModelViewModel Track(MlModelViewModel model)
    {
        model.PropertyChanged += (_, e) =>
        {
            if (_loading) return;
            if (e.PropertyName is nameof(MlModelViewModel.Name) or nameof(MlModelViewModel.Notes))
            {
                IsDirty = true;
            }
        };
        return model;
    }

    private void SyncSelection()
    {
        foreach (var model in Models)
        {
            model.IsSelected = string.Equals(model.Path, CheckpointPath, StringComparison.OrdinalIgnoreCase);
        }
        SelectedModel ??= Models.FirstOrDefault(m => m.IsSelected);
    }

    // -- runtime ------------------------------------------------------------------------------

    /// <summary>Import torch on the engine host and report whether CUDA is usable.</summary>
    [RelayCommand]
    private async Task CheckRuntimeAsync()
    {
        Status = "probing the inference runtime…";
        await RefreshStatusAsync(probe: true);
    }

    private async Task RefreshStatusAsync(bool probe)
    {
        if (!Connected) return;
        try
        {
            var status = await _api.GetMlStatusAsync(probe);
            ApplyStatus(status);
            if (probe)
            {
                Status = status.TorchAvailable
                    ? $"torch {status.TorchVersion ?? "?"}; CUDA " +
                      (status.CudaAvailable == true ? "available" : "not available")
                    : "torch is not installed on the engine host";
            }
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"ml_status failed: {ex.Message}");
        }
    }

    private void ApplyStatus(MlStatus status)
    {
        ApplyRequirements(status.Requirements);
        RuntimeText = status.TorchAvailable
            ? $"torch {status.TorchVersion ?? "installed"}  ·  CUDA " + status.CudaAvailable switch
            {
                true => status.CudaDevices.Count > 0 ? string.Join(", ", status.CudaDevices) : "available",
                false => "not available",
                _ => "not checked",
            }
            : "torch not installed  ·  see the ML dependencies card above";

        if (!status.Session)
        {
            LoadedText = "no session  ·  the model loads when a session starts";
            ReloadPending = false;
        }
        else if (!status.GestureLoaded)
        {
            LoadedText = status.Enabled
                ? "session running, no model loaded  ·  scripted mouth track in use"
                : "session running, gesture model disabled";
            ReloadPending = status.Enabled && status.CheckpointExists;
        }
        else
        {
            LoadedText = $"loaded in the session: {status.LoadedCheckpoint}";
            ReloadPending = !string.Equals(
                status.LoadedCheckpoint, status.CheckpointPath, StringComparison.OrdinalIgnoreCase);
        }
        // Only overwrite the preview line while something is actually playing, so the
        // result of the last preview stays readable after it has finished.
        if (status.PreviewActive) PreviewStatus = $"playing {status.PreviewPlaying}";
    }

    private void ApplyRequirements(MlRequirements req)
    {
        Requirements.Clear();
        foreach (var item in req.Items) Requirements.Add(item);

        RequirementsReady = req.Ready;
        RequirementsFile = req.RequirementsFile;
        RequirementsInstallable = req.Installable.Count > 0 && req.RequirementsExists;
        EnginePython = req.Python;
        EnginePythonVersion = req.PythonVersion;

        if (req.Ready)
        {
            RequirementsSummary = "All ML dependencies are present on the engine host.";
            return;
        }

        var missing = string.Join(", ", req.Missing);
        RequirementsSummary = req.Installable.Count == req.Missing.Count
            ? $"Missing on the engine host: {missing}. " +
              $"Install {req.RequirementsFile} to fix it  a large download (torch is a few hundred MB)."
            : $"Missing on the engine host: {missing}. Items outside {req.RequirementsFile} " +
              "(the mlBehaviour/ training pipeline) are part of the checkout and cannot be pip-installed  " +
              "restore them from git.";
    }

    /// <summary>Install requirements/ml.txt into the interpreter the engine itself runs on,
    /// streaming pip's output to the Logs tab. torch is imported lazily, so a running engine
    /// picks the new packages up without a restart.</summary>
    [RelayCommand]
    private async Task InstallRequirementsAsync()
    {
        if (!CanInstallRequirements) return;
        if (string.IsNullOrWhiteSpace(_repoRoot))
        {
            InstallStatus = "could not locate the repo checkout, so requirements/ml.txt can't be found.";
            InstallFailed = true;
            return;
        }

        Installing = true;
        InstallFailed = false;
        InstallPercent = 0;
        InstallIndeterminate = true;
        InstallStatus = "starting pip…";
        _installCts = new CancellationTokenSource();

        var progress = new Progress<SetupProgress>(p =>
        {
            if (p.PercentComplete is { } pct) { InstallPercent = pct; InstallIndeterminate = false; }
            else { InstallIndeterminate = true; }
            InstallStatus = p.Message;
            _logs.Append(p.IsError ? "error" : "info", $"[ml-setup:{p.Stage}] {p.Message}");
        });

        try
        {
            // No ConfigureAwait(false): the continuation touches UI-bound state.
            var result = await _python.InstallRequirementsAsync(
                EnginePython, _repoRoot, RequirementsFile, progress, _installCts.Token);
            InstallStatus = result.Message;
            InstallFailed = !result.Ok;
            Status = result.Message;
            // Re-poll either way: a partial install still changes what is present, and the
            // engine invalidates its import caches so a fresh torch is seen without a restart.
            await RefreshStatusAsync(probe: result.Ok);
        }
        catch (OperationCanceledException)
        {
            InstallStatus = "install cancelled.";
            InstallFailed = true;
        }
        catch (Exception ex)
        {
            InstallStatus = $"install failed: {ex.Message}";
            InstallFailed = true;
            _logs.Append("error", $"ml requirements install failed: {ex.Message}");
        }
        finally
        {
            Installing = false;
            _installCts = null;
        }
    }

    [RelayCommand]
    private void CancelInstall() => _installCts?.Cancel();

    /// <summary>Save the page, then load the selected checkpoint into the running session
    /// so a model swap takes effect without restarting the conversation.</summary>
    [RelayCommand]
    private async Task SaveAsync()
    {
        if (!Connected) return;
        Busy = true;
        try
        {
            await _store.SaveAsync(BuildConfig());
            IsDirty = false;
            Status = "saved";
            if (SessionActive) await ApplyToSessionAsync(force: false);
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"save failed: {ex.Message}");
            Status = $"save failed: {ex.Message}";
        }
        finally { Busy = false; }
    }

    /// <summary>Reload the checkpoint into the running session even if nothing changed
    /// what you want after re-training into the same path.</summary>
    [RelayCommand]
    private async Task ReloadModelAsync()
    {
        if (!Connected || !SessionActive) return;
        Busy = true;
        try
        {
            await ApplyToSessionAsync(force: true);
        }
        finally { Busy = false; }
    }

    private async Task ApplyToSessionAsync(bool force)
    {
        try
        {
            Status = "loading the model into the running session…";
            var status = await _api.ReloadMlModelAsync(force);
            ApplyStatus(status);
            Status = status.GestureLoaded
                ? $"model loaded into the session: {status.LoadedCheckpoint}"
                : "no model loaded; the session is using the scripted mouth track";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"ml_reload_model failed: {ex.Message}");
            Status = $"could not load the model: {ex.Message}";
        }
    }

    /// <summary>Drop every edit on the page. The library list is rebuilt from the engine
    /// rather than from the fields, so an added or removed model is undone too.</summary>
    [RelayCommand]
    private async Task RevertAsync()
    {
        LoadFrom(_store.Current);
        if (Connected) await RefreshAsync();
        IsDirty = false;
        Status = "reverted";
    }

    // -- preview / replay ----------------------------------------------------------------------

    /// <summary>Play the preview clip through the selected checkpoint on the live robot.</summary>
    [RelayCommand]
    private async Task PreviewAsync()
    {
        if (!CanPreview) return;
        var wav = (PreviewWav ?? "").Trim();
        if (wav.Length == 0)
        {
            Status = "set an audio file to preview with first";
            return;
        }

        Previewing = true;
        PreviewStatus = "loading the model…";
        try
        {
            var result = await _api.MlPreviewAsync(CheckpointPath, wav, ControlHz, Intensity, Device);
            PreviewStatus = DescribeResult(result, $"model on {result.Wav}");
            if (!result.PoseCapable)
            {
                PreviewStatus += "  (console session: audio only, no servos)";
            }
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"ml_preview failed: {ex.Message}");
            PreviewStatus = $"preview failed: {ex.Message}";
        }
        finally
        {
            Previewing = false;
        }
    }

    /// <summary>Fetch the clips of a converted BEAT2 dataset, if one exists on the host.</summary>
    [RelayCommand]
    private async Task RefreshClipsAsync()
    {
        if (!Connected) return;
        Busy = true;
        try
        {
            var manifest = string.IsNullOrWhiteSpace(ClipManifest) ? null : ClipManifest.Trim();
            var list = await _api.ListMlClipsAsync(manifest);
            Clips.Clear();
            foreach (var clip in list.Clips) Clips.Add(clip);
            SelectedClip = Clips.FirstOrDefault();
            Status = list.Exists
                ? $"{Clips.Count} clip(s) in {list.Manifest}"
                : $"no dataset at {list.Manifest}  run beat2_to_ohbot.py convert to build one";
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"list_ml_clips failed: {ex.Message}");
            Status = $"clip list failed: {ex.Message}";
        }
        finally { Busy = false; }
    }

    /// <summary>Replay the selected training clip as recorded  ground truth to compare a
    /// model preview against.</summary>
    [RelayCommand]
    private async Task ReplayClipAsync()
    {
        if (!Connected || !SessionActive || Previewing) return;
        var clip = SelectedClip;
        if (clip is null)
        {
            Status = "pick a clip first (Refresh clips)";
            return;
        }

        Previewing = true;
        PreviewStatus = $"replaying {clip.ClipId}…";
        try
        {
            var result = await _api.MlReplayClipAsync(clip.Path, ReplaySpeed, ReplayAudio);
            PreviewStatus = DescribeResult(result, $"ground truth {clip.ClipId}");
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"ml_replay_clip failed: {ex.Message}");
            PreviewStatus = $"replay failed: {ex.Message}";
        }
        finally
        {
            Previewing = false;
        }
    }

    private static string DescribeResult(MlPreviewResult result, string what)
    {
        var verb = result.Stopped ? "stopped" : "finished";
        var frames = result.Frames is > 0 ? $", {result.Frames} frames" : "";
        return $"{verb}: {what} ({result.ElapsedS:0.0}s{frames})";
    }

    [RelayCommand]
    private async Task StopPreviewAsync()
    {
        if (!Connected) return;
        try
        {
            await _api.StopMlPreviewAsync();
        }
        catch (Exception ex)
        {
            _logs.Append("error", $"ml_preview_stop failed: {ex.Message}");
        }
    }

    // -- connection / session ------------------------------------------------------------------

    public void OnConnectionChanged(bool connected)
    {
        Connected = connected;
        if (connected)
        {
            _ = RefreshAsync();
        }
        else
        {
            SessionActive = false;
            Previewing = false;
            LoadedText = "not connected";
            RuntimeText = "torch: unknown";
        }
    }

    /// <summary>Called by the shell when the dashboard's session state changes: preview and
    /// model reload both need a running session to drive.</summary>
    public void NotifySessionActive(bool active)
    {
        SessionActive = active;
        if (!active)
        {
            Previewing = false;
            LoadedText = "no session  ·  the model loads when a session starts";
            ReloadPending = false;
        }
        else if (Connected)
        {
            _ = RefreshStatusAsync(probe: false);
        }
    }
}
