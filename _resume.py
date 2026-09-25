"""Temporary probe: verify the scan resumes instead of restarting."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from maa.controller import AdbController
from maa.pipeline import JOCR
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import stone_selector  # noqa: E402
from stone_selector import StoneSelector  # noqa: E402

stone_selector.DEBUG = True

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


class Wrapper:
    def run_recognition(self, entry, image, override=None):
        node = (override or {}).get(entry)
        if node is None:
            return None
        roi = node["roi"]
        j = tasker.post_recognition(
            "OCR",
            JOCR(
                roi=(roi[0], roi[1], roi[2], roi[3]),
                threshold=node.get("threshold", 0.1),
                only_rec=node.get("only_rec", True),
                order_by="Horizontal",
            ),
            image,
        )
        j.wait()
        task = j.get()
        if not task:
            return None
        for n in task.nodes:
            if n.recognition is not None:
                return n.recognition
        return None


if __name__ == "__main__":
    frame = ctrl.post_screencap().wait().get()
    Image.fromarray(frame[:, :, ::-1]).save(WORK / "resume_before.png")
    selector = StoneSelector(
        context=Wrapper(), controller=ctrl, log=lambda m, lv: print(f"  [{lv}] {m}")
    )
    report = selector.select()
    print("RESULT:", report.names)
    print("scans:", report.scans, "drags:", report.drags)
    frame = ctrl.post_screencap().wait().get()
    Image.fromarray(frame[:, :, ::-1]).save(WORK / "resume_after.png")
