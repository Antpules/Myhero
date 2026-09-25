"""Temporary probe: find an invariant stone-page anchor (3 states to compare)."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw
from maa.controller import AdbController
from maa.pipeline import JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
WORK = ROOT / "_work"
WORK.mkdir(exist_ok=True)
Toolkit.init_option(ROOT)

resource = Resource()
resource.post_bundle(ROOT / "resource").wait()
dev = Toolkit.find_adb_devices()[0]
ctrl = AdbController(
    adb_path=dev.adb_path,
    address=dev.address,
    screencap_methods=dev.screencap_methods,
    input_methods=dev.input_methods,
    config=dev.config,
)
ctrl.post_connection().wait()
tasker = Tasker()
tasker.bind(resource, ctrl)

# candidate anchors on the stone page
CANDIDATES = {
    "center_top": (430, 100, 420, 70),      # 石板图标 + 计数
    "effect_bar": (270, 196, 740, 40),      # “石板效果”横条
    "reward_bar": (270, 330, 740, 40),      # “奖励预览”横条
    "tile_bar": (40, 585, 840, 90),         # 底部石板条
}


def score(template, roi, frame):
    x, y, w, h = roi
    arr = frame[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch", JTemplateMatch(template=[template], roi=(0, 0, w, h), threshold=0.1), arr
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            res = n.recognition.all_results
            if res:
                return round(float(getattr(res[0], "score", 0)), 3)
    return None


if __name__ == "__main__":
    shots = []
    f = ctrl.post_screencap().wait().get()
    Image.fromarray(f[:, :, ::-1]).save(WORK / "anchor_a.png")
    shots.append(("stateA", f))

    # switch to another tile to change the center panel contents
    ctrl.post_click(421, 631).wait()
    time.sleep(1.2)
    f2 = ctrl.post_screencap().wait().get()
    Image.fromarray(f2[:, :, ::-1]).save(WORK / "anchor_b.png")
    shots.append(("stateB", f2))

    # a third state: another tile
    ctrl.post_click(637, 631).wait()
    time.sleep(1.2)
    f3 = ctrl.post_screencap().wait().get()
    Image.fromarray(f3[:, :, ::-1]).save(WORK / "anchor_c.png")
    shots.append(("stateC", f3))

    # crop candidate templates from state A
    for name, box in CANDIDATES.items():
        x, y, w, h = box
        tpl_path = WORK / f"tpl_{name}.png"
        Image.fromarray(shots[0][1][y : y + h, x : x + w][:, :, ::-1]).save(tpl_path)
        line = [f"{name} ({w}x{h})"]
        for label, frame in shots:
            line.append(f"{label}={score(str(tpl_path), box, frame)}")
        print("  ".join(line))
