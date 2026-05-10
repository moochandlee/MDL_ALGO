#!/usr/bin/env python3
"""
generate_icons.py — Creates placeholder PWA icons using PIL.
Run once after install: python generate_icons.py
"""
import os
from pathlib import Path

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

try:
    from PIL import Image, ImageDraw, ImageFont

    for size in (192, 512):
        img  = Image.new("RGBA", (size, size), "#0a0f1e")
        draw = ImageDraw.Draw(img)
        # Simple chart icon
        margin  = size // 6
        bar_w   = (size - margin * 2) // 5
        heights = [0.3, 0.6, 0.45, 0.8, 0.55]
        for i, h in enumerate(heights):
            x0 = margin + i * bar_w + 4
            x1 = x0 + bar_w - 8
            y1 = size - margin
            y0 = int(size - margin - h * (size - 2 * margin))
            draw.rectangle([x0, y0, x1, y1], fill="#4fc3f7")
        img.save(static_dir / f"icon-{size}.png")
    print("Icons generated.")
except ImportError:
    # PIL not available — create minimal valid 1×1 PNGs as fallback
    import base64
    # Minimal 1×1 transparent PNG
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    for size in (192, 512):
        (static_dir / f"icon-{size}.png").write_bytes(png_1x1)
    print("Fallback icons written (install Pillow for real icons: pip install Pillow)")

print(f"Icons in: {static_dir}")
