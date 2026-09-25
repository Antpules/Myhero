"""从原始 1280×720 截图生成嘉年华战斗识别模板。"""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "图片"
OUTPUT = ROOT / "resource" / "image" / "混沌千域"


TEMPLATES = {
    "战斗目标_1.png": ("战斗场景1.png", (20, 151, 258, 187)),
    "战斗目标_2.png": ("战斗场景2.png", (20, 151, 258, 187)),
    "战斗目标_3.png": ("战斗场景3.png", (20, 151, 258, 187)),
    "战斗目标_4.png": ("战斗场景4.png", (20, 151, 258, 187)),
    "战斗目标_5.png": ("战斗场景5.png", (20, 151, 258, 187)),
    "战斗目标_6.png": ("战斗场景6.png", (20, 151, 258, 187)),
    "战斗目标_7.png": ("战斗场景7.png", (20, 151, 258, 187)),
    "Boss倒计时.png": ("boss战.png", (20, 151, 264, 186)),
    "Boss出口.png": ("boss战结算.png", (1045, 108, 1142, 215)),
    "退出副本.png": ("结算界面.png", (548, 607, 733, 680)),
    "玩家死亡复活币.png": ("战斗死亡.png", (77, 50, 124, 91)),
    "复活确定.png": ("复活确认.png", (683, 449, 857, 512)),
}


def build() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for output_name, (source_name, box) in TEMPLATES.items():
        with Image.open(SOURCE / source_name) as image:
            image.convert("RGB").crop(box).save(OUTPUT / output_name)


if __name__ == "__main__":
    build()
