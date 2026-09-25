"""Temporary probe: close dialogs and return to the chaos map."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from maa.controller import AdbController
from maa.pipeline import JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

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


def score(template, roi):
    f = ctrl.post_screencap().wait().get()
    x, y, w, h = roi
    arr = f[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch",
        JTemplateMatch(template=template if isinstance(template, list) else [template],
                       roi=(0, 0, w, h), threshold=0.1),
        arr,
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            res = n.recognition.all_results
            if res:
                return round(float(getattr(res[0], "score", 0)), 3)
    return None


SLOTS = ["混沌千域/石板奖励槽.png", "混沌千域/石板奖励槽_已放置.png"]


def state():
    f = ctrl.post_screencap().wait().get()
    return {
        "anchor": score("混沌千域/石板界面标志.png", (430, 100, 420, 70)),
        "slot": score(SLOTS, (940, 545, 320, 130)),
        "map_title": score("混沌千域/混沌千域标题.png", (0, 0, 400, 160)),
        "panel": score("混沌千域/嘉年华面板标题.png", (880, 0, 400, 140)),
    }


if __name__ == "__main__":
    for i in range(6):
        st = state()
        ctrl.post_screencap().wait().get()
        import numpy as np
        from PIL import Image

        Image.fromarray(ctrl.post_screencap().wait().get()[:, :, ::-1]).save(WORK / f"reset_{i}.png")
        print(f"step{i}: {st}")
        if st["anchor"] is None and st["slot"] is None and st["map_title"] and st["map_title"] > 0.82:
            print("on map, done")
            break
        ctrl.post_click(38, 40).wait()  # back
        time.sleep(2.0)
