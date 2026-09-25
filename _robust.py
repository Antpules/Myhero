"""Temporary probe: test robust recognisers for the stone page / panel states."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from maa.controller import AdbController
from maa.pipeline import JOCR, JTemplateMatch
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

FRAME = ctrl.post_screencap().wait().get()
Image.fromarray(FRAME[:, :, ::-1]).save(WORK / "robust_now.png")


def tmpl(template, roi, threshold):
    x, y, w, h = roi
    arr = FRAME[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch", JTemplateMatch(template=[template], roi=(0, 0, w, h), threshold=threshold), arr
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            return n.recognition.hit, n.recognition.box
    return False, None


def score(template, roi):
    x, y, w, h = roi
    arr = FRAME[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch", JTemplateMatch(template=[template], roi=(0, 0, w, h), threshold=0.1), arr
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            res = n.recognition.all_results
            return [(round(float(getattr(r, "score", 0)), 3), getattr(r, "box", None)) for r in res[:3]]
    return None


def ocr(box, threshold=0.1):
    x, y, w, h = box
    arr = FRAME[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "OCR", JOCR(roi=(0, 0, w, h), threshold=threshold, only_rec=True, order_by="Horizontal"), arr
    )
    job.wait()
    task = job.get()
    if task:
        for n in task.nodes:
            if n.recognition is not None:
                return [
                    (getattr(r, "text", "?"), round(float(getattr(r, "score", 0.0)), 3))
                    for r in n.recognition.all_results
                ]
    return "NO-DETAIL"


if __name__ == "__main__":
    print("== existing slot template ==")
    print("  (940,550,320,130) t0.8:", tmpl("混沌千域/石板奖励槽.png", (940, 550, 320, 130), 0.8))
    print("  best scores:", score("混沌千域/石板奖励槽.png", (940, 550, 320, 130)))

    print("== 石板奖励 OCR ==")
    for box in [(950, 425, 240, 32), (955, 428, 220, 28), (960, 426, 260, 30)]:
        print(f"  {box}: {ocr(box)}")

    print("== 前往 button template ==")
    for box in [(1040, 575, 200, 60), (1020, 570, 240, 70)]:
        print(f"  {box}:", tmpl("混沌千域/前往按钮.png", box, 0.8), score("混沌千域/前往按钮.png", box))
