"""Temporary probe: verify the stone-page anchor does not false-match."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

from PIL import Image
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

ANCHOR = "混沌千域/石板界面标志.png"
SLOT = "混沌千域/石板奖励槽.png"
SLOT_FULL = "混沌千域/石板奖励槽_已放置.png"


def score(template, roi, frame):
    x, y, w, h = roi
    arr = frame[y : y + h, x : x + w].copy()
    job = tasker.post_recognition(
        "TemplateMatch", JTemplateMatch(template=template if isinstance(template, list) else [template],
                                        roi=(0, 0, w, h), threshold=0.1), arr
    )
    job.wait()
    task = job.get()
    for n in (task.nodes if task else []):
        if n.recognition is not None:
            res = n.recognition.all_results
            if res:
                return round(float(getattr(res[0], "score", 0)), 3)
    return None


def report(tag):
    f = ctrl.post_screencap().wait().get()
    Image.fromarray(f[:, :, ::-1]).save(WORK / f"anc_{tag}.png")
    print(
        f"{tag}: anchor={score(ANCHOR, (430, 100, 420, 70), f)} "
        f"slot_empty={score(SLOT, (940, 545, 320, 130), f)} "
        f"slot_full={score(SLOT_FULL, (940, 545, 320, 130), f)}"
    )


if __name__ == "__main__":
    report("stone_page")
    # go back to the carnival panel (click the back arrow only once)
    ctrl.post_click(38, 40).wait()
    time.sleep(2.0)
    report("carnival_panel")
    # back to the map
    ctrl.post_click(38, 40).wait()
    time.sleep(2.0)
    report("map")
