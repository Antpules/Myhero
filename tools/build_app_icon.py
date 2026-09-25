"""把用户提供的像素图生成 Tk PNG 与 Windows 多尺寸 ICO。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "图片" / "软件图标原图.png"
OUTPUT_PNG = ROOT / "resource" / "app_icon.png"
OUTPUT_ICO = ROOT / "resource" / "app_icon.ico"


def build() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    side = max(source.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(source, ((side - source.width) // 2, (side - source.height) // 2))

    display = square.resize((256, 256), Image.Resampling.NEAREST)
    display.save(OUTPUT_PNG)
    display.save(
        OUTPUT_ICO,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    build()
