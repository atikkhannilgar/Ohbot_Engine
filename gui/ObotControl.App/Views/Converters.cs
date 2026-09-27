using System.Globalization;
using Avalonia.Data.Converters;
using Avalonia.Media;
using ObotControl.Core.Protocol;
using ObotControl.Core.ViewModels;

namespace ObotControl.App.Views;

/// <summary>
/// Small value converters for status colours and empty-state visibility (kept trivial;
/// logic lives in Core). Colours mirror the tokens in Styles/Tokens.axaml -- keep the two
/// in sync when changing the palette.
/// </summary>
public static class Converters
{
    // Palette echo of Styles/Tokens.axaml, so status colours match the rest of the app.
    private static readonly Color SuccessColor = Color.FromRgb(0x2E, 0xA0, 0x57);
    private static readonly Color AccentColor = Color.FromRgb(0x3B, 0x82, 0xF6);
    private static readonly Color WarningColor = Color.FromRgb(0xE0, 0xA0, 0x40);
    private static readonly Color DangerColor = Color.FromRgb(0xC4, 0x48, 0x3A);
    private static readonly Color NeutralColor = Color.FromRgb(0x5A, 0x62, 0x70);

    // "Soft" fills sit behind a pill; the saturated colour above is used for its dot.
    private static readonly Color SuccessSoft = Color.FromRgb(0x12, 0x29, 0x1C);
    private static readonly Color AccentSoft = Color.FromRgb(0x16, 0x26, 0x3D);
    private static readonly Color WarningSoft = Color.FromRgb(0x2C, 0x22, 0x14);
    private static readonly Color NeutralSoft = Color.FromRgb(0x1A, 0x23, 0x31);

    public static readonly IValueConverter ConnectionBrush = new FuncValueConverter<bool, IBrush>(
        connected => new SolidColorBrush(connected ? SuccessColor : NeutralColor));

    public static readonly IValueConverter ConnectionSoftBrush = new FuncValueConverter<bool, IBrush>(
        connected => new SolidColorBrush(connected ? SuccessSoft : NeutralSoft));

    public static readonly IValueConverter PythonStatusBrush = new FuncValueConverter<PythonSetupStatusKind, IBrush>(kind => kind switch
    {
        PythonSetupStatusKind.Ready => new SolidColorBrush(SuccessColor),
        PythonSetupStatusKind.Busy => new SolidColorBrush(AccentColor),
        PythonSetupStatusKind.Error => new SolidColorBrush(DangerColor),
        _ => new SolidColorBrush(NeutralColor),
    });

    public static readonly IValueConverter StateBrush = new FuncValueConverter<BotState, IBrush>(state => state switch
    {
        BotState.Speaking => new SolidColorBrush(WarningColor),
        BotState.Listening => new SolidColorBrush(AccentColor),
        _ => new SolidColorBrush(NeutralColor),
    });

    public static readonly IValueConverter StateSoftBrush = new FuncValueConverter<BotState, IBrush>(state => state switch
    {
        BotState.Speaking => new SolidColorBrush(WarningSoft),
        BotState.Listening => new SolidColorBrush(AccentSoft),
        _ => new SolidColorBrush(NeutralSoft),
    });

    public static readonly IValueConverter CutOffDecoration = new FuncValueConverter<bool, TextDecorationCollection?>(
        cut => cut ? TextDecorations.Strikethrough : null);

    /// <summary>Highlights the active emotion button in the manual control panel.</summary>
    public static readonly IValueConverter BoolToAccent = new FuncValueConverter<bool, IBrush>(
        active => new SolidColorBrush(active ? AccentColor : Color.FromRgb(0x23, 0x2E, 0x3E)));

    /// <summary>True when a collection is empty -- drives the "nothing here yet" placeholders.</summary>
    public static readonly IValueConverter IsEmpty = new FuncValueConverter<int, bool>(count => count == 0);

    /// <summary>True for a non-blank string -- hides status lines that have nothing to say.</summary>
    public static readonly IValueConverter IsNotEmptyText = new FuncValueConverter<string?, bool>(
        text => !string.IsNullOrWhiteSpace(text));

    /// <summary>Tints the picked row of a list (the ML Control model library) so the active
    /// choice reads at a glance. Transparent leaves the inset card's own fill showing.</summary>
    public static readonly IValueConverter SelectedRowBrush = new FuncValueConverter<bool, IBrush>(
        selected => selected ? new SolidColorBrush(AccentSoft) : Brushes.Transparent);

    /// <summary>Present/missing tick for the ML dependency checklist.</summary>
    public static readonly IValueConverter CheckMark = new FuncValueConverter<bool, string>(
        present => present ? "✓" : "✗");

    public static readonly IValueConverter PresenceBrush = new FuncValueConverter<bool, IBrush>(
        present => new SolidColorBrush(present ? SuccessColor : DangerColor));
}
