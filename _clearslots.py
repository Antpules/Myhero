"""Temporary probe: clear the reward panel via the three slots."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

from maa.controller import AdbController
from maa.pipeline import JOCR
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

from stone_selector import ADD_BUTTON, SLOT_ROIS, TITLE_ROI

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


def frame():
    return ctrl.post_screencap().wait().get()


def ocr(box, f):
    x, y, w, h = box
    arr = f[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "OCR", JOCR(roi=(0, 0, w, h), threshold=0.1, only_rec=True, order_by="Horizontal"), arr
    )
    job.wait()
    task = job.get()
    if task:
        for n in task.nodes:
            if n.recognition is not None:
                res = n.recognition.all_results
                return getattr(res[0], "text", "") if res else ""
    return ""


if __name__ == "__main__":
    for i, slot in enumerate(SLOT_ROIS):
        x, y, w, h = slot
        ctrl.post_click(x + w // 2, y + h // 2).wait()
        time.sleep(1.2)
        f = frame()
        title = ocr(TITLE_ROI, f)
        btn = ocr(ADD_BUTTON, f)
        print(f"slot{i + 1}: title={title!r} btn={btn!r}")
        if btn == "取消":
            ctrl.post_click(
                ADD_BUTTON[0] + ADD_BUTTON[2] // 2, ADD_BUTTON[1] + ADD_BUTTON[3] // 2
            ).wait()
            time.sleep(1.3)
    print("after clear, btn:", ocr(ADD_BUTTON, frame()))
