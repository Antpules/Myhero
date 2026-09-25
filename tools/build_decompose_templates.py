"""从自动分解流程截图生成 Maa/自定义识别使用的小模板。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "图片"
TARGET = ROOT / "resource" / "image" / "混沌千域"


def crop(source: str, box: tuple[int, int, int, int], target: str) -> None:
    image = Image.open(SOURCE / source).convert("RGB")
    TARGET.mkdir(parents=True, exist_ok=True)
    image.crop(box).save(TARGET / target)


def main() -> None:
    # 图 1 已经是完整入口图标，不再裁剪。
    Image.open(SOURCE / "拉吉酱入口原图.png").convert("RGB").save(
        TARGET / "拉吉酱入口.png"
    )
    crop("自动分解_口袋.png", (24, 18, 320, 66), "拉吉酱口袋标题.png")
    crop("自动分解_筛选.png", (741, 18, 1260, 58), "分解筛选标题.png")
    crop("自动分解_已选择.png", (1010, 628, 1190, 692), "分解已选择标志.png")
    crop("自动分解_已选择.png", (305, 628, 480, 692), "分解左侧确定.png")
    crop("自动分解_奖励小窗.png", (582, 264, 701, 302), "分解奖励标题.png")
    crop("自动分解_奖励小窗.png", (552, 431, 725, 493), "分解奖励确定.png")


if __name__ == "__main__":
    main()
