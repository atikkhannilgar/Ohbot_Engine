using System.Collections.Specialized;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using ObotControl.Core.ViewModels;

namespace ObotControl.App.Views;

public partial class DashboardView : UserControl
{
    private DashboardViewModel? _viewModel;

    public DashboardView()
    {
        AvaloniaXamlLoader.Load(this);
        DataContextChanged += (_, _) => HookTranscript();
    }

    // Keep the newest transcript line in view: scroll to the bottom whenever a
    // message arrives, after layout has placed it.
    private void HookTranscript()
    {
        if (_viewModel is not null)
            _viewModel.Transcript.CollectionChanged -= OnTranscriptChanged;

        _viewModel = DataContext as DashboardViewModel;
        if (_viewModel is not null)
            _viewModel.Transcript.CollectionChanged += OnTranscriptChanged;
    }

    private void OnTranscriptChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.Action != NotifyCollectionChangedAction.Add) return;
        Dispatcher.UIThread.Post(
            () => this.FindControl<ScrollViewer>("TranscriptScroll")?.ScrollToEnd(),
            DispatcherPriority.Loaded);
    }

    // Enter sends the turn, so a typed conversation never needs the mouse.
    // Shift+Enter is left alone for anyone who wants a literal newline.
    private void OnMessageKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key != Key.Return || e.KeyModifiers.HasFlag(KeyModifiers.Shift)) return;
        if (_viewModel is null || !_viewModel.SendCommand.CanExecute(null)) return;

        _viewModel.SendCommand.Execute(null);
        e.Handled = true;
    }
}
