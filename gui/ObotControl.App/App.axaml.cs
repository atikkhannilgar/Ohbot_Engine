using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using ObotControl.Core.ViewModels;

namespace ObotControl.App;

public partial class App : Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var shell = new ShellViewModel();
            // Marshal engine events + child-process output onto the UI thread.
            shell.UseDispatcher(action => Dispatcher.UIThread.Post(action));
            ApplyStartupArgs(shell, desktop.Args);

            desktop.MainWindow = new MainWindow { DataContext = shell };
            desktop.ShutdownRequested += (_, _) => shell.DisconnectCommand.Execute(null);
        }

        base.OnFrameworkInitializationCompleted();
    }

    /// <summary>
    /// Optional flags: <c>--host ADDR</c>, <c>--port N</c>, <c>--attach</c>
    /// (also <c>OBOT_HOST</c> / <c>OBOT_PORT</c> / <c>OBOT_AUTO_ATTACH=1</c>).
    /// </summary>
    private static void ApplyStartupArgs(ShellViewModel shell, string[]? args)
    {
        args ??= Array.Empty<string>();
        string? host = Environment.GetEnvironmentVariable("OBOT_HOST");
        int? port = null;
        if (int.TryParse(Environment.GetEnvironmentVariable("OBOT_PORT"), out var envPort))
            port = envPort;
        var autoAttach = Environment.GetEnvironmentVariable("OBOT_AUTO_ATTACH") is "1" or "true" or "TRUE";

        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--host" when i + 1 < args.Length:
                    host = args[++i];
                    break;
                case "--port" when i + 1 < args.Length && int.TryParse(args[++i], out var p):
                    port = p;
                    break;
                case "--attach":
                    autoAttach = true;
                    break;
            }
        }

        shell.ApplyStartupOptions(host, port, autoAttach);
    }
}
