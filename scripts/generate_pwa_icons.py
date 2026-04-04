#!/usr/bin/env python3
"""Generate PWA icons for IBKR Options Analyzer.

Creates all required icon sizes from a source image, or generates
branded placeholder icons using Pillow.

Usage:
    # From a source image:
    python scripts/generate_pwa_icons.py path/to/source.png

    # Generate placeholder icons (no source image):
    python scripts/generate_pwa_icons.py --placeholder

Requires: pip install Pillow
"""

import argparse
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is required: pip install Pillow")
    sys.exit(1)

ICON_SIZES = {
    "icon-72x72.png": 72,
    "icon-96x96.png": 96,
    "icon-128x128.png": 128,
    "icon-144x144.png": 144,
    "icon-152x152.png": 152,
    "icon-192x192.png": 192,
    "icon-384x384.png": 384,
    "icon-512x512.png": 512,
    "apple-touch-icon.png": 180,
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "dashboard", "assets", "icons")

# Brand colors from tokens.py
BG_COLOR = "#0f0f1a"
ACCENT_COLOR = "#64ffda"


def generate_placeholder(size: int) -> Image.Image:
    """Generate a branded placeholder icon."""
    img = Image.new("RGBA", (size, size), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Draw a circle accent ring
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        outline=ACCENT_COLOR,
        width=max(2, size // 40),
    )

    # Draw "IB" text in the center
    font_size = size // 3
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    text = "IB"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), text, fill=ACCENT_COLOR, font=font)

    return img


def resize_source(source_path: str, size: int) -> Image.Image:
    """Resize a source image to the target size."""
    img = Image.open(source_path).convert("RGBA")
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description="Generate PWA icons")
    parser.add_argument("source", nargs="?", help="Path to source icon image")
    parser.add_argument("--placeholder", action="store_true", help="Generate placeholder icons")
    args = parser.parse_args()

    if not args.source and not args.placeholder:
        parser.print_help()
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for filename, size in ICON_SIZES.items():
        out_path = os.path.join(OUTPUT_DIR, filename)
        if args.placeholder:
            img = generate_placeholder(size)
        else:
            img = resize_source(args.source, size)
        img.save(out_path, "PNG")
        print(f"  Created {filename} ({size}x{size})")

    print(f"\nAll icons written to {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
