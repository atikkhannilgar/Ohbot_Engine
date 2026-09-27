using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;

namespace ObotControl.App.Views;

/// <summary>
/// Makes the app-wide tooltips less intrusive.
///
/// Every control here carries a tooltip, which is helpful when you rest on something and
/// annoying when you are just crossing the window on the way somewhere else. Two rules fix
/// that: tooltips wait longer before appearing, and an open tooltip is dismissed as soon as
/// the pointer drifts away from where it was when the tooltip opened -- so a tooltip only
/// stays up while you actually hold still on the control.
/// </summary>
public static class ToolTipBehavior
{
    /// <summary>
    /// How far the pointer may drift from the position it had when the tooltip opened,
    /// in device-independent pixels, before the tooltip is dismissed. Roughly "still on the
    /// same word/icon" -- small enough to feel responsive, large enough that hand tremor or
    /// a one-pixel nudge does not flicker it away.
    /// </summary>
    private const double DriftTolerance = 28.0;

    private static bool _hooked;
    private static Control? _openOwner;
    private static Point _anchor;
    private static Point _last;

    /// <summary>
    /// Starts watching pointer movement on a window. Tunnelled and handled-events-too so it
    /// sees the move regardless of which control ends up consuming it.
    /// </summary>
    /// <remarks>
    /// The longer hover delay is a separate concern and lives in Styles/Controls.axaml.
    /// It cannot be set here: Avalonia already registers ShowDelay metadata for Control,
    /// so OverrideDefaultValue throws.
    /// </remarks>
    public static void Install(TopLevel topLevel)
    {
        if (!_hooked)
        {
            _hooked = true;
            ToolTip.IsOpenProperty.Changed.AddClassHandler<Control>(OnIsOpenChanged);
        }

        topLevel.AddHandler(InputElement.PointerMovedEvent, OnPointerMoved,
                            RoutingStrategies.Tunnel, handledEventsToo: true);
    }

    private static void OnIsOpenChanged(Control owner, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.GetNewValue<bool>())
        {
            // Anchor on the last position we saw: the tooltip opens under a resting pointer,
            // so this is where the user was when they asked for it.
            _openOwner = owner;
            _anchor = _last;
        }
        else if (ReferenceEquals(owner, _openOwner))
        {
            _openOwner = null;
        }
    }

    private static void OnPointerMoved(object? sender, PointerEventArgs e)
    {
        if (sender is not Visual root) return;

        _last = e.GetPosition(root);

        var owner = _openOwner;
        if (owner is null) return;

        var dx = _last.X - _anchor.X;
        var dy = _last.Y - _anchor.Y;
        if (dx * dx + dy * dy < DriftTolerance * DriftTolerance) return;

        // Clear first: closing raises IsOpenChanged re-entrantly.
        _openOwner = null;
        ToolTip.SetIsOpen(owner, false);
    }
}
