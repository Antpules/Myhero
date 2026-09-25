"""Temporary probe: report the current screen, then click back to the map."""
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


def match(template, roi, threshold=0.8):
    f = ctrl.post_screencap().wait().get()
    x, y, w, h = roi
    arr = f[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch", JTemplateMatch(template=[template], roi=(0, 0, w, h), threshold=threshold), arr
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            return n.recognition.hit
    return False


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "state"
    for i in range(4):
        slot = match("混沌千域/石板奖励槽.png", (940, 550, 320, 130))
        panel = match("混沌千域/嘉年华面板标题.png", (880, 0, 400, 140), 0.7)
        print(f"step{i}: slot_visible={slot} carnival_panel={panel}")
        if step == "state" or not (slot or panel):
            break
        ctrl.post_click(38, 40).wait()  # back arrow
        time.sleep(2.0)
