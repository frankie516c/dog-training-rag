param(
  [Parameter(Mandatory = $true)]
  [string]$InputPath,

  [Parameter(Mandatory = $true)]
  [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not ("DogSpriteNormalizer" -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;

public static class DogSpriteNormalizer
{
    private const int FrameCount = 4;
    private const int FrameWidth = 582;
    private const int FrameHeight = 568;
    private const int AlphaThreshold = 24;

    public static void Normalize(string inputPath, string outputPath)
    {
        using (var original = new Bitmap(inputPath))
        using (var source = ToArgb(original))
        {
            var bounds = FindFrameBounds(source);
            var maxWidth = 1;
            var maxHeight = 1;
            foreach (var bound in bounds)
            {
                maxWidth = Math.Max(maxWidth, bound.Width);
                maxHeight = Math.Max(maxHeight, bound.Height);
            }

            var scale = Math.Min(542.0 / maxWidth, 526.0 / maxHeight);
            using (var output = new Bitmap(FrameWidth * FrameCount, FrameHeight, PixelFormat.Format32bppArgb))
            using (var graphics = Graphics.FromImage(output))
            {
                graphics.Clear(Color.Transparent);
                graphics.CompositingMode = CompositingMode.SourceCopy;
                graphics.InterpolationMode = InterpolationMode.NearestNeighbor;
                graphics.PixelOffsetMode = PixelOffsetMode.Half;

                for (var index = 0; index < FrameCount; index += 1)
                {
                    var sourceBounds = bounds[index];
                    var width = Math.Max(1, (int)Math.Round(sourceBounds.Width * scale));
                    var height = Math.Max(1, (int)Math.Round(sourceBounds.Height * scale));
                    var x = index * FrameWidth + (FrameWidth - width) / 2;
                    var y = 552 - height;
                    graphics.DrawImage(
                        source,
                        new Rectangle(x, y, width, height),
                        sourceBounds,
                        GraphicsUnit.Pixel
                    );
                }

                var directory = Path.GetDirectoryName(outputPath);
                if (!String.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                output.Save(outputPath, ImageFormat.Png);
            }
        }
    }

    private static Bitmap ToArgb(Bitmap original)
    {
        var copy = new Bitmap(original.Width, original.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(copy))
        {
            graphics.CompositingMode = CompositingMode.SourceCopy;
            graphics.DrawImageUnscaled(original, 0, 0);
        }
        return copy;
    }

    private static Rectangle[] FindFrameBounds(Bitmap source)
    {
        var result = new Rectangle[FrameCount];
        var data = source.LockBits(
            new Rectangle(0, 0, source.Width, source.Height),
            ImageLockMode.ReadOnly,
            PixelFormat.Format32bppArgb
        );

        try
        {
            var rowSize = Math.Abs(data.Stride);
            var pixels = new byte[rowSize * source.Height];
            Marshal.Copy(data.Scan0, pixels, 0, pixels.Length);

            for (var frame = 0; frame < FrameCount; frame += 1)
            {
                var startX = frame * source.Width / FrameCount;
                var endX = (frame + 1) * source.Width / FrameCount;
                var minX = endX;
                var minY = source.Height;
                var maxX = startX - 1;
                var maxY = -1;

                for (var y = 0; y < source.Height; y += 1)
                {
                    var row = data.Stride >= 0 ? y * rowSize : (source.Height - 1 - y) * rowSize;
                    for (var x = startX; x < endX; x += 1)
                    {
                        if (pixels[row + x * 4 + 3] <= AlphaThreshold) continue;
                        minX = Math.Min(minX, x);
                        maxX = Math.Max(maxX, x);
                        minY = Math.Min(minY, y);
                        maxY = Math.Max(maxY, y);
                    }
                }

                if (maxX < minX || maxY < minY)
                    throw new InvalidDataException("Frame " + frame + " has no visible pixels.");

                result[frame] = Rectangle.FromLTRB(minX, minY, maxX + 1, maxY + 1);
            }
        }
        finally
        {
            source.UnlockBits(data);
        }

        return result;
    }
}
'@ -ReferencedAssemblies @("System.Drawing")
}

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
[DogSpriteNormalizer]::Normalize($resolvedInput, $resolvedOutput)
Write-Output "Normalized $resolvedOutput"
