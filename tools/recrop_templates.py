from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "图片"
OUTPUT = ROOT / "resource" / "image" / "混沌千域"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    crops = [
        ("混沌千域大地图.png", "混沌千域标题.png", (82, 18, 242, 78)),
        ("混沌千域大地图.png", "嘉年华入口.png", (946, 350, 1077, 405)),
        ("嘉年华挑战.png", "嘉年华面板标题.png", (967, 8, 1202, 69)),
        # 使用石板详情卡片中固定的“石板效果”标题条判断是否已经展开。
        # 旧模板裁到了地图背景，弹窗覆盖地图时仍会以 0.98 的高分误命中。
        ("石板选择界面.png", "石板界面标志.png", (326, 234, 638, 272)),
    ]

    for source_name, output_name, box in crops:
        with Image.open(SOURCE / source_name) as image:
            if image.size != (1280, 720):
                raise ValueError(f"{source_name} 应为 1280x720，实际为 {image.size}")
            image.crop(box).save(OUTPUT / output_name)


if __name__ == "__main__":
    main()
