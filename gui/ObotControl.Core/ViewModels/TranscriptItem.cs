using CommunityToolkit.Mvvm.ComponentModel;

namespace ObotControl.Core.ViewModels;

public enum TranscriptKind { User, Bot, Action, Emotion, System }

/// <summary>One row in the conversation transcript (a user/bot turn, or an inline chip).</summary>
public partial class TranscriptItem : ObservableObject
{
    public TranscriptKind Kind { get; init; }
    public string Text { get; init; } = "";

    /// <summary>Bot sentence that was interrupted at a word boundary (shown struck-through).</summary>
    [ObservableProperty] private bool _cutOff;

    public bool IsUser => Kind == TranscriptKind.User;
    public bool IsBot => Kind == TranscriptKind.Bot;
    public bool IsChip => Kind is TranscriptKind.Action or TranscriptKind.Emotion;
    public bool IsSystem => Kind == TranscriptKind.System;

    /// <summary>Speaker/kind label shown before the text (keeps item templates trivial).</summary>
    public string Prefix => Kind switch
    {
        TranscriptKind.User => "You",
        TranscriptKind.Bot => "Ms. Mimic",
        TranscriptKind.Action => "action",
        TranscriptKind.Emotion => "emotion",
        _ => "•",
    };

    public string Display => Kind switch
    {
        TranscriptKind.Action => $"[{Text}]",
        TranscriptKind.Emotion => $"({Text})",
        _ => Text,
    };
}
