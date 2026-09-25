"""石板选择逻辑：自动选择三个不同石板并识别其名称，可选仅限绑定石板。

坐标与流程来自 `功能实现/石板放置功能.txt`，全部基于 1280x720 的横屏画面：

1. 在嘉年华挑战界面点击 [988, 563, 64, 61] 展开石板选择界面；展开后游戏会
   默认选中第一个拥有的石板，因此直接从石板条最左侧开始往右挑选；
2. 识别 [328, 190, 313, 31] 处的石板名字，并点击 [422, 499, 121, 48] 的“添加”按钮；
3. 依次点击每个石板，直到添加满 3 个不同的石板；不足 3 个时才向右拖动，
   从 [852, 631] 拖到 [97, 638] 查看后续石板；
4. 拖动后识别最右侧石板名字，若连续 3 次相同则视为已经拖动到底；
5. 启用绑定过滤时只选择名称带“（绑定）”字样的石板；
6. 点击 [988, 563, 64, 61] / [1064, 567, 52, 53] / [1126, 568, 62, 53]
   可以选中已放置的石板并取消选中。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- 坐标常量 ---
# 石板选择界面底部石板条：8 个可见图块
TILE_ROW_X = (97, 205, 313, 421, 529, 637, 745, 853)
TILE_Y = 631

# 覆盖整个图块的中上部，以容忍拖动后列表没有正好停在整格位置。使用区域内的
# 90% 分位亮度而非均值，避免黑色背景把亮图标的结果拉低。实测拥有图标约
# 155–163，未拥有图标约 87–94；阈值留出足够余量。
TILE_SAMPLE_HALF_WIDTH = 45
TILE_SAMPLE_TOP = 600
TILE_SAMPLE_BOTTOM = 655
DIM_BRIGHTNESS_THRESHOLD = 115.0

# 石板条拖动：从右向左拖动，露出右侧的石板
DRAG_FROM = (852, TILE_Y)
DRAG_TO = (97, 638)
DRAG_MS = 700

# 中央详情面板：石板名字与“添加”按钮
TITLE_ROI = (328, 190, 313, 31)
ADD_BUTTON = (422, 499, 121, 48)

# 右侧“石板奖励”的三个槽位，用于查看/取消已放置的石板
SLOT_ROIS = ((988, 563, 64, 61), (1064, 567, 52, 53), (1126, 568, 62, 53))

TITLE_NODE = "石板_标题识别"
BUTTON_NODE = "石板_按钮识别"


def _ocr_override(node: str, roi: tuple[int, int, int, int]) -> dict[str, Any]:
    """构造 OCR 节点覆盖；roi 使用整屏坐标。"""
    return {
        node: {
            "recognition": "OCR",
            "roi": list(roi),
            "threshold": 0.1,
            "only_rec": True,
            "order_by": "Horizontal",
        }
    }

ADD_LABEL = "添加"
CANCEL_LABEL = "取消"

CLICK_SETTLE = 0.7
ADD_SETTLE = 1.1
DRAG_SETTLE = 1.0
MAX_DRAGS = 8
# 面板刷新等待：读取为空时重复取帧的间隔与次数
RETRY_WAIT = 0.45
RETRY_TIMES = 3
# 拖动后最右侧石板名字连续相同的次数，达到即认为已经拖到底
END_REPEATS = 3

# 只选择名称带“绑定”字样的石板
BOUND_MARK = "绑定"

# 置为 True 时输出每个图块的识别详情，用于排查误判
DEBUG = False

# 石板名称里不应影响“是否同一块石板”判断的字符
_NAME_NOISE = re.compile(r"[\s·・.，,。:：]+")

# 名称末尾的“绑定”标记（OCR 可能识别成 ( 或 （）
_BOUND_SUFFIX = re.compile(r"[\s·・.，,。:：]*[《（(【\[]?\s*绑定\s*[》）》)】\]]?\s*$")
_LABEL_NOISE = re.compile(r"[\s·・.，,。:：()（）【】\[\]]+")


def is_bound(raw: str) -> bool:
    """判断石板名称是否带“绑定”字样。"""
    return BOUND_MARK in (raw or "")


def clean_name(raw: str) -> str:
    """清理 OCR 结果：去掉首尾杂符与末尾的“绑定”标记。"""
    name = _BOUND_SUFFIX.sub("", raw or "")
    return name.strip("·・.，,。:： ")


def name_key(name: str) -> str:
    """把石板名归一化成用于去重的键。"""
    return _NAME_NOISE.sub("", name or "")


def button_kind(raw: str) -> str:
    """归一化按钮 OCR；容忍空格、括号和少量附带字符。"""
    label = _LABEL_NOISE.sub("", raw or "")
    if CANCEL_LABEL in label:
        return CANCEL_LABEL
    if ADD_LABEL in label:
        return ADD_LABEL
    return ""


def tile_brightness(image: Any, index: int) -> float | None:
    """返回指定图块区域的 90% 分位亮度；无法读取时返回 ``None``。"""
    if image is None or not 0 <= index < len(TILE_ROW_X):
        return None
    x = TILE_ROW_X[index]
    try:
        crop = image[
            TILE_SAMPLE_TOP:TILE_SAMPLE_BOTTOM,
            x - TILE_SAMPLE_HALF_WIDTH : x + TILE_SAMPLE_HALF_WIDTH + 1,
        ]
        if crop.size == 0:
            return None
        pixels = sorted(float(value) for value in crop.mean(axis=2).flat)
        return pixels[int((len(pixels) - 1) * 0.9)]
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def is_dim_tile(image: Any, index: int) -> bool:
    """未拥有或因冲突不可用的石板会整体变暗，可在点击前快速排除。"""
    brightness = tile_brightness(image, index)
    return brightness is not None and brightness < DIM_BRIGHTNESS_THRESHOLD


@dataclass
class SelectorReport:
    """选择结果：UI 需要的信息都在这里。"""

    names: list[str] = field(default_factory=list)
    scans: int = 0
    drags: int = 0
    wanted: int = 3
    message: str = ""

    @property
    def ok(self) -> bool:
        return len(self.names) >= self.wanted

    @property
    def summary(self) -> str:
        return "、".join(self.names) if self.names else "无"


class StoneSelector:
    """在石板选择界面自动挑选并添加石板。"""

    def __init__(
        self,
        context: Any,
        controller: Any,
        log: Callable[[str, str], None] | None = None,
        wanted: int = 3,
        settle_scale: float = 1.0,
        bound_only: bool = True,
    ) -> None:
        self.context = context
        self.controller = controller
        self.wanted = wanted
        self.settle = settle_scale
        self.bound_only = bound_only
        self._log = log or (lambda message, level: None)
        self._added: list[str] = []
        self._scans = 0
        self._drags = 0

    # ------------------------------------------------------------ 基础设施 ---
    def log(self, message: str, level: str = "info") -> None:
        self._log(message, level)

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds * self.settle)

    def screenshot(self) -> Any:
        return self.controller.post_screencap().wait().get()

    def click(self, x: int, y: int, settle: float = CLICK_SETTLE) -> None:
        self.controller.post_click(int(x), int(y)).wait()
        self._sleep(settle)

    def drag(self) -> None:
        self.controller.post_swipe(*DRAG_FROM, *DRAG_TO, DRAG_MS).wait()
        self._sleep(DRAG_SETTLE)

    def _read(self, node: str, image: Any, roi: tuple[int, int, int, int]) -> str:
        """读取识别文本原文（未做清理，便于判断“绑定”字样）。"""
        override = _ocr_override(node, roi)
        detail = self.context.run_recognition(node, image, override)
        text = self._text_of(detail)
        if text:
            return text
        return self._read_bright(node, image, roi)

    @staticmethod
    def _text_of(detail: Any) -> str:
        if detail is None or not getattr(detail, "hit", False):
            return ""
        best = getattr(detail, "best_result", None)
        text = getattr(best, "text", "") if best is not None else ""
        if not text:
            results = getattr(detail, "all_results", None) or []
            text = getattr(results[0], "text", "") if results else ""
        return text or ""

    def _read_bright(self, node: str, image: Any, roi: tuple[int, int, int, int]) -> str:
        """兜底：灰度放大并拉高对比度后再识别一次。"""
        brightened = self._brighten(image, roi)
        if brightened is None:
            return ""
        detail = self.context.run_recognition(
            node, brightened, _ocr_override(node, (0, 0, roi[2] * 2, roi[3] * 2))
        )
        return self._text_of(detail)

    @staticmethod
    def _brighten(image: Any, roi: tuple[int, int, int, int]) -> Any | None:
        try:
            import numpy as np
            from PIL import Image, ImageOps
        except Exception:
            return None
        x, y, w, h = roi
        try:
            crop = image[y : y + h, x : x + w]
        except Exception:
            return None
        if crop.size == 0:
            return None
        gray = Image.fromarray(crop).convert("L")
        gray = gray.resize((w * 2, h * 2), Image.LANCZOS)
        rgb = ImageOps.autocontrast(gray).convert("RGB")
        return np.array(rgb)[:, :, ::-1].copy()

    def read_title(self, image: Any) -> str:
        """石板名字原文，可能带末尾的“（绑定）”。"""
        return self._read(TITLE_NODE, image, TITLE_ROI)

    def read_button(self, image: Any) -> str:
        return self._read(BUTTON_NODE, image, ADD_BUTTON)

    # ---------------------------------------------------------------- 流程 ---
    def _pick_tile(self, index: int) -> tuple[str, str]:
        """点击第 index 个图块，返回 (石板名原文, 按钮文案)。

        面板切换有动画，读空时等待后再取帧重试，避免拿到上一块石板的数据。
        """
        self.click(TILE_ROW_X[index], TILE_Y)
        raw, button = self._read_panel()
        if not raw or not button:
            self.click(TILE_ROW_X[index], TILE_Y - 10)
            raw, button = self._read_panel()
        self._scans += 1
        return raw, button

    def _read_panel(self) -> tuple[str, str]:
        """读取中央面板的石板名与按钮文案，空结果会重试。"""
        raw = button = ""
        for attempt in range(RETRY_TIMES):
            image = self.screenshot()
            raw = self.read_title(image)
            button = self.read_button(image)
            if raw and button:
                break
            if attempt < RETRY_TIMES - 1:
                self._sleep(RETRY_WAIT)
        return raw, button

    def select(self) -> SelectorReport:
        """挑选并添加石板，返回最终结果。

        展开界面时游戏已默认选中第一块石板，因此从最左侧开始向右扫描；
        每添加一块后从**下一块**继续，不会回头重扫前面的石板。
        """
        mode = "绑定石板" if self.bound_only else "可用石板"
        self.log(f"进入石板选择界面，开始从左向右挑选{mode}", "info")
        index = 0
        last_right = ""
        end_repeats = 0

        while len(self._added) < self.wanted:
            found = self._scan_from(index)
            if found >= 0:
                # 从刚添加的石板之后继续扫描
                index = found + 1
                if len(self._added) >= self.wanted:
                    break
                continue

            # 可见范围内已经没有合适的石板，向右拖动查看后续石板
            if self._drags >= MAX_DRAGS:
                self.log(f"已拖动 {self._drags} 次仍不足，停止挑选", "warn")
                break
            self.log(f"可见范围内没有更多合适的{mode}，向右拖动查看后续石板", "warn")
            self.drag()
            self._drags += 1
            # 拖动后石板条整体左移，从左端重新扫描
            index = 0

            right = clean_name(self._rightmost_name())
            if right and right == last_right:
                end_repeats += 1
                self.log(
                    f"拖动后最右侧仍是“{right}”（{end_repeats}/{END_REPEATS}）", "warn"
                )
                if end_repeats >= END_REPEATS:
                    self.log("已拖动到底，没有更多石板", "warn")
                    break
            else:
                end_repeats = 0
            last_right = right

        report = SelectorReport(
            names=list(self._added),
            scans=self._scans,
            drags=self._drags,
            wanted=self.wanted,
        )
        if report.ok:
            report.message = "已选择 " + report.summary
            self.log(f"最终选择了 {len(report.names)} 个石板：" + report.summary, "ok")
        elif report.names:
            report.message = "仅找到 " + report.summary
            self.log(
                f"{mode}不足 {self.wanted} 个，仅选择到 {len(report.names)} 个："
                + report.summary,
                "warn",
            )
        else:
            if self.bound_only:
                report.message = "未找到绑定的石板"
                self.log(
                    "未找到绑定的石板（名称末尾没有“绑定”字样），不添加任何石板",
                    "warn",
                )
            else:
                report.message = "未找到可添加的石板"
                self.log("未找到可添加的石板", "warn")
        return report

    def _rightmost_name(self) -> str:
        """识别当前最右侧图块的石板名字。"""
        self.click(TILE_ROW_X[-1], TILE_Y)
        return self.read_title(self.screenshot())

    def _scan_from(self, start: int) -> int:
        """从 start 开始向右扫描，添加成功则返回该图块下标，否则返回 -1。"""
        row_image = self.screenshot()
        for index in range(start, len(TILE_ROW_X)):
            if self._try_add(index, row_image):
                return index
        return -1

    def _try_add(self, index: int, row_image: Any | None = None) -> bool:
        """检查第 index 个图块，若符合当前过滤条件且可添加则添加。"""
        if row_image is not None and is_dim_tile(row_image, index):
            self._scans += 1
            if DEBUG:
                brightness = tile_brightness(row_image, index)
                self.log(
                    f"[debug] 图块{index + 1}亮度={brightness:.1f}，未拥有或当前冲突，跳过"
                )
            return False

        raw, button = self._pick_tile(index)
        if not raw:
            return False
        name = clean_name(raw)

        if DEBUG:
            self.log(f"[debug] 图块{index + 1} 名称={raw!r} 按钮={button!r}")

        # 启用“仅选择绑定石板”时，未带绑定标记的一律跳过。
        if self.bound_only and not is_bound(raw):
            if DEBUG:
                self.log(f"[debug] “{name}”非绑定石板，跳过")
            return False

        if name_key(name) in {name_key(n) for n in self._added}:
            # 已经添加过（可能是拖动后重复出现的同一块石板）
            return False
        kind = button_kind(button)
        if kind == CANCEL_LABEL:
            # 该石板已在石板奖励中，避免重复选择
            self.log(f"“{name}”已在石板奖励中，跳过", "warn")
            self._added.append(name)
            return True
        if kind != ADD_LABEL:
            # 数量为 0 等不可添加的石板：没有“添加”按钮
            if DEBUG:
                self.log(f"[debug] “{name}”不可添加，跳过")
            return False

        self.click(*self._center(ADD_BUTTON), settle=ADD_SETTLE)
        self._added.append(name)
        self.log(f"已添加第 {len(self._added)} 块石板：{name}", "ok")
        return True

    @staticmethod
    def _center(roi: tuple[int, int, int, int]) -> tuple[int, int]:
        x, y, w, h = roi
        return x + w // 2, y + h // 2
