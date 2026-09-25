"""Temporary probe: run the stone pipeline outside the UI with node details."""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from maa.controller import AdbController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from stone_selector import StoneSelector  # noqa: E402

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "_work"
WORK.mkdir(exist_ok=True)
Toolkit.init_option(ROOT)


class SelectStonesAction(CustomAction):
    def run(self, context, argv):
        selector = StoneSelector(
            context=context,
            controller=context.tasker.controller,
            log=lambda m, lv: print(f"  [{lv}] {m}"),
        )
        report = selector.select()
        print("  RESULT:", report.names)
        return bool(report.ok)


resource = Resource()
resource.post_bundle(ROOT / "resource").wait()
print("loaded:", resource.loaded, "nodes:", len(resource.node_list))
resource.register_custom_action("SelectStones", SelectStonesAction())

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
print("bind:", tasker.bind(resource, ctrl), "inited:", tasker.inited)

if __name__ == "__main__":
    entry = sys.argv[1] if len(sys.argv) > 1 else "选择石板并前往"
    frame = ctrl.post_screencap().wait().get()
    Image.fromarray(frame[:, :, ::-1]).save(WORK / "pl_before.png")
    job = tasker.post_task(entry)
    job.wait()
    detail = job.get()
    print("status:", detail.status if detail else None)
    for node in (detail.nodes if detail else []):
        print(f"  node={node.name!r} completed={node.completed}")
    frame = ctrl.post_screencap().wait().get()
    Image.fromarray(frame[:, :, ::-1]).save(WORK / "pl_after.png")
