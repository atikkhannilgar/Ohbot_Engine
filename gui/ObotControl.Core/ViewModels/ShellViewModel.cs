using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObotControl.Core.Protocol;
using ObotControl.Core.Services;

namespace ObotControl.Core.ViewModels;

/// <summary>
/// The application root: owns the engine link (client + optional child process), the
/// shared config store and every page view-model, and fans connection-state and engine
/// events out to the pages. Both GUIs new this up once and bind their shell to it.
/// </summary>
public partial class ShellViewModel : ObservableObject
{
    private Action<Action> _post = a => a();
    private EngineProcess? _engine;

    public EngineClient Client { get; }
    public EngineApi Api { get; }
    public ConfigStore Store { get; }

    public LogsViewModel Logs { get; }
    public DashboardViewModel Dashboard { get; }
    public SetupViewModel Setup { get; }
    public ConfigurationViewModel Configuration { get; }
    public ManualControlViewModel ManualControl { get; }
    public MlControlViewModel MlControl { get; }

    public string[] LaunchControllers { get; } = { "virtual", "sim", "console" };

    [ObservableProperty] private string _host = "127.0.0.1";
    [ObservableProperty] private int _port = 8765;
    [ObservableProperty] private string _launchController = "virtual";

    [ObservableProperty] private ConnectionState _connectionState = ConnectionState.Disconnected;
    [ObservableProperty] private string _connectionText = "Disconnected";
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanLaunch))]
    private bool _isConnected;
    [ObservableProperty] private bool _engineOwned;
    [ObservableProperty] private string? _repoRoot;
    [ObservableProperty] private bool _showHelp;
    [ObservableProperty] private int _selectedTab;

    public bool CanLaunch => !IsConnected && Setup.Python.IsReady;

    public ShellViewModel()
    {
        Client = new EngineClient();
        Api = new EngineApi(Client);
        Store = new ConfigStore(Api);
        Logs = new LogsViewModel();
        var guiSettings = new GuiSettingsStore();
        Dashboard = new DashboardViewModel(Api, Logs, guiSettings);
        // One environment service, shared: the Setup page provisions the venv with it and
        // ML Control installs the optional ML extras into whatever the engine reports.
        var pythonService = new PythonEnvironmentService();
        var python = new PythonSetupViewModel(pythonService, guiSettings, Logs);
        Setup = new SetupViewModel(Api, Store, Logs, python, new VoskModelSetupService());
        Configuration = new ConfigurationViewModel(Api, Store, Logs);
        ManualControl = new ManualControlViewModel(Api, Logs);
        MlControl = new MlControlViewModel(Api, Store, Logs, pythonService);

        Client.StateChanged += (_, s) => HandleConnectionState(s);
        Client.EngineEventReceived += (_, e) => RouteEvent(e);
        Dashboard.PropertyChanged += (_, e) =>
        {
            // The dashboard owns session_start/session_stop; mirror its result so the
            // manual-control panel knows whether set_joint/release_joint will succeed,
            // and so ML Control knows a model preview has a controller to drive.
            if (e.PropertyName == nameof(DashboardViewModel.SessionActive))
            {
                ManualControl.NotifySessionActive(Dashboard.SessionActive);
                MlControl.NotifySessionActive(Dashboard.SessionActive);
            }
            // Mirrors get_state/session_start/session_stop's "emotion" field, so a fresh
            // session (or a reconnect to one already running) shows the real active pose.
            else if (e.PropertyName == nameof(DashboardViewModel.Emotion))
                ManualControl.SyncEmotion(Dashboard.Emotion);
        };
        Setup.Python.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName != nameof(PythonSetupViewModel.IsReady)) return;
            LaunchEngineCommand.NotifyCanExecuteChanged();
            // First run / nothing usable yet: land directly on the Setup tab instead of
            // leaving the user stuck on a Dashboard whose Launch button is disabled.
            if (!Setup.Python.IsReady && SelectedTab == 0) SelectedTab = 1;
        };

        RepoRoot = EngineProcess.LocateRepoRoot();
        if (RepoRoot is not null)
        {
            Logs.SetLogDirectory(Path.Combine(RepoRoot, "gui"));
            Setup.Python.Initialize(RepoRoot);
            Setup.SetRepoRoot(RepoRoot);
            MlControl.SetRepoRoot(RepoRoot);
        }
    }

    /// <summary>Wire the UI-thread marshaller; forwards to the client and to child-process output.</summary>
    public void UseDispatcher(Action<Action> post)
    {
        _post = post;
        Client.UseDispatcher(post);
    }

    /// <summary>
    /// Apply CLI / launcher overrides (e.g. <c>--host</c>, <c>--port</c>, <c>--attach</c>).
    /// Used by Docker's <c>docker/start.sh</c> so the GUI opens already talking to the
    /// containerized engine.
    /// </summary>
    public void ApplyStartupOptions(string? host = null, int? port = null, bool autoAttach = false)
    {
        if (!string.IsNullOrWhiteSpace(host)) Host = host.Trim();
        if (port is > 0) Port = port.Value;
        if (autoAttach) Attach();
    }

    // -- connect / launch --------------------------------------------------------------

    [RelayCommand]
    private void Attach()
    {
        Logs.Append("info", $"attaching to ws://{Host}:{Port}");
        Client.Connect(new Uri($"ws://{Host}:{Port}"));
    }

    [RelayCommand(CanExecute = nameof(CanLaunch))]
    private void LaunchEngine()
    {
        if (RepoRoot is null)
        {
            Logs.Append("error", "could not locate the engine repo (src/obot/__main__.py).");
            return;
        }
        StopEngineProcess();
        var options = new EngineLaunchOptions
        {
            RepoRoot = RepoRoot,
            PythonPath = EngineProcess.VenvPython(RepoRoot) ?? "",
            Host = Host,
            Port = Port,
            Controller = LaunchController == "virtual" ? "" : LaunchController,
        };
        var engine = new EngineProcess(options);
        engine.OutputReceived += (_, line) => _post(() => Logs.AppendRaw(line));
        engine.Exited += (_, code) => _post(() =>
        {
            EngineOwned = false;
            // A nonzero exit here usually just means some other engine (e.g. one left
            // running from an earlier session) already owns this port  the connect
            // retry above will attach to that one instead, so this isn't a real failure.
            if (engine.ObservedAddressInUse)
            {
                Logs.Append("warn",
                    $"an engine is already running on {Host}:{Port}  attaching to it instead of the one just launched.");
            }
            else
            {
                Logs.Append("warn", $"engine exited ({code})");
            }
        });
        try
        {
            engine.Start();
            _engine = engine;
            EngineOwned = true;
            Logs.Append("info", $"launched engine ({LaunchController}); connecting…");
            // Auto-reconnect keeps retrying until the server's socket is up.
            Client.Connect(new Uri($"ws://{Host}:{Port}"));
        }
        catch (Exception ex)
        {
            Logs.Append("error", $"failed to launch engine: {ex.Message}");
            engine.Dispose();
        }
    }

    [RelayCommand]
    private async Task DisconnectAsync()
    {
        await Client.DisconnectAsync();
        StopEngineProcess();
    }

    [RelayCommand]
    private void ToggleHelp() => ShowHelp = !ShowHelp;

    [RelayCommand]
    private void CloseHelp() => ShowHelp = false;

    /// <summary>Re-fetch config + devices from the engine (discards unsaved page edits).</summary>
    [RelayCommand]
    private async Task ReloadAsync()
    {
        if (!IsConnected) return;
        await OnConnectedAsync();
    }

    private void StopEngineProcess()
    {
        _engine?.Dispose();
        _engine = null;
        EngineOwned = false;
    }

    // -- state & events ----------------------------------------------------------------

    private void HandleConnectionState(ConnectionState state)
    {
        ConnectionState = state;
        IsConnected = state == ConnectionState.Connected;
        ConnectionText = state switch
        {
            ConnectionState.Connected => $"Connected · {Host}:{Port}",
            ConnectionState.Connecting => "Connecting…",
            ConnectionState.Reconnecting => "Reconnecting…",
            ConnectionState.Faulted => "Connection error",
            _ => "Disconnected",
        };
        LaunchEngineCommand.NotifyCanExecuteChanged();

        Dashboard.OnConnectionChanged(IsConnected);
        Setup.OnConnectionChanged(IsConnected);
        Configuration.OnConnectionChanged(IsConnected);
        ManualControl.OnConnectionChanged(IsConnected);
        // The ML page installs dependencies with a local pip, so it needs to know whether
        // the engine it is talking to is even on this machine.
        MlControl.SetEngineHost(Host);
        MlControl.OnConnectionChanged(IsConnected);

        if (IsConnected)
        {
            _ = OnConnectedAsync();
        }
    }

    private async Task OnConnectedAsync()
    {
        try
        {
            await Store.LoadAsync();
            await Setup.RefreshDevicesCommand.ExecuteAsync(null);
            // Restores the remembered model selection into the (now-populated) list 
            // the picker itself was already restored from GuiSettings in the constructor.
            if (Dashboard.RequiresModel) await Dashboard.RefreshModelsCommand.ExecuteAsync(null);
            var state = await Api.GetStateAsync();
            Dashboard.ApplyState(state);
            Logs.Append("info", "connected; config + devices loaded");
        }
        catch (Exception ex)
        {
            Logs.Append("error", $"initial load failed: {ex.Message}");
        }
    }

    private void RouteEvent(EngineEvent evt)
    {
        switch (evt.Topic)
        {
            case Topics.Log:
                var log = ObotJson.Deserialize<LogEvent>(evt.Data);
                if (log is not null) Logs.Append(log.Level, log.Message);
                break;
            case Topics.Error:
                var err = ObotJson.Deserialize<ErrorEvent>(evt.Data);
                if (err is not null) Logs.Append("error", $"{err.Where}: {err.Message}");
                break;
            case Topics.MicLevel:
                Setup.HandleEvent(evt);
                break;
            case Topics.Joints:
            case Topics.Emotion:
                Dashboard.HandleEvent(evt);
                ManualControl.HandleEvent(evt);
                break;
            default:
                Dashboard.HandleEvent(evt);
                break;
        }
    }
}
