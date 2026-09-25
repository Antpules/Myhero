"""Temporary helper: run one real task through the app UI and capture it."""
from __future__ import annotations

import io
import sys

import app as appmod

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TASK_LABEL = sys.argv[1] if len(sys.argv) > 1 else "选择三个石板"
OUT = sys.argv[2] if len(sys.argv) > 2 else "resume"


def run() -> None:
    root = appmod.App()
    root.geometry("1080x780+30+20")
    root.update_idletasks()
    root.update()

    import ctypes
    from ctypes import wintypes

    from PIL import ImageGrab

    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

    def snap(tag: str) -> None:
        root.update_idletasks()
        root.update()
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        full = ImageGrab.grab()
        scale = full.width / root.winfo_screenwidth()
        box = tuple(
            int(v * scale) for v in (rect.left, rect.top, rect.right, rect.bottom)
        )
        full.crop(box).save(f"{OUT}-{tag}.png")
        print("snap", tag, "| status:", root.status_label.cget("text"))

    def begin() -> None:
        if not root.devices:
            root.after(1500, begin)
            return
        labels = [label for label, _ in appmod.TASKS]
        root.task_combo.current(labels.index(TASK_LABEL))
        root._sync_task_hint()
        root.start_task()
        snap("running")

    def poll() -> None:
        if root.runner.running:
            root.after(1000, poll)
        else:
            snap("done")
            root.destroy()

    root.after(1800, begin)
    root.after(4000, poll)
    root.mainloop()


if __name__ == "__main__":
    run()
