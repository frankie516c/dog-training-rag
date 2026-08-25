param(
  [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;

public static class DaengsThemeRenderer
{
    public sealed class Palette
    {
        public string Id;
        public Color Scene, Wall, Floor, Accent, AccentSoft, Cream, Pot;
        public Palette(string id, string scene, string wall, string floor, string accent, string accentSoft, string cream, string pot)
        {
            Id = id;
            Scene = Hex(scene); Wall = Hex(wall); Floor = Hex(floor); Accent = Hex(accent);
            AccentSoft = Hex(accentSoft); Cream = Hex(cream); Pot = Hex(pot);
        }
    }

    static Color Hex(string value) { return ColorTranslator.FromHtml(value); }
    static double Clamp(double value, double min, double max) { return Math.Max(min, Math.Min(max, value)); }

    static void Hsl(Color color, out double hue, out double saturation, out double lightness)
    {
        double r = color.R / 255.0, g = color.G / 255.0, b = color.B / 255.0;
        double max = Math.Max(r, Math.Max(g, b)), min = Math.Min(r, Math.Min(g, b));
        lightness = (max + min) / 2.0;
        if (Math.Abs(max - min) < 0.0001) { hue = 0; saturation = 0; return; }
        double delta = max - min;
        saturation = lightness > 0.5 ? delta / (2.0 - max - min) : delta / (max + min);
        if (max == r) hue = ((g - b) / delta + (g < b ? 6 : 0)) / 6.0;
        else if (max == g) hue = ((b - r) / delta + 2) / 6.0;
        else hue = ((r - g) / delta + 4) / 6.0;
    }

    static double HueToRgb(double p, double q, double t)
    {
        if (t < 0) t += 1; if (t > 1) t -= 1;
        if (t < 1.0 / 6) return p + (q - p) * 6 * t;
        if (t < 1.0 / 2) return q;
        if (t < 2.0 / 3) return p + (q - p) * (2.0 / 3 - t) * 6;
        return p;
    }

    static Color FromHsl(double h, double s, double l, byte alpha)
    {
        double r, g, b;
        if (s < 0.0001) r = g = b = l;
        else {
            double q = l < 0.5 ? l * (1 + s) : l + s - l * s;
            double p = 2 * l - q;
            r = HueToRgb(p, q, h + 1.0 / 3); g = HueToRgb(p, q, h); b = HueToRgb(p, q, h - 1.0 / 3);
        }
        return Color.FromArgb(alpha, (int)Math.Round(Clamp(r, 0, 1) * 255), (int)Math.Round(Clamp(g, 0, 1) * 255), (int)Math.Round(Clamp(b, 0, 1) * 255));
    }

    static Color Shade(Color source, Color target, double sourceReference, double strength = 1.0)
    {
        double sh, ss, sl, th, ts, tl;
        Hsl(source, out sh, out ss, out sl); Hsl(target, out th, out ts, out tl);
        double newL = Clamp(tl + (sl - sourceReference) * 0.82, 0.045, 0.97);
        double newS = Clamp(ts * (0.82 + ss * 0.28), 0, 0.88);
        Color themed = FromHsl(th, newS, newL, source.A);
        if (strength >= 0.999) return themed;
        return Color.FromArgb(source.A,
            (int)Math.Round(source.R + (themed.R - source.R) * strength),
            (int)Math.Round(source.G + (themed.G - source.G) * strength),
            (int)Math.Round(source.B + (themed.B - source.B) * strength));
    }

    static bool InFloor(double x, double y)
    {
        double[][] p = { new[]{.005,.685}, new[]{.565,.518}, new[]{.998,.710}, new[]{.430,.968} };
        bool inside = false;
        for (int i = 0, j = p.Length - 1; i < p.Length; j = i++) {
            if (((p[i][1] > y) != (p[j][1] > y)) && x < (p[j][0] - p[i][0]) * (y - p[i][1]) / (p[j][1] - p[i][1]) + p[i][0]) inside = !inside;
        }
        return inside;
    }

    static bool InFencePost(double x, double y, double centerX, double top, double bottom, double halfWidth)
    {
        if (y < top || y > bottom) return false;
        const double capHeight = .012;
        double width = halfWidth;
        if (y < top + capHeight) {
            double progress = (y - top) / capHeight;
            width *= .34 + .66 * progress;
        }
        return Math.Abs(x - centerX) < width;
    }

    static Color ThemeRoom(Color c, int px, int py, int width, int height, Palette p)
    {
        double x = (double)px / width, y = (double)py / height;
        double h, s, l; Hsl(c, out h, out s, out l);
        bool outdoor = x > .315 && x < .512 && y > .175 && y < .455 && ((h > .12 && h < .72 && s > .22) || l > .91);
        if (outdoor) return c;
        if (x < .205 && y > .365 && y < .675 && h > .12 && h < .36 && s > .18) return Shade(c, p.Accent, .43);
        // The fence shares its original hue with the floor, so a broad polygon
        // would tint the floor behind it. Follow the four posts and two rails
        // instead; the narrow perspective bands preserve their pixel silhouette.
        bool fencePost =
            InFencePost(x, y, .509, .874, .988, .025) ||
            InFencePost(x, y, .663, .807, .915, .023) ||
            InFencePost(x, y, .774, .766, .863, .022) ||
            InFencePost(x, y, .932, .704, .798, .021);
        bool upperRail = x > .523 && x < .914
            && y > 1.105 - .430 * x
            && y < 1.135 - .420 * x;
        bool lowerRail = x > .524 && x < .914
            && y > 1.150 - .421 * x
            && y < 1.183 - .417 * x;
        bool fenceRail = upperRail || lowerRail;
        bool frontFence = fencePost || fenceRail;
        if (frontFence) {
            if (l > .46) return Shade(c, p.AccentSoft, .50);
            return Shade(c, p.Accent, .43);
        }
        // Floor visible through the open rail gaps sits just outside InFloor().
        // Continue the pastel floor through that narrow perspective band while
        // the rail and post masks above keep every fence surface in its palette.
        bool fenceBackdrop = x > .47 && x < .975
            && y > 1.052 - .398 * x
            && y < 1.182 - .408 * x
            && (h < .20 || h > .97) && s > .18;
        if (fenceBackdrop) return Shade(c, p.Floor, .58);
        if (InFloor(x, y)) {
            return Shade(c, p.Floor, .58);
        }
        bool roomShell = y < .72 && (x < .57 || y < .54 + (x - .57) * .43);
        if (roomShell && h > .045 && h < .19) {
            if (l > .82) return Shade(c, p.Cream, .88);
            return Shade(c, p.Wall, .70);
        }
        if (!roomShell && h > .045 && h < .19 && s < .62) return Shade(c, p.Scene, .62);
        return c;
    }

    static bool IsGreen(double h, double s) { return h > .14 && h < .40 && s > .16; }
    static bool IsWarmNeutral(double h, double s, double l) { return h > .045 && h < .19 && s > .12 && l > .32; }
    static bool IsBrass(double h, double s, double l) { return h > .075 && h < .14 && s > .58 && l < .68; }
    static bool InEllipse(double x, double y, double centerX, double centerY, double radiusX, double radiusY)
    {
        double dx = (x - centerX) / radiusX, dy = (y - centerY) / radiusY;
        return dx * dx + dy * dy <= 1;
    }

    static Color ThemeAsset(Color c, int x, int y, int width, int height, string kind, Palette p)
    {
        double h, s, l; Hsl(c, out h, out s, out l);
        double nx = (double)x / width, ny = (double)y / height;
        if (kind == "ball") return Shade(c, p.AccentSoft, .55);
        if (kind == "doghouse") {
            if (IsGreen(h, s)) return Shade(c, p.Accent, .43);
            if (IsWarmNeutral(h, s, l)) return Shade(c, p.Cream, .82);
        }
        if (kind == "cabinet") {
            // Assign every opaque cabinet pixel to an intentional surface so
            // original orange texture cannot leak through the themed finish.
            // Coordinates follow the canonical cabinet perspective; brass knob
            // pixels retain their natural material.
            bool leftDrawers = nx >= .055 && nx < .395
                && ny > .207 + .494 * nx
                && ny < .546 + .449 * nx;
            bool rightDrawers = nx >= .395 && nx < .715
                && ny > .230 + .444 * nx
                && ny < .551 + .450 * nx;
            bool cabinetKnob =
                InEllipse(nx, ny, .218, .402, .034, .039) ||
                InEllipse(nx, ny, .218, .548, .034, .039) ||
                InEllipse(nx, ny, .529, .549, .034, .039) ||
                InEllipse(nx, ny, .529, .707, .034, .039);
            if (cabinetKnob && (IsBrass(h, s, l) || l < .34)) return c;
            if (leftDrawers) return Shade(c, p.Accent, .43);
            if (rightDrawers) return Shade(c, p.AccentSoft, .55);
            return Shade(c, p.Cream, .82);
        }
        if (kind == "rug") {
            if (IsGreen(h, s)) return Shade(c, p.AccentSoft, .55);
            if (IsWarmNeutral(h, s, l)) return Shade(c, p.Cream, .84);
        }
        if (kind == "rug-cream" && IsWarmNeutral(h, s, l)) return Shade(c, p.Cream, .84);
        if (kind == "plant") {
            if (ny > .66 && !IsGreen(h, s) && !(h > .045 && h < .13 && s > .58 && l < .52)) return Shade(c, p.Pot, .60);
            return c; // foliage and soil remain natural
        }
        if (kind == "basket") {
            if (IsGreen(h, s)) return Shade(c, p.AccentSoft, .52);
            return c; // wicker, rope and bone remain natural
        }
        if (kind == "bowls") {
            if (nx < .51 && IsGreen(h, s)) return Shade(c, p.Accent, .43);
            if (nx >= .45 && IsGreen(h, s)) return Shade(c, p.Cream, .82);
            return c; // food and water retain natural colors
        }
        return c;
    }

    public static void Render(string sourcePath, string outputPath, string kind, Palette palette)
    {
        using (Bitmap input = new Bitmap(sourcePath))
        using (Bitmap bitmap = new Bitmap(input.Width, input.Height, PixelFormat.Format32bppArgb)) {
            using (Graphics graphics = Graphics.FromImage(bitmap)) graphics.DrawImageUnscaled(input, 0, 0);
            Rectangle rect = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
            BitmapData data = bitmap.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
            int size = Math.Abs(data.Stride) * bitmap.Height;
            byte[] pixels = new byte[size]; Marshal.Copy(data.Scan0, pixels, 0, size);
            for (int y = 0; y < bitmap.Height; y++) for (int x = 0; x < bitmap.Width; x++) {
                int i = y * data.Stride + x * 4;
                byte a = pixels[i + 3]; if (a == 0) continue;
                Color source = Color.FromArgb(a, pixels[i + 2], pixels[i + 1], pixels[i]);
                Color output = kind == "room" ? ThemeRoom(source, x, y, bitmap.Width, bitmap.Height, palette) : ThemeAsset(source, x, y, bitmap.Width, bitmap.Height, kind, palette);
                pixels[i] = output.B; pixels[i + 1] = output.G; pixels[i + 2] = output.R; pixels[i + 3] = output.A;
            }
            Marshal.Copy(pixels, 0, data.Scan0, size); bitmap.UnlockBits(data);
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            bitmap.Save(outputPath, ImageFormat.Png);
        }
    }
}
'@

$palettes = @(
  [DaengsThemeRenderer+Palette]::new("cherry-blossom", "#d7b7bf", "#f4d7df", "#d9aab4", "#a95e76", "#d9849b", "#fff3e1", "#dfa1ac"),
  [DaengsThemeRenderer+Palette]::new("mint", "#b8d4c8", "#d8efe5", "#aecfbe", "#5f9d85", "#83bfa8", "#fff7e8", "#8db9a8"),
  [DaengsThemeRenderer+Palette]::new("lavender", "#c8bcd6", "#e7dcf2", "#bcaed2", "#79629a", "#a18bc0", "#fff5e9", "#b6a1cc"),
  [DaengsThemeRenderer+Palette]::new("sky-blue", "#bdd3e2", "#dceef7", "#a9cee5", "#4f83aa", "#79add0", "#fff8ec", "#91b9d0"),
  [DaengsThemeRenderer+Palette]::new("butter", "#d9c997", "#fff0bd", "#dfc47e", "#b68737", "#d7ad55", "#fff8de", "#e2c16e")
)

$assetRoot = Join-Path $RepositoryRoot "ui-experiments\main-screen\assets"
$outputs = [ordered]@{
  "room" = "modular-empty-room-v1.png"
  "ball" = "modular-ball-v1-final.png"
  "cabinet" = "modular-cabinet-v1-final.png"
  "doghouse" = "modular-doghouse-v1-final.png"
  "bowls" = "modular-feeding-bowls-v1-final.png"
  "plant" = "modular-plant-v1-final.png"
  "rug" = "modular-rug-sage-v1-final.png"
  "rug-cream" = "modular-rug-v1-final.png"
  "basket" = "modular-toy-basket-v1-final.png"
}

foreach ($palette in $palettes) {
  $themeDirectory = Join-Path $assetRoot ("themes\" + $palette.Id)
  foreach ($entry in $outputs.GetEnumerator()) {
    $source = Join-Path $assetRoot $entry.Value
    $destination = Join-Path $themeDirectory ($entry.Key + ".png")
    [DaengsThemeRenderer]::Render($source, $destination, $entry.Key, $palette)
  }
  Write-Output ("Rendered " + $palette.Id)
}
