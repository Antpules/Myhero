"""拉吉酱次元口袋自动分解流程。"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from battle_runner import normalized_match


REFERENCE_SIZE = (1280, 720)
ROUNDS = 3

ONE_KEY_DECOMPOSE = (828, 660)
FILTER_CONFIRM = (1132, 660)
POCKET_CLOSE = (1234, 49)


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


ASSET_DIR = _bundle_root() / "resource" / "image" / "混沌千域"


def _load(name: str) -> np.ndarray:
    return np.asarray(Image.open(ASSET_DIR / name).convert("RGB"))


class DecomposeRunner:
    """识别拉吉酱入口，并连续完成三轮装备分解。"""

    def __init__(
        self,
        controller: Any,
        log: Callable[[str, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        rounds: int = ROUNDS,
    ) -> None:
        self.controller = controller
        self.log = log or (lambda message, level: None)
        self.should_stop = should_stop or (lambda: False)
        self.rounds = rounds
        self.entrance = _load("拉吉酱入口.png")
        self.pocket_title = _load("拉吉酱口袋标题.png")
        self.filter_title = _load("分解筛选标题.png")
        self.selected_marker = _load("分解已选择标志.png")
        self.selection_confirm = _load("分解左侧确定.png")
        self.reward_title = _load("分解奖励标题.png")
        self.reward_confirm = _load("分解奖励确定.png")
        self.map_title = _load("混沌千域标题.png")

    def screenshot(self) -> np.ndarray:
        return self.controller.post_screencap().wait().get()

    def click(self, point: tuple[int, int]) -> None:
        self.controller.post_click(*point).wait()

    @staticmethod
    def _match(
        frame: np.ndarray,
        template: np.ndarray,
        roi: tuple[int, int, int, int],
        threshold: float,
    ) -> tuple[bool, tuple[int, int], float]:
        score, center = normalized_match(frame, template, roi)
        return score >= threshold, center, score

    def _wait_match(
        self,
        label: str,
        template: np.ndarray,
        roi: tuple[int, int, int, int],
        threshold: float = 0.78,
        timeout: float = 12.0,
    ) -> tuple[int, int] | None:
        deadline = time.monotonic() + timeout
        best = -1.0
        while time.monotonic() < deadline and not self.should_stop():
            frame = self.screenshot()
            hit, center, score = self._match(frame, template, roi, threshold)
            best = max(best, score)
            if hit:
                return center
            time.sleep(0.35)
        if not self.should_stop():
            self.log(f"等待{label}超时（最高匹配度 {best:.1%}）", "error")
        return None

    def _drain_rewards(self, round_index: int) -> bool:
        """持续关闭奖励弹窗；兼容截图中的大窗和后续小窗。"""
        if self._wait_match(
            "分解奖励弹窗",
            self.reward_title,
            (350, 50, 600, 350),
            threshold=0.78,
            timeout=12.0,
        ) is None:
            return False

        clicked = 0
        clear_streak = 0
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline and not self.should_stop():
            frame = self.screenshot()
            has_reward, _, _ = self._match(
                frame, self.reward_title, (350, 50, 600, 350), 0.78
            )
            if not has_reward:
                clear_streak += 1
                if clear_streak >= 4:
                    self.log(
                        f"第 {round_index}/{self.rounds} 轮奖励已全部确认"
                        f"（关闭 {clicked} 个弹窗）",
                        "ok",
                    )
                    return True
                time.sleep(0.4)
                continue

            clear_streak = 0
            hit, center, score = self._match(
                frame, self.reward_confirm, (350, 350, 600, 340), 0.78
            )
            if not hit:
                self.log(f"已识别奖励弹窗，但未找到确定按钮（匹配度 {score:.1%}）", "warn")
                time.sleep(0.4)
                continue
            self.click(center)
            clicked += 1
            self.log(f"已确认第 {clicked} 个奖励弹窗", "info")
            time.sleep(0.6)

        if not self.should_stop():
            self.log("确认分解奖励弹窗超时", "error")
        return False

    def _wait_selection_result(self, timeout: float = 10.0) -> tuple[str, tuple[int, int] | None]:
        """等待左侧确定按钮；口袋界面稳定但按钮缺失时判定没有可分解装备。"""
        started = time.monotonic()
        deadline = started + timeout
        empty_streak = 0
        best = -1.0
        while time.monotonic() < deadline and not self.should_stop():
            frame = self.screenshot()
            ready, center, score = self._match(
                frame, self.selection_confirm, (150, 580, 500, 140), 0.78
            )
            best = max(best, score)
            if ready:
                return "ready", center

            # 给筛选面板关闭和装备入栏动画留出时间，再连续确认空状态。
            pocket, _, _ = self._match(frame, self.pocket_title, (0, 0, 500, 120), 0.78)
            filter_open, _, _ = self._match(
                frame, self.filter_title, (650, 0, 630, 150), 0.78
            )
            if time.monotonic() - started >= 1.5 and pocket and not filter_open:
                empty_streak += 1
                if empty_streak >= 4:
                    return "empty", None
            else:
                empty_streak = 0
            time.sleep(0.35)

        if not self.should_stop():
            self.log(f"等待左侧分解确定按钮超时（最高匹配度 {best:.1%}）", "error")
        return "failed", None

    def _run_round(self, round_index: int) -> bool | None:
        """执行一轮；``None`` 表示没有满足条件的装备，应正常结束整个流程。"""
        self.log(f"开始第 {round_index}/{self.rounds} 轮自动分解", "info")
        self.click(ONE_KEY_DECOMPOSE)

        if self._wait_match(
            "分解筛选面板", self.filter_title, (650, 0, 630, 150)
        ) is None:
            return False
        self.click(FILTER_CONFIRM)
        self.log("已确认分解筛选条件", "info")

        selection_state, selection_center = self._wait_selection_result()
        if selection_state == "empty":
            self.log("分解界面左侧没有确定按钮，无满足条件的装备，退出分解流程", "warn")
            return None
        if selection_state != "ready" or selection_center is None:
            return False
        self.click(selection_center)
        self.log("已点击左侧分解确定按钮", "info")
        return self._drain_rewards(round_index)

    def _return_to_map(self) -> bool:
        self.click(POCKET_CLOSE)
        self.log("自动分解结束，正在关闭次元口袋", "info")
        if self._wait_match(
            "千域大地图", self.map_title, (0, 0, 330, 130), threshold=0.72, timeout=15.0
        ) is None:
            return False
        self.log("已返回千域大地图", "ok")
        return True

    def run(self) -> bool:
        self.log("正在千域大地图识别拉吉酱入口", "info")
        entrance_center = self._wait_match(
            "拉吉酱入口", self.entrance, (0, 0, *REFERENCE_SIZE), threshold=0.72, timeout=15.0
        )
        if entrance_center is None:
            return False
        self.click(entrance_center)
        self.log("已识别并点击拉吉酱入口", "ok")

        if self._wait_match(
            "拉吉酱次元口袋", self.pocket_title, (0, 0, 500, 120), timeout=15.0
        ) is None:
            return False

        for round_index in range(1, self.rounds + 1):
            if self.should_stop():
                return False
            result = self._run_round(round_index)
            if result is None:
                self.log(
                    f"自动分解提前结束：完成 {round_index - 1} 轮后已无满足条件的装备",
                    "ok",
                )
                return self._return_to_map()
            if not result:
                return False
        self.log(f"自动分解完成，共执行 {self.rounds} 次一键分解", "ok")
        return self._return_to_map()
