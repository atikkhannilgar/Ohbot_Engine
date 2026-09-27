using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Markup.Xaml;
using ObotControl.Core.ViewModels;

namespace ObotControl.App;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        AvaloniaXamlLoader.Load(this);
        // Dismiss tooltips once the pointer drifts, so they do not follow you across the app.
        Views.ToolTipBehavior.Install(this);
        // Tunnel so the window sees the key before a focused control consumes it  needed
        // to catch the push-to-talk hotkey. Typing in text boxes is explicitly left alone.
        AddHandler(KeyDownEvent, OnKeyDown, RoutingStrategies.Tunnel);
    }

    private void OnKeyDown(object? sender, KeyEventArgs e)
    {
        if (DataContext is not ShellViewModel shell) return;
        var dash = shell.Dashboard;

        // Rebinding: grab the very next key regardless of what's focused.
        if (dash.CapturingHotkey)
        {
            if (dash.HandleHotkey(e.Key.ToString())) e.Handled = true;
            return;
        }
        // Never hijack typing in a text field (e.g. Space in the message box).
        if (e.Source is TextBox) return;
        if (dash.HandleHotkey(e.Key.ToString())) e.Handled = true;
    }
}
