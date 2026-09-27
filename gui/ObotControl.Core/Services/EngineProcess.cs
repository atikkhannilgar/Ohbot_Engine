using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;

namespace ObotControl.Core.Services;

/// <summary>How to launch the engine: where the repo is, which Python, and the controller.</summary>
public sealed class EngineLaunchOptions
{
    public string RepoRoot { get; set; } = "";
    public string PythonPath { get; set; } = "";
    public string Host { get; set; } = "127.0.0.1";
    public int Port { get; set; } = 8765;

    /// <summary>Default controller: "" (virtual), "sim" (--sim) or "console" (--console).</summary>
    public string Controller { get; set; } = "";
}

/// <summary>
/// Spawns and owns a <c>python -m obot --serve</c> child process, streams its stdout/stderr
/// to the log pane, and guarantees the whole process tree is killed when the GUI exits
/// (the engine must run from the repo root  ohbot lib + ohbotData/ are CWD-relative).
/// </summary>
public sealed class EngineProcess : IDisposable
{
    private readonly EngineLaunchOptions _options;
    private Process? _process;

    public EngineProcess(EngineLaunchOptions options) => _options = options;

    public event EventHandler<string>? OutputReceived;
    public event EventHandler<int>? Exited;

    public bool IsRunning => _process is { HasExited: false };
    public Uri Endpoint => new($"ws://{_options.Host}:{_options.Port}");

    /// <summary>True if stdout/stderr contained a "port already in use" bind failure 
    /// i.e. some other engine (stray or otherwise) is already listening on this address,
    /// so a nonzero exit here doesn't mean the engine itself is broken.</summary>
    public bool ObservedAddressInUse { get; private set; }

    private static readonly string[] AddressInUseMarkers =
        { "WinError 10048", "address already in use", "[Errno 98]", "[Errno 48]" };

    public void Start()
    {
        if (IsRunning) return;

        var args = new List<string> { "-m", "obot", "--serve",
            "--host", _options.Host, "--port", _options.Port.ToString() };
        if (_options.Controller == "sim") args.Add("--sim");
        else if (_options.Controller == "console") args.Add("--console");

        var psi = new ProcessStartInfo
        {
            FileName = ResolvePython(_options),
            WorkingDirectory = _options.RepoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

        var process = new Process { StartInfo = psi, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) HandleLine(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is not null) HandleLine(e.Data); };
        process.Exited += (_, _) => Exited?.Invoke(this, process.ExitCode);

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        _process = process;
    }

    private void HandleLine(string line)
    {
        if (LooksLikeAddressInUse(line)) ObservedAddressInUse = true;
        OutputReceived?.Invoke(this, line);
    }

    /// <summary>Whether a stdout/stderr line looks like a "port already in use" bind
    /// failure (Windows/macOS/Linux phrasing), as opposed to some other crash.</summary>
    public static bool LooksLikeAddressInUse(string line) =>
        AddressInUseMarkers.Any(m => line.Contains(m, StringComparison.OrdinalIgnoreCase));

    public void Stop()
    {
        var process = _process;
        _process = null;
        if (process is null) return;
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(5000);
            }
        }
        catch { /* already gone */ }
        finally
        {
            process.Dispose();
        }
    }

    public void Dispose() => Stop();

    private static string ResolvePython(EngineLaunchOptions options)
    {
        if (!string.IsNullOrWhiteSpace(options.PythonPath) && File.Exists(options.PythonPath))
        {
            return options.PythonPath;
        }
        var venv = VenvPython(options.RepoRoot);
        if (venv is not null) return venv;
        return RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "python" : "python3";
    }

    /// <summary>The project's bundled virtualenv interpreter, if present.</summary>
    public static string? VenvPython(string repoRoot)
    {
        if (string.IsNullOrWhiteSpace(repoRoot)) return null;
        string[] candidates = RuntimeInformation.IsOSPlatform(OSPlatform.Windows)
            ? new[] { Path.Combine(repoRoot, "OhBots", "Scripts", "python.exe"),
                      Path.Combine(repoRoot, ".venv", "Scripts", "python.exe"),
                      Path.Combine(repoRoot, "venv", "Scripts", "python.exe") }
            : new[] { Path.Combine(repoRoot, "OhBots", "bin", "python"),
                      Path.Combine(repoRoot, ".venv", "bin", "python"),
                      Path.Combine(repoRoot, "venv", "bin", "python") };
        return candidates.FirstOrDefault(File.Exists);
    }

    /// <summary>
    /// Walk up from a starting directory to find the engine repo root (the folder that
    /// contains <c>src/obot/__main__.py</c>). Lets the GUI find the engine whether it runs
    /// from gui/**/bin during development or an installed location beside the repo.
    /// </summary>
    public static string? LocateRepoRoot(string? start = null)
    {
        var dir = new DirectoryInfo(start ?? AppContext.BaseDirectory);
        for (var d = dir; d is not null; d = d.Parent)
        {
            if (File.Exists(Path.Combine(d.FullName, "src", "obot", "__main__.py")))
            {
                return d.FullName;
            }
        }
        return null;
    }
}
