using CommunityToolkit.Mvvm.ComponentModel;
using ObotControl.Core.Protocol;

namespace ObotControl.Core.ViewModels;

/// <summary>
/// Live joint positions (0..10, 5 = rest) mirrored from <c>joints</c> events, for the
/// face preview. Both GUIs bind their face drawing to these properties and redraw on
/// change  the ~80 lines of face geometry live in each view, the numbers live here.
/// </summary>
public partial class JointPose : ObservableObject
{
    [ObservableProperty] private double _headNod = 5.0;
    [ObservableProperty] private double _headTurn = 5.0;
    [ObservableProperty] private double _eyeTurn = 5.0;
    [ObservableProperty] private double _lidBlink = 5.0;
    [ObservableProperty] private double _topLip = 5.0;
    [ObservableProperty] private double _bottomLip = 5.0;
    [ObservableProperty] private double _eyeTilt = 5.0;
    [ObservableProperty] private double _headTilt = 5.0;

    /// <summary>Raised after any joint changes, so a view can trigger one redraw.</summary>
    public event EventHandler? Changed;

    public void Update(JointsEvent joints)
    {
        HeadNod = joints.Get("HeadNod");
        HeadTurn = joints.Get("HeadTurn");
        EyeTurn = joints.Get("EyeTurn");
        LidBlink = joints.Get("LidBlink");
        TopLip = joints.Get("TopLip");
        BottomLip = joints.Get("BottomLip");
        EyeTilt = joints.Get("EyeTilt");
        HeadTilt = joints.Get("HeadTilt");
        Changed?.Invoke(this, EventArgs.Empty);
    }
}
