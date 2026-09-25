"""Temporary probe: score candidate 'stone page' recognisers."""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from maa.controller import AdbController
from maa.pipeline import JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
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
FRAME = ctrl.post_screencap().wait().get()


def best(template, roi):
    x, y, w, h = roi
    arr = FRAME[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch", JTemplateMatch(template=[template], roi=(0, 0, w, h), threshold=0.1), arr
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            return [
                (round(float(getattr(r, "score", 0)), 3), getattr(r, "box", None))
                for r in n.recognition.all_results[:2]
            ]
    return None


if __name__ == "__main__":
    print("button template (stone page only):")
    for roi in [(400, 480, 200, 100), (380, 470, 260, 120)]:
        print(f"  roi{roi}:", best("混沌千域/石板操作按钮.png", roi))
    print("slot template (exists only when a slot is empty):")
    for roi in [(940, 550, 320, 130)]:
        print(f"  roi{roi}:", best("混沌千域/石板奖励槽.png", roi))
