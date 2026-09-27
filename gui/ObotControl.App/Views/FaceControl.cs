using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using ObotControl.Core.ViewModels;

namespace ObotControl.App.Views;

/// <summary>
/// Draws the OhBot head from the live <see cref="JointPose"/> with a pseudo-3D look.
///
/// * HeadTurn <b>yaws</b> the head: the features shift with parallax, the far side of
///   the shell foreshortens, and the shading moves  reading as a real turn rather
///   than a flat slide. HeadNod raises/dips the whole assembly. HeadTilt <b>rolls</b>
///   the head shell and features (not the neck, which stays upright) about the head
///   center, like the roll servo mounted between neck and shell on the real robot.
/// * A fixed light from the top-left shades everything: the shell carries a crown
///   highlight and a turned-away side in shadow, the eyes are glossy spheres with
///   catchlights, the lip plates are brushed metal.
/// * Each eye has a shell-blue eyelid clipped to the eyeball, so a blink reads as a
///   lid sweeping down and a partial value (a tired half-lid) covers the eye partway.
/// * The mouth stays honest to the hardware: two independent lip plates (TopLip
///   lifts, BottomLip drops) around a dark cavity.
///
/// The base plate never moves; the head, neck and features ride the pose. Redraws
/// whenever a joints event updates the pose.
/// </summary>
public class FaceControl : Control
{
    public static readonly StyledProperty<JointPose?> PoseProperty =
        AvaloniaProperty.Register<FaceControl, JointPose?>(nameof(Pose));

    public JointPose? Pose
    {
        get => GetValue(PoseProperty);
        set => SetValue(PoseProperty, value);
    }

    // Palette: blue shell, warm amber eyes, brushed-metal mouth.
    private static readonly Color Shell = Color.FromRgb(43, 108, 210);
    private static readonly Color ShellInner = Color.FromRgb(33, 86, 176);
    private static readonly Pen ShellEdge = new(new SolidColorBrush(Color.FromRgb(120, 176, 236)), 2);
    private static readonly Pen LidCrease = new(new SolidColorBrush(Color.FromArgb(160, 22, 52, 104)), 1);
    private static readonly Pen IrisEdge = new(new SolidColorBrush(Color.FromRgb(150, 96, 24)), 1.5);
    private static readonly IBrush Pupil = new SolidColorBrush(Color.FromRgb(20, 23, 31));
    private static readonly IBrush CatchLight = new SolidColorBrush(Color.FromArgb(215, 255, 255, 255));
    private static readonly IBrush GlintLight = new SolidColorBrush(Color.FromArgb(70, 255, 255, 255));
    private static readonly Pen SilverEdge = new(new SolidColorBrush(Color.FromRgb(138, 147, 163)), 1.5);
    private static readonly IBrush Servo = new SolidColorBrush(Color.FromRgb(28, 32, 42));
    private static readonly IBrush HeadShadow = new SolidColorBrush(Color.FromArgb(90, 0, 0, 0));

    private JointPose? _subscribed;

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property != PoseProperty) return;
        if (_subscribed is not null) _subscribed.Changed -= OnPoseChanged;
        _subscribed = Pose;
        if (_subscribed is not null) _subscribed.Changed += OnPoseChanged;
        InvalidateVisual();
    }

    private void OnPoseChanged(object? sender, EventArgs e) => InvalidateVisual();

    /// <summary>Joint position as a signed delta from rest (positions are 0..10, 5 = rest).</summary>
    private static double D(double pos) => pos - 5.0;

    /// <summary>Lighten (f &gt; 0) or darken (f &lt; 0) a colour toward white/black.</summary>
    private static Color Shade(Color c, double f)
    {
        double t = Math.Clamp(Math.Abs(f), 0, 1);
        byte Mix(byte ch, byte target) => (byte)(ch + (target - ch) * t);
        return f >= 0
            ? Color.FromRgb(Mix(c.R, 255), Mix(c.G, 255), Mix(c.B, 255))
            : Color.FromRgb(Mix(c.R, 0), Mix(c.G, 0), Mix(c.B, 0));
    }

    private static LinearGradientBrush VerticalGradient(params GradientStop[] stops)
    {
        var brush = new LinearGradientBrush
        {
            StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
            EndPoint = new RelativePoint(0, 1, RelativeUnit.Relative),
        };
        foreach (var stop in stops) brush.GradientStops.Add(stop);
        return brush;
    }

    private static LinearGradientBrush HorizontalGradient(params GradientStop[] stops)
    {
        var brush = new LinearGradientBrush
        {
            StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
            EndPoint = new RelativePoint(1, 0, RelativeUnit.Relative),
        };
        foreach (var stop in stops) brush.GradientStops.Add(stop);
        return brush;
    }

    public override void Render(DrawingContext ctx)
    {
        var b = Bounds;
        DrawBackground(ctx, b);
        if (b.Width < 40 || b.Height < 40) return;

        var pose = Pose ?? new JointPose();
        double unit = Math.Min(b.Width, b.Height) * 0.92;

        // Normalized head orientation, all -1..1.
        double yaw = Math.Clamp(D(pose.HeadTurn) / 5.0, -1, 1);
        double pitch = Math.Clamp(D(pose.HeadNod) / 5.0, -1, 1);
        double roll = Math.Clamp(D(pose.HeadTilt) / 5.0, -1, 1);

        double baseCx = b.Width / 2;
        double baseCy = b.Height * 0.90;
        DrawBase(ctx, baseCx, baseCy, unit);

        // The shell shifts a little with the yaw; the features shift more (parallax)
        // and compress horizontally (foreshortening), which is what sells the turn.
        double headCx = baseCx + yaw * unit * 0.05;
        double headCy = baseCy - unit * 0.49 + pitch * unit * -0.03;
        double headW = unit * 0.62 * (1 - Math.Abs(yaw) * 0.08);
        double headH = unit * 0.74 * (1 - Math.Abs(pitch) * 0.04);
        double featureDx = yaw * unit * 0.075;
        double featureDy = pitch * unit * -0.045;
        double featureScaleX = 1 - Math.Abs(yaw) * 0.12;

        // Soft shadow the head casts on the base plate.
        ctx.DrawEllipse(HeadShadow, null,
            new Point(headCx, baseCy - unit * 0.075), unit * 0.26, unit * 0.045);

        DrawNeck(ctx, headCx, headCy + headH / 2 - unit * 0.04, baseCy, unit);

        // The shell and features roll together about the head center; the neck above
        // stays upright, matching a roll servo mounted between neck and shell.
        double rollAngle = roll * Math.PI / 9; // up to 20 degrees each way
        using (ctx.PushTransform(
            Matrix.CreateTranslation(-headCx, -headCy) *
            Matrix.CreateRotation(rollAngle) *
            Matrix.CreateTranslation(headCx, headCy)))
        {
            DrawHead(ctx, headCx, headCy, headW, headH, unit, yaw);

            double eyeR = unit * 0.145;
            double eyeY = headCy - unit * 0.14 + featureDy;
            double eyeDX = unit * 0.185 * featureScaleX;
            DrawEye(ctx, headCx + featureDx - eyeDX, eyeY, eyeR, pose, yaw);
            DrawEye(ctx, headCx + featureDx + eyeDX, eyeY, eyeR, pose, yaw);

            DrawMouth(ctx, headCx + featureDx, headCy + unit * 0.235 + featureDy,
                unit, featureScaleX, pose);
        }
    }

    private static void DrawBackground(DrawingContext ctx, Rect b)
    {
        var rect = new Rect(0, 0, b.Width, b.Height);
        ctx.FillRectangle(VerticalGradient(
            new GradientStop(Color.FromRgb(23, 28, 39), 0),
            new GradientStop(Color.FromRgb(11, 13, 18), 1)), rect);

        // Faint glow behind the head so the robot doesn't sit in a void.
        var glow = new RadialGradientBrush
        {
            Center = new RelativePoint(0.5, 0.42, RelativeUnit.Relative),
            GradientOrigin = new RelativePoint(0.5, 0.42, RelativeUnit.Relative),
        };
        glow.GradientStops.Add(new GradientStop(Color.FromArgb(34, 80, 140, 235), 0));
        glow.GradientStops.Add(new GradientStop(Color.FromArgb(0, 80, 140, 235), 1));
        ctx.FillRectangle(glow, rect);
    }

    private static void DrawBase(DrawingContext ctx, double cx, double cy, double unit)
    {
        ctx.DrawEllipse(VerticalGradient(
                new GradientStop(Color.FromRgb(45, 100, 190), 0),
                new GradientStop(Color.FromRgb(20, 50, 98), 1)),
            ShellEdge, new Point(cx, cy), unit * 0.44, unit * 0.10);
        ctx.DrawRectangle(Servo, null,
            new Rect(cx - unit * 0.11, cy - unit * 0.12, unit * 0.22, unit * 0.12), 3, 3);
    }

    private static void DrawNeck(DrawingContext ctx, double cx, double top, double baseCy, double unit)
    {
        double w = unit * 0.10;
        double bottom = baseCy - unit * 0.05;
        ctx.DrawRectangle(HorizontalGradient(
                new GradientStop(Color.FromRgb(58, 66, 82), 0),
                new GradientStop(Color.FromRgb(30, 35, 46), 0.55),
                new GradientStop(Color.FromRgb(20, 24, 32), 1)),
            null, new Rect(cx - w / 2, top, w, Math.Max(1, bottom - top)), 3, 3);
    }

    private static void DrawHead(DrawingContext ctx, double cx, double cy,
        double w, double h, double unit, double yaw)
    {
        var headRect = new Rect(cx - w / 2, cy - h / 2, w, h);
        double cr = unit * 0.16;

        // Directional shading: the side turned away from the fixed top-left light
        // darkens as the head yaws, the lit side brightens.
        double lightLeft = 0.16 + 0.10 * yaw;
        double darkRight = -(0.20 + 0.10 * yaw);
        ctx.DrawRectangle(HorizontalGradient(
                new GradientStop(Shade(Shell, lightLeft), 0),
                new GradientStop(Shell, 0.45),
                new GradientStop(Shade(Shell, darkRight), 1)),
            ShellEdge, headRect, cr, cr);

        // Inner face panel, slightly inset and darker.
        double iw = w * 0.82, ih = h * 0.84;
        var panelRect = new Rect(cx - iw / 2, cy - ih / 2, iw, ih);
        ctx.DrawRectangle(HorizontalGradient(
                new GradientStop(Shade(ShellInner, lightLeft * 0.7), 0),
                new GradientStop(ShellInner, 0.5),
                new GradientStop(Shade(ShellInner, darkRight * 0.7), 1)),
            null, panelRect, unit * 0.12, unit * 0.12);

        // Crown highlight from the overhead light.
        ctx.DrawRectangle(VerticalGradient(
                new GradientStop(Color.FromArgb(56, 255, 255, 255), 0),
                new GradientStop(Color.FromArgb(0, 255, 255, 255), 0.45)),
            null, headRect, cr, cr);
    }

    private static void DrawEye(DrawingContext ctx, double cx, double cy, double r,
        JointPose pose, double yaw)
    {
        var eyeRect = new Rect(cx - r, cy - r, r * 2, r * 2);
        var center = new Point(cx, cy);

        // Eyeball: a warm white sphere, lit from the upper left.
        var ball = new RadialGradientBrush
        {
            Center = new RelativePoint(0.42, 0.38, RelativeUnit.Relative),
            GradientOrigin = new RelativePoint(0.34, 0.28, RelativeUnit.Relative),
        };
        ball.GradientStops.Add(new GradientStop(Color.FromRgb(255, 250, 235), 0));
        ball.GradientStops.Add(new GradientStop(Color.FromRgb(240, 229, 201), 0.6));
        ball.GradientStops.Add(new GradientStop(Color.FromRgb(190, 178, 148), 1));
        ctx.DrawEllipse(ball, null, center, r, r);

        // Iris carries the eye servos plus a touch of the head yaw, so the gaze
        // stays glued to the sphere as the head turns. Clamp the offset so the
        // iris (radius 0.58r) never crosses the eyeball's edge, however extreme
        // the joint values are.
        double irisR = r * 0.58;
        double dx = D(pose.EyeTurn) * r * 0.11 + yaw * r * 0.16;
        double dy = -D(pose.EyeTilt) * r * 0.11;
        double maxOffset = (r - irisR) * 0.9;
        double dist = Math.Sqrt(dx * dx + dy * dy);
        if (dist > maxOffset && dist > 0)
        {
            double scale = maxOffset / dist;
            dx *= scale;
            dy *= scale;
        }
        double px = cx + dx;
        double py = cy + dy;
        var iris = new RadialGradientBrush
        {
            Center = new RelativePoint(0.45, 0.42, RelativeUnit.Relative),
            GradientOrigin = new RelativePoint(0.38, 0.34, RelativeUnit.Relative),
        };
        iris.GradientStops.Add(new GradientStop(Color.FromRgb(242, 178, 74), 0));
        iris.GradientStops.Add(new GradientStop(Color.FromRgb(216, 145, 43), 0.6));
        iris.GradientStops.Add(new GradientStop(Color.FromRgb(150, 96, 24), 1));

        // Belt-and-suspenders: the offset clamp above already keeps the iris inside
        // the eyeball, but clip to the eyeball circle too so nothing can ever paint
        // outside it, even if the radii above are tuned differently later.
        using (ctx.PushGeometryClip(new EllipseGeometry(eyeRect)))
        {
            ctx.DrawEllipse(iris, IrisEdge, new Point(px, py), irisR, irisR);
            ctx.DrawEllipse(Pupil, null, new Point(px, py), r * 0.27, r * 0.27);
            ctx.DrawEllipse(CatchLight, null, new Point(px - r * 0.16, py - r * 0.18), r * 0.09, r * 0.09);
            ctx.DrawEllipse(GlintLight, null, new Point(px + r * 0.15, py + r * 0.14), r * 0.05, r * 0.05);
        }

        // Eyelid: draw on the true 0..10 servo scale (10 = disc fully lifted, 0 =
        // closed). Open-rest on this OhBot is commanded at 7, so the preview shows
        // the same partial-open look as the hardware — not a remapped "7 = fully open".
        double openness = Math.Clamp(pose.LidBlink / 10.0, 0, 1);
        double lidCy = cy - openness * (2 * r);
        using (ctx.PushGeometryClip(new EllipseGeometry(eyeRect)))
        {
            ctx.DrawEllipse(VerticalGradient(
                    new GradientStop(Shade(Shell, 0.22), 0),
                    new GradientStop(Shade(Shell, -0.08), 1)),
                null, new Point(cx, lidCy), r * 1.04, r);
            ctx.DrawEllipse(null, LidCrease, new Point(cx, lidCy), r * 1.04, r);

            // Ambient occlusion under the brow, so the sphere sits "inside" the head.
            ctx.DrawEllipse(null, new Pen(new SolidColorBrush(Color.FromArgb(70, 0, 0, 0)), r * 0.14),
                center, r * 0.96, r * 0.96);
        }
        ctx.DrawEllipse(null, new Pen(ShellEdge.Brush!, 1.5), center, r, r);
    }

    /// <summary>Two independent brushed-metal lip plates around a dark cavity:
    /// TopLip lifts up, BottomLip drops down (deltas above rest).</summary>
    private static void DrawMouth(DrawingContext ctx, double cx, double my,
        double unit, double scaleX, JointPose pose)
    {
        double mouthW = unit * 0.40 * scaleX;
        double lipH = unit * 0.075;
        double travel = unit * 0.11;
        double restGap = unit * 0.015;

        double topOpen = Math.Max(0, D(pose.TopLip)) / 5.0 * travel;
        double botOpen = Math.Max(0, D(pose.BottomLip)) / 5.0 * travel;
        double topFrown = Math.Max(0, -D(pose.TopLip)) / 5.0 * (unit * 0.03);
        double botFrown = Math.Max(0, -D(pose.BottomLip)) / 5.0 * (unit * 0.03);

        double topBottomEdge = my - restGap / 2 - topOpen + topFrown;
        double botTopEdge = my + restGap / 2 + botOpen - botFrown;

        double cavTop = topBottomEdge - lipH * 0.2;
        double cavBot = botTopEdge + lipH * 0.2;
        ctx.DrawRectangle(VerticalGradient(
                new GradientStop(Color.FromRgb(4, 5, 7), 0),
                new GradientStop(Color.FromRgb(22, 16, 18), 1)),
            null,
            new Rect(cx - mouthW / 2, cavTop, mouthW, Math.Max(1, cavBot - cavTop)),
            lipH * 0.4, lipH * 0.4);

        DrawLipPlate(ctx, cx, topBottomEdge - lipH, mouthW, lipH);
        DrawLipPlate(ctx, cx, botTopEdge, mouthW, lipH);
    }

    private static void DrawLipPlate(DrawingContext ctx, double cx, double y, double w, double h)
    {
        double r = h * 0.5; // pill-shaped plate
        ctx.DrawRectangle(VerticalGradient(
                new GradientStop(Color.FromRgb(236, 240, 246), 0),
                new GradientStop(Color.FromRgb(199, 205, 214), 0.5),
                new GradientStop(Color.FromRgb(158, 166, 180), 1)),
            SilverEdge, new Rect(cx - w / 2, y, w, h), r, r);
    }
}
