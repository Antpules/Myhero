"""嘉年华战斗控制：状态识别、固定巡逻走位与虚拟摇杆移动。"""

from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, binary_fill_holes
from scipy.signal import fftconvolve


REFERENCE_SIZE = (1280, 720)
JOYSTICK = (205, 555)
PLAYER = (640, 360)
# 智能施法按钮：既用于点击，也作为开启状态的检测中心。
SMART_CAST = (1240, 516)
PLAYER_AVATAR = (101, 70)
SMART_CAST_RADIUS = 40
SMART_CAST_CYAN_RATIO = 0.05
PLAYFIELD = (250, 20, 1020, 700)
CELL = 20

ENTER_TIMEOUT = 90.0
# 先随机八向移动 RANDOM_WALK_SECONDS 秒（每次 RANDOM_STEP_SECONDS 秒），
# 再顺时针、逆时针各走一遍八向，随后重新开始随机阶段。
RANDOM_WALK_SECONDS = 10.0
RANDOM_STEP_SECONDS = 1.0
EIGHT_WAY_SECONDS = 1.0
SMART_CAST_CHECK_DELAY = 5.0
STONE_SMART_CAST_START_DELAY = 1.0
STONE_SMART_CAST_CLICK_COUNT = 2
STONE_SMART_CAST_CLICK_INTERVAL = 1.0
RUN_TIMEOUT = 15 * 60.0
SETTLEMENT_TIMEOUT = 45.0

def _bundle_root() -> Path:
    """源码运行时取仓库根目录，打包后取 PyInstaller 的资源解包目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


ASSET_DIR = _bundle_root() / "resource" / "image" / "混沌千域"

DIAGONAL = 1.0 / math.sqrt(2.0)
# 屏幕上（y 轴向下）的顺时针八向顺序：上、右上、右、右下、下、左下、左、左上。
EIGHT_DIRECTIONS: tuple[tuple[float, float], ...] = (
    (0.0, -1.0),
    (DIAGONAL, -DIAGONAL),
    (1.0, 0.0),
    (DIAGONAL, DIAGONAL),
    (0.0, 1.0),
    (-DIAGONAL, DIAGONAL),
    (-1.0, 0.0),
    (-DIAGONAL, -DIAGONAL),
)


def _gray(image: np.ndarray) -> np.ndarray:
    """BGR/RGB 均可用的亮度图；模板和截图使用同一公式即可。"""
    return image[..., :3].astype(np.float32).mean(axis=2)


def _load(name: str) -> np.ndarray:
    return np.asarray(Image.open(ASSET_DIR / name).convert("RGB"))


def normalized_match(
    image: np.ndarray,
    template: np.ndarray,
    roi: tuple[int, int, int, int],
    scale: float = 0.5,
) -> tuple[float, tuple[int, int]]:
    """在 ROI 内做归一化相关匹配，返回分数和模板中心坐标。"""
    x, y, w, h = roi
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        return -1.0, (0, 0)

    # Maa 截图是 BGR、Pillow 模板是 RGB；通道均值可消除排列差异。
    source = Image.fromarray(_gray(crop).astype(np.uint8), mode="L")
    target = Image.fromarray(_gray(template).astype(np.uint8), mode="L")
    if scale != 1.0:
        source = source.resize(
            (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
            Image.Resampling.BILINEAR,
        )
        target = target.resize(
            (max(1, round(target.width * scale)), max(1, round(target.height * scale))),
            Image.Resampling.BILINEAR,
        )

    src = np.asarray(source, dtype=np.float32)
    tpl = np.asarray(target, dtype=np.float32)
    th, tw = tpl.shape
    if src.shape[0] < th or src.shape[1] < tw:
        return -1.0, (0, 0)

    tpl -= float(tpl.mean())
    tpl_energy = float(np.square(tpl).sum())
    if tpl_energy < 1.0:
        return -1.0, (0, 0)

    kernel = np.ones((th, tw), dtype=np.float32)
    count = float(th * tw)
    cross = fftconvolve(src, tpl[::-1, ::-1], mode="valid")
    sums = fftconvolve(src, kernel, mode="valid")
    sums2 = fftconvolve(np.square(src), kernel, mode="valid")
    variance = np.maximum(sums2 - np.square(sums) / count, 1.0)
    scores = cross / np.sqrt(variance * tpl_energy)
    iy, ix = np.unravel_index(int(np.argmax(scores)), scores.shape)
    score = float(scores[iy, ix])
    cx = x + round((ix + tw / 2) / scale)
    cy = y + round((iy + th / 2) / scale)
    return score, (cx, cy)


def walkable_grid(frame: np.ndarray) -> np.ndarray:
    """把棕色木地板压缩为 20px 网格；特效遮挡用较低占比容错。"""
    rgb = frame[..., :3].astype(np.int16)
    # 截图来自 Maa 时通常为 BGR；棕色的红通道在两种排列下都是两端较大者。
    hi = np.maximum(rgb[..., 0], rgb[..., 2])
    lo = np.minimum(rgb[..., 0], rgb[..., 2])
    green = rgb[..., 1]
    brown = (
        (hi >= 55)
        & (hi <= 180)
        & (green >= 25)
        & (green <= 125)
        & (lo <= 115)
        & (hi >= green + 10)
    )
    x0, y0, x1, y1 = PLAYFIELD
    brown[:y0, :] = False
    brown[y1:, :] = False
    brown[:, :x0] = False
    brown[:, x1:] = False

    gh = math.ceil(frame.shape[0] / CELL)
    gw = math.ceil(frame.shape[1] / CELL)
    grid = np.zeros((gh, gw), dtype=bool)
    for gy in range(gh):
        for gx in range(gw):
            block = brown[gy * CELL : (gy + 1) * CELL, gx * CELL : (gx + 1) * CELL]
            grid[gy, gx] = bool(block.size and block.mean() >= 0.22)
    # 技能、角色和掉落物会短暂盖住地板；先合并小裂缝并填洞，边缘跟随只看外轮廓。
    grid = binary_closing(grid, structure=np.ones((3, 3), dtype=bool), iterations=2)
    return np.asarray(binary_fill_holes(grid), dtype=bool)


def _nearest_open(grid: np.ndarray, point: tuple[int, int], radius: int = 8) -> tuple[int, int] | None:
    gx, gy = point[0] // CELL, point[1] // CELL
    best: tuple[int, int] | None = None
    best_dist = 10**9
    for y in range(max(0, gy - radius), min(grid.shape[0], gy + radius + 1)):
        for x in range(max(0, gx - radius), min(grid.shape[1], gx + radius + 1)):
            if not grid[y, x]:
                continue
            dist = (x - gx) ** 2 + (y - gy) ** 2
            if dist < best_dist:
                best = (x, y)
                best_dist = dist
    return best


def smart_cast_enabled(
    frame: np.ndarray,
    center: tuple[int, int] = SMART_CAST,
    red_index: int = 2,
) -> float:
    """返回智能施法按钮圆盘内“亮青色”像素的占比。

    按钮开启时圆盘整圈泛青蓝色高光（绿、蓝都亮且明显高于红），关闭时是暗色
    灰剑图标，因此用圆盘内的青色占比即可判断状态。只统计圆盘内部，避免周围
    技能特效干扰。MaaFramework 的截图是 BGR（`red_index=2`），Pillow 读出的
    PNG 是 RGB（`red_index=0`），两种排列下绿通道都在中间。
    """
    x, y = center
    radius = SMART_CAST_RADIUS
    y0, y1 = max(0, y - radius), min(frame.shape[0], y + radius + 1)
    x0, x1 = max(0, x - radius), min(frame.shape[1], x + radius + 1)
    patch = frame[y0:y1, x0:x1, :3].astype(np.int16)
    if patch.size == 0:
        return 0.0

    rows, columns = np.mgrid[0 : patch.shape[0], 0 : patch.shape[1]]
    circle = np.square(rows + y0 - y) + np.square(columns + x0 - x) <= radius * radius
    if not circle.any():
        return 0.0

    red = patch[..., red_index]
    green = patch[..., 1]
    blue = patch[..., 2 - red_index]
    cyan = (
        (green >= 110)
        & (blue >= 110)
        & (green >= red + 30)
        & (blue >= red + 30)
    )
    return float(cyan[circle].mean())


def patrol_sweep(step: int) -> tuple[str, tuple[float, float]] | None:
    """八向巡逻的第 step 步（0 起）：前半圈顺时针、后半圈逆时针，走满一圈返回 None。"""
    total = len(EIGHT_DIRECTIONS)
    if step < 0:
        return None
    if step < total:
        return "顺时针", EIGHT_DIRECTIONS[step]
    if step < 2 * total:
        return "逆时针", EIGHT_DIRECTIONS[2 * total - 1 - step]
    return None


class CarnivalBattleRunner:
    def __init__(
        self,
        controller: Any,
        log: Callable[[str, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        random_walk_seconds: float = RANDOM_WALK_SECONDS,
        smart_cast_start_delay: float = 0.0,
        smart_cast_click_count: int = 1,
        smart_cast_click_interval: float = 0.0,
    ) -> None:
        self.controller = controller
        self.log = log or (lambda message, level: None)
        self.should_stop = should_stop or (lambda: False)
        self.random_walk_seconds = random_walk_seconds
        self.smart_cast_start_delay = max(0.0, smart_cast_start_delay)
        self.smart_cast_click_count = max(1, smart_cast_click_count)
        self.smart_cast_click_interval = max(0.0, smart_cast_click_interval)
        self.target_templates = [_load(f"战斗目标_{index}.png") for index in range(1, 8)]
        self.boss_template = _load("Boss倒计时.png")
        self.exit_template = _load("Boss出口.png")
        self.settlement_template = _load("退出副本.png")
        self.map_template = _load("混沌千域标题.png")
        self.death_template = _load("玩家死亡复活币.png")
        self.revive_confirm_template = _load("复活确定.png")

    def screenshot(self) -> np.ndarray:
        return self.controller.post_screencap().wait().get()

    def click(self, point: tuple[int, int]) -> None:
        self.controller.post_click(*point).wait()

    def _match(
        self,
        frame: np.ndarray,
        template: np.ndarray,
        roi: tuple[int, int, int, int],
        threshold: float,
    ) -> tuple[bool, tuple[int, int], float]:
        score, center = normalized_match(frame, template, roi)
        return score >= threshold, center, score

    def _battle(self, frame: np.ndarray) -> bool:
        return max(
            normalized_match(frame, template, (0, 125, 320, 90))[0]
            for template in self.target_templates
        ) >= 0.72

    def _boss(self, frame: np.ndarray) -> bool:
        return self._match(frame, self.boss_template, (0, 125, 330, 90), 0.72)[0]

    def _boss_exit(self, frame: np.ndarray) -> tuple[bool, tuple[int, int]]:
        hit, center, _ = self._match(frame, self.exit_template, (960, 70, 230, 210), 0.66)
        return hit, center

    def _settlement(self, frame: np.ndarray) -> tuple[bool, tuple[int, int]]:
        hit, center, _ = self._match(
            frame, self.settlement_template, (470, 550, 350, 160), 0.70
        )
        return hit, center

    def smart_cast_open(self, frame: np.ndarray) -> tuple[bool, float]:
        """检测智能施法按钮是否处于开启状态，返回 (是否开启, 青色像素占比)。

        `frame` 为 MaaFramework 截图（BGR），沿用 `smart_cast_enabled` 的默认通道下标。
        """
        ratio = smart_cast_enabled(frame)
        return ratio >= SMART_CAST_CYAN_RATIO, ratio

    def _revive_confirm(self, frame: np.ndarray) -> tuple[bool, tuple[int, int], float]:
        return self._match(
            frame, self.revive_confirm_template, (550, 380, 400, 200), 0.78
        )

    def _handle_revive(self, frame: np.ndarray) -> bool:
        """发现死亡标志后打开复活框并确认；返回是否进入了复活处理。"""
        confirm, center, _ = self._revive_confirm(frame)
        if confirm:
            self.click(center)
            self.log("已点击确定，使用复活币复活", "ok")
            time.sleep(1.0)
            return True

        dead, _, score = self._match(
            frame, self.death_template, (45, 20, 115, 105), 0.80
        )
        if not dead:
            return False

        self.log(f"检测到玩家死亡（复活币标志匹配度 {score:.1%}）", "warn")
        self.click(PLAYER_AVATAR)
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and not self.should_stop():
            frame = self.screenshot()
            confirm, center, _ = self._revive_confirm(frame)
            if confirm:
                self.click(center)
                self.log("已点击确定，使用复活币复活", "ok")
                time.sleep(1.0)
                return True
            time.sleep(0.3)

        if not self.should_stop():
            self.log("已点击玩家头像，但未识别到复活确认框，将继续重试", "warn")
        return True

    def move(self, direction: tuple[float, float], seconds: float = 1.0) -> None:
        if self.should_stop():
            return
        dx, dy = direction
        radius = 64
        end = (round(JOYSTICK[0] + dx * radius), round(JOYSTICK[1] + dy * radius))
        self.controller.post_touch_down(*JOYSTICK).wait()
        self.controller.post_touch_move(*end).wait()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.should_stop():
            time.sleep(max(0.0, min(0.1, deadline - time.monotonic())))
        self.controller.post_touch_up().wait()

    def random_direction(self, frame: np.ndarray) -> tuple[float, float]:
        grid = walkable_grid(frame)
        source = _nearest_open(grid, PLAYER, radius=6)
        if source is not None:
            choices: list[tuple[float, float]] = []
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                probe = (PLAYER[0] + round(math.cos(rad) * 100), PLAYER[1] + round(math.sin(rad) * 100))
                if _nearest_open(grid, probe, radius=1) is not None:
                    choices.append((math.cos(rad), math.sin(rad)))
            if choices:
                return random.choice(choices)
        angle = random.random() * math.tau
        return math.cos(angle), math.sin(angle)

    def _wait_for_map(self, timeout: float = 25.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.should_stop():
            frame = self.screenshot()
            hit, _, _ = self._match(frame, self.map_template, (0, 0, 330, 130), 0.65)
            if hit:
                return True
            time.sleep(1.0)
        return False

    def run(self) -> bool:
        self.log("已点击前往，等待进入战斗场景", "info")
        enter_deadline = time.monotonic() + ENTER_TIMEOUT
        frame: np.ndarray | None = None
        while time.monotonic() < enter_deadline and not self.should_stop():
            frame = self.screenshot()
            if self._battle(frame) or self._boss(frame):
                break
            time.sleep(1.0)
        else:
            self.log("等待战斗场景超时，未识别到“找到并击败BOSS”", "error")
            return False

        if self.smart_cast_start_delay:
            self.log(
                f"本轮已添加石板，进入战斗后延迟"
                f" {self.smart_cast_start_delay:g} 秒点击智能施法",
                "info",
            )
            delay_deadline = time.monotonic() + self.smart_cast_start_delay
            while time.monotonic() < delay_deadline and not self.should_stop():
                time.sleep(max(0.0, min(0.1, delay_deadline - time.monotonic())))
            if self.should_stop():
                self.log("战斗控制已停止", "warn")
                return False

        for click_index in range(self.smart_cast_click_count):
            if click_index:
                click_deadline = time.monotonic() + self.smart_cast_click_interval
                while time.monotonic() < click_deadline and not self.should_stop():
                    time.sleep(max(0.0, min(0.1, click_deadline - time.monotonic())))
                if self.should_stop():
                    self.log("战斗控制已停止", "warn")
                    return False
            self.click(SMART_CAST)
            if self.smart_cast_click_count > 1:
                self.log(
                    f"已执行智能施法点击 {click_index + 1}/{self.smart_cast_click_count}",
                    "info",
                )
        self.log("已进入战斗并启动智能施法", "ok")
        time.sleep(0.8)

        started = time.monotonic()
        cycle_started = started
        sweep_index = 0
        smart_cast_checked = False
        next_smart_cast_check = started + SMART_CAST_CHECK_DELAY
        self.log(
            f"开始随机八向移动 {self.random_walk_seconds:g} 秒"
            f"（每次 {RANDOM_STEP_SECONDS:g} 秒）",
            "info",
        )

        while time.monotonic() - started < RUN_TIMEOUT and not self.should_stop():
            frame = self.screenshot()
            now = time.monotonic()
            if self._handle_revive(frame):
                continue
            settlement, settlement_center = self._settlement(frame)
            if settlement:
                self.click(settlement_center)
                self.log("已点击“退出副本”，等待返回千域大地图", "ok")
                returned = self._wait_for_map()
                self.log(
                    "已返回千域大地图，一轮嘉年华刷取完成"
                    if returned
                    else "退出副本已点击，但未在限定时间内确认大地图",
                    "ok" if returned else "warn",
                )
                return returned

            exit_hit, exit_center = self._boss_exit(frame)
            if exit_hit:
                self.click(exit_center)
                self.log("Boss 已击败，已点击右侧出口", "ok")
                deadline = time.monotonic() + SETTLEMENT_TIMEOUT
                while time.monotonic() < deadline and not self.should_stop():
                    frame = self.screenshot()
                    settlement, settlement_center = self._settlement(frame)
                    if settlement:
                        self.click(settlement_center)
                        self.log("已点击“退出副本”，等待返回千域大地图", "ok")
                        return self._wait_for_map()
                    time.sleep(0.8)
                self.log("已点击 Boss 出口，但等待结算界面超时", "error")
                return False

            # 每隔 5 秒确认智能施法是否打开；未打开就补点，直到确认开启。
            if not smart_cast_checked and now >= next_smart_cast_check:
                next_smart_cast_check = now + SMART_CAST_CHECK_DELAY
                opened, ratio = self.smart_cast_open(frame)
                if opened:
                    smart_cast_checked = True
                    self.log(
                        f"智能施法定时检测：已开启"
                        f"（青色占比 {ratio:.1%}）",
                        "ok",
                    )
                else:
                    self.click(SMART_CAST)
                    self.log(
                        f"智能施法定时检测：未开启"
                        f"（青色占比 {ratio:.1%}），已再次点击开启；"
                        f" {SMART_CAST_CHECK_DELAY:g} 秒后继续检测",
                        "warn",
                    )
                    continue

            if now - cycle_started < self.random_walk_seconds:
                self.move(self.random_direction(frame), seconds=RANDOM_STEP_SECONDS)
                continue

            sweep = patrol_sweep(sweep_index)
            if sweep is None:
                sweep_index = 0
                cycle_started = time.monotonic()
                self.log(
                    f"八向搜索完成一圈，重新开始随机八向移动"
                    f" {self.random_walk_seconds:g} 秒",
                    "info",
                )
                continue

            phase, direction = sweep
            self.log(
                f"{phase}八向 {sweep_index % len(EIGHT_DIRECTIONS) + 1}"
                f"/{len(EIGHT_DIRECTIONS)}：持续移动 {EIGHT_WAY_SECONDS:g} 秒",
                "info",
            )
            self.move(direction, seconds=EIGHT_WAY_SECONDS)
            sweep_index += 1

        if self.should_stop():
            self.log("战斗控制已停止", "warn")
        else:
            self.log("嘉年华战斗超过 15 分钟，已停止本轮", "error")
        return False
