from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

try:
    from maa.controller import AdbController
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    MAA_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - used only when maafw is missing
    AdbController = Resource = Tasker = Toolkit = None  # type: ignore[assignment]
    MAA_IMPORT_ERROR = exc

if getattr(sys, "frozen", False):  # pragma: no cover - 仅打包后生效
    # onefile 会把资源解包到临时目录，onedir 则放在 exe 同级的 _internal 下。
    APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    WORK_DIR = Path(sys.executable).resolve().parent
else:
    APP_ROOT = Path(__file__).resolve().parent
    WORK_DIR = APP_ROOT

RESOURCE_DIR = APP_ROOT / "resource"
APP_ICON_PNG = RESOURCE_DIR / "app_icon.png"
APP_ICON_ICO = RESOURCE_DIR / "app_icon.ico"
WINDOWS_APP_ID = "Myhero.BraveBangBang"


def configure_windows_app_id() -> None:
    """让源码运行时的任务栏图标不再继承 python.exe。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass

# 可选任务：界面下拉框里的每一项，值为 Pipeline 入口名
TASKS: tuple[tuple[str, str], ...] = (("嘉年华刷取", "嘉年华刷取"),)
DEFAULT_TASK = TASKS[0][1]


def carnival_pipeline_override(
    select_stones: bool,
    bound_only: bool = False,
    repeat_count: int = 1,
    auto_decompose: bool = False,
) -> dict[str, Any]:
    """Build the same option override declared in ``interface.json``."""
    override: dict[str, Any] = {}
    if select_stones:
        override.update(
            {
                "确认嘉年华挑战界面": {"next": ["石板_打开石板界面"]},
                "选择石板": {"custom_action_param": {"bound_only": bool(bound_only)}},
            }
        )
    if auto_decompose:
        override["嘉年华刷取"] = {"next": ["嘉年华_自动分解"]}
    repeat_count = normalize_repeat_count(repeat_count)
    if repeat_count > 1 or auto_decompose:
        override["嘉年华_执行战斗"] = {
            "custom_action_param": {
                "repeat_count": repeat_count,
                "select_stones": bool(select_stones),
                "bound_only": bool(bound_only),
                "auto_decompose": bool(auto_decompose),
            }
        }
    return override


def normalize_repeat_count(value: Any, maximum: int = 999) -> int:
    """校验循环次数，拒绝小数、空值、零和过大的输入。"""
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError("循环次数必须是正整数")
    count = int(text)
    if not 1 <= count <= maximum:
        raise ValueError(f"循环次数必须在 1–{maximum} 之间")
    return count

_prev_sys_path = list(sys.path)
sys.path.insert(0, str(APP_ROOT / "tools"))
try:
    from stone_selector import StoneSelector  # noqa: E402
    from battle_runner import (  # noqa: E402
        STONE_SMART_CAST_CLICK_COUNT,
        STONE_SMART_CAST_CLICK_INTERVAL,
        STONE_SMART_CAST_START_DELAY,
        CarnivalBattleRunner,
    )
    from decompose_runner import DecomposeRunner  # noqa: E402

    SELECTOR_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - 仅在选择逻辑缺失时触发
    StoneSelector = None  # type: ignore[assignment]
    CarnivalBattleRunner = None  # type: ignore[assignment]
    STONE_SMART_CAST_START_DELAY = 1.0
    STONE_SMART_CAST_CLICK_COUNT = 2
    STONE_SMART_CAST_CLICK_INTERVAL = 1.0
    DecomposeRunner = None  # type: ignore[assignment]
    SELECTOR_ERROR = exc
finally:
    sys.path[:] = _prev_sys_path

try:  # 自定义动作依赖 MaaFramework 的 CustomAction 基类
    from maa.custom_action import CustomAction

    CUSTOM_ACTION_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    CustomAction = None  # type: ignore[assignment]
    CUSTOM_ACTION_ERROR = exc

# ---------------------------------------------------------------- palette ---
BG = "#0f1420"
CARD = "#171e2d"
CARD_SOFT = "#1b2334"
INPUT = "#101725"
BORDER = "#2b3750"
TEXT = "#e9edf5"
TEXT_SOFT = "#c7d0df"
MUTED = "#8e9ab0"
FAINT = "#6c7890"
PURPLE = "#7567f7"
PURPLE_HOVER = "#887bff"
GREEN = "#68d6a2"
AMBER = "#f0c674"
RED = "#ff8799"

LOG_BG = "#0a0f18"
LOG_TIME = "#5c6880"
LOG_INFO = "#b9c3d3"
LOG_OK = "#7fe0b0"
LOG_WARN = "#ffd08a"
LOG_ERR = "#ff9fae"

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# log level -> (prefix tag colour) mapping
LEVEL_COLORS = {
    "info": LOG_INFO,
    "ok": LOG_OK,
    "warn": LOG_WARN,
    "error": LOG_ERR,
}
LEVEL_PREFIX = {"info": "·", "ok": "✓", "warn": "!", "error": "×"}

STATUS_COLORS = {
    "idle": MUTED,
    "run": PURPLE_HOVER,
    "ok": GREEN,
    "warn": AMBER,
    "error": RED,
}


class MaaRunner:
    """Runs MaaFramework work outside Tk's UI thread."""

    def __init__(self, events: queue.Queue[tuple[Any, ...]]) -> None:
        self.events = events
        self.thread: threading.Thread | None = None
        self._tasker: Any | None = None
        self._lock = threading.Lock()
        self._stop_requested = False
        self.stone_report: Any | None = None
        self.repeat_count = 1
        self._round_select_stones = False
        self._round_bound_only = False

    # ------------------------------------------------------- 自定义动作 ---
    def _make_stone_action(self) -> Any | None:
        """包装石板选择逻辑，把日志实时推给界面。"""
        if StoneSelector is None or CustomAction is None:
            self.events.put(
                ("log", "warn", f"石板选择逻辑不可用：{SELECTOR_ERROR or CUSTOM_ACTION_ERROR}")
            )
            return None

        runner = self

        class SelectStonesAction(CustomAction):  # type: ignore[misc, valid-type]
            def run(self, context: Any, argv: Any) -> bool:
                def emit(message: str, level: str) -> None:
                    runner.events.put(("log", level, message))

                params: dict[str, Any] = {}
                try:
                    raw_params = getattr(argv, "custom_action_param", "")
                    if raw_params:
                        loaded = json.loads(raw_params)
                        if isinstance(loaded, dict):
                            params = loaded
                except (TypeError, ValueError) as exc:
                    emit(f"石板设置解析失败，使用默认设置：{exc}", "warn")

                selector = StoneSelector(
                    context=context,
                    controller=context.tasker.controller,
                    log=emit,
                    bound_only=bool(params.get("bound_only", True)),
                )
                runner._round_select_stones = True
                runner._round_bound_only = selector.bound_only
                report = selector.select()
                runner.stone_report = report
                if report.names:
                    runner.events.put(("stones", list(report.names)))
                if not report.ok:
                    emit(
                        f"石板不足 {report.wanted} 个，按当前已选择的"
                        f" {len(report.names)} 个继续点击前往",
                        "warn",
                    )
                # 石板数量不足是正常的资源状态，不应阻断后续“前往”和战斗节点；
                # 真正的识别/控制异常会由 selector.select() 抛出并让动作失败。
                return True

        return SelectStonesAction()

    def _make_battle_action(self) -> Any | None:
        """包装嘉年华战斗状态机，并让停止按钮能中断移动循环。"""
        if CarnivalBattleRunner is None or CustomAction is None:
            self.events.put(
                ("log", "warn", f"战斗控制逻辑不可用：{SELECTOR_ERROR or CUSTOM_ACTION_ERROR}")
            )
            return None

        runner = self

        class CarnivalBattleAction(CustomAction):  # type: ignore[misc, valid-type]
            def run(self, context: Any, argv: Any) -> bool:
                def emit(message: str, level: str) -> None:
                    runner.events.put(("log", level, message))

                params: dict[str, Any] = {}
                try:
                    raw_params = getattr(argv, "custom_action_param", "")
                    if raw_params:
                        loaded = json.loads(raw_params)
                        if isinstance(loaded, dict):
                            params = loaded
                except (TypeError, ValueError) as exc:
                    emit(f"循环设置解析失败，按 1 轮执行：{exc}", "warn")

                try:
                    repeat_count = normalize_repeat_count(params.get("repeat_count", 1))
                except ValueError as exc:
                    emit(f"{exc}，按 1 轮执行", "warn")
                    repeat_count = 1
                select_stones = bool(
                    params.get("select_stones", False) or runner._round_select_stones
                )
                bound_only = bool(
                    params.get("bound_only", runner._round_bound_only)
                )
                suppress_round_log = bool(params.get("suppress_round_log", False))
                auto_decompose = bool(params.get("auto_decompose", False))

                for round_index in range(1, repeat_count + 1):
                    if runner._stopping():
                        return False
                    if not suppress_round_log:
                        emit(f"开始第 {round_index}/{repeat_count} 轮嘉年华刷取", "info")
                    if round_index == 1:
                        battle = CarnivalBattleRunner(
                            controller=context.tasker.controller,
                            log=emit,
                            should_stop=runner._stopping,
                            smart_cast_start_delay=(
                                STONE_SMART_CAST_START_DELAY if select_stones else 0.0
                            ),
                            smart_cast_click_count=(
                                STONE_SMART_CAST_CLICK_COUNT if select_stones else 1
                            ),
                            smart_cast_click_interval=(
                                STONE_SMART_CAST_CLICK_INTERVAL if select_stones else 0.0
                            ),
                        )
                        succeeded = bool(battle.run())
                    else:
                        runner.stone_report = None
                        nested_override = carnival_pipeline_override(
                            select_stones, bound_only, 1, False
                        )
                        nested_override["嘉年华_执行战斗"] = {
                            "custom_action_param": {"suppress_round_log": True}
                        }
                        detail = context.run_task(
                            DEFAULT_TASK,
                            nested_override,
                        )
                        succeeded = bool(
                            detail is not None
                            and getattr(detail, "status", None) is not None
                            and detail.status.succeeded
                        )
                    if not succeeded:
                        emit(f"第 {round_index}/{repeat_count} 轮执行失败", "error")
                        return False
                    if not suppress_round_log:
                        emit(f"第 {round_index}/{repeat_count} 轮已完成", "ok")
                    if auto_decompose and round_index % 5 == 0:
                        emit(f"已完成 {round_index} 轮，开始定期自动分解", "info")
                        decompose = DecomposeRunner(
                            controller=context.tasker.controller,
                            log=emit,
                            should_stop=runner._stopping,
                        )
                        if not decompose.run():
                            emit(f"第 {round_index} 轮后的自动分解失败", "error")
                            return False
                return True

        return CarnivalBattleAction()

    def _make_decompose_action(self) -> Any | None:
        """包装自动分解流程，供开刷前的 Pipeline 节点调用。"""
        if DecomposeRunner is None or CustomAction is None:
            self.events.put(
                ("log", "warn", f"自动分解逻辑不可用：{SELECTOR_ERROR or CUSTOM_ACTION_ERROR}")
            )
            return None

        runner = self

        class AutoDecomposeAction(CustomAction):  # type: ignore[misc, valid-type]
            def run(self, context: Any, argv: Any) -> bool:
                def emit(message: str, level: str) -> None:
                    runner.events.put(("log", level, message))

                action = DecomposeRunner(
                    controller=context.tasker.controller,
                    log=emit,
                    should_stop=runner._stopping,
                )
                return bool(action.run())

        return AutoDecomposeAction()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(
        self,
        device: Any,
        entry: str = DEFAULT_TASK,
        pipeline_override: dict[str, Any] | None = None,
        repeat_count: int = 1,
    ) -> None:
        if self.running:
            return
        with self._lock:
            self._stop_requested = False
            self._tasker = None
        self.stone_report = None
        self.repeat_count = normalize_repeat_count(repeat_count)
        self._round_select_stones = False
        self._round_bound_only = False
        self.thread = threading.Thread(
            target=self._run,
            args=(device, entry, pipeline_override or {}),
            daemon=True,
        )
        self.thread.start()

    def request_stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            tasker = self._tasker
        self.events.put(("log", "warn", "正在请求 MaaFramework 停止任务……"))
        if tasker is not None:
            threading.Thread(target=self._post_stop, args=(tasker,), daemon=True).start()

    def _post_stop(self, tasker: Any) -> None:
        try:
            tasker.post_stop().wait()
        except Exception as exc:
            self.events.put(("log", "error", f"停止请求发送失败：{exc}"))

    def _stopping(self) -> bool:
        with self._lock:
            return self._stop_requested

    def _run(
        self,
        device: Any,
        entry: str = DEFAULT_TASK,
        pipeline_override: dict[str, Any] | None = None,
    ) -> None:
        try:
            if self._stopping():
                self.events.put(("task_done", False, "任务已取消"))
                return

            self.events.put(("log", "info", f"正在加载资源：{RESOURCE_DIR}"))
            resource = Resource()
            resource_job = resource.post_bundle(RESOURCE_DIR)
            resource_job.wait()
            if resource_job.failed or not resource.loaded:
                raise RuntimeError("MaaFramework 资源加载失败")
            self.events.put(("log", "ok", "资源包加载完成"))

            action = self._make_stone_action()
            if action is not None:
                if not resource.register_custom_action("SelectStones", action):
                    self.events.put(("log", "warn", "注册石板选择动作失败"))
            battle_action = self._make_battle_action()
            if battle_action is not None:
                if not resource.register_custom_action("CarnivalBattle", battle_action):
                    self.events.put(("log", "warn", "注册嘉年华战斗动作失败"))
            decompose_action = self._make_decompose_action()
            if decompose_action is not None:
                if not resource.register_custom_action("AutoDecompose", decompose_action):
                    self.events.put(("log", "warn", "注册自动分解动作失败"))

            if self._stopping():
                self.events.put(("task_done", False, "任务已取消"))
                return

            self.events.put(("log", "info", f"正在连接设备：{device.address}"))
            controller = AdbController(
                adb_path=device.adb_path,
                address=device.address,
                screencap_methods=device.screencap_methods,
                input_methods=device.input_methods,
                config=device.config,
            )
            connection_job = controller.post_connection()
            connection_job.wait()
            if connection_job.failed or not controller.connected:
                raise RuntimeError("ADB 控制器连接失败")

            try:
                width, height = controller.resolution()
                self.events.put(("log", "ok", f"设备连接成功，分辨率 {width}×{height}"))
            except Exception:
                self.events.put(("log", "ok", "设备连接成功"))
            if self._stopping():
                self.events.put(("task_done", False, "任务已取消"))
                return

            self.events.put(("log", "info", "正在初始化任务执行器"))
            tasker = Tasker()
            tasker.bind(resource, controller)
            if not tasker.inited:
                raise RuntimeError("MaaFramework Tasker 初始化失败")

            with self._lock:
                self._tasker = tasker
                should_stop = self._stop_requested
            if should_stop:
                tasker.post_stop().wait()
                self.events.put(("task_done", False, "任务已取消"))
                return

            self.events.put(("log", "info", f"开始执行任务：{entry}"))
            task_job = tasker.post_task(entry, pipeline_override or {})
            task_job.wait()
            detail = task_job.get()

            succeeded = bool(
                not self._stopping()
                and task_job.succeeded
                and detail is not None
                and detail.status.succeeded
            )

            if self._stopping():
                self.events.put(("task_done", False, "任务已停止"))
            elif succeeded:
                stones = getattr(self.stone_report, "names", None)
                if stones:
                    self.events.put(
                        (
                            "task_done",
                            True,
                            f"{self.repeat_count} 轮嘉年华刷取已完成；末轮石板："
                            + "、".join(stones),
                        )
                    )
                else:
                    self.events.put(
                        ("task_done", True, f"{self.repeat_count} 轮嘉年华刷取已完成")
                    )
            else:
                self.events.put(("log", "error", "错误现场已保存到 debug/on_error"))
                raise RuntimeError("任务失败，请查看运行日志与 debug/on_error")
        except Exception as exc:
            self.events.put(("task_done", False, str(exc)))
        finally:
            with self._lock:
                self._tasker = None


class App(tk.Tk):
    def __init__(self) -> None:
        # 必须在创建顶层窗口前设置，否则 Windows 任务栏会继续使用 python.exe 图标。
        configure_windows_app_id()
        super().__init__()
        self.title("勇者邦邦")
        self.configure(bg=BG)
        self._app_icon: Any | None = None
        if sys.platform == "win32" and APP_ICON_ICO.exists():
            try:
                self.iconbitmap(str(APP_ICON_ICO))
            except tk.TclError:
                pass
        try:
            self._app_icon = tk.PhotoImage(file=str(APP_ICON_PNG))
            self.iconphoto(True, self._app_icon)
        except tk.TclError:
            pass
        self.minsize(880, 600)
        self._place_window(1080, 760)

        self.events: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.runner = MaaRunner(self.events)
        self.devices: list[Any] = []
        self.scan_thread: threading.Thread | None = None
        self.close_pending = False
        self.select_stones_var = tk.BooleanVar(value=False)
        self.bound_only_var = tk.BooleanVar(value=False)
        self.repeat_count_var = tk.StringVar(value="1")
        self.auto_decompose_var = tk.BooleanVar(value=False)

        self._configure_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)
        self.refresh_devices()

    # ------------------------------------------------------------ window ---
    def _place_window(self, width: int, height: int) -> None:
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
        except Exception:
            self.geometry(f"{width}x{height}")
            return
        width = min(width, screen_w - 40)
        height = min(height, screen_h - 80)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------ styles ---
    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "Dark.TCombobox",
            fieldbackground=INPUT,
            background=INPUT,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=10,
            font=(FONT, 11),
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[
                ("readonly", INPUT),
                ("disabled", "#151b28"),
                ("focus", INPUT),
            ],
            foreground=[("readonly", TEXT), ("disabled", FAINT)],
            selectbackground=[("readonly", INPUT)],
            selectforeground=[("readonly", TEXT)],
            arrowcolor=[("disabled", "#3d4759")],
        )
        style.configure(
            "Dark.Vertical.TScrollbar",
            background="#232d43",
            troughcolor=LOG_BG,
            bordercolor=LOG_BG,
            arrowcolor=MUTED,
            lightcolor="#232d43",
            darkcolor="#232d43",
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#33415e")],
            arrowcolor=[("active", TEXT)],
        )
        style.configure(
            "Dark.Horizontal.TProgressbar",
            background=PURPLE,
            troughcolor="#1a2233",
            bordercolor="#1a2233",
            lightcolor=PURPLE,
            darkcolor=PURPLE,
        )

    # ---------------------------------------------------------------- ui ---
    def _build_ui(self) -> None:
        page = tk.Frame(self, bg=BG, padx=26, pady=20)
        page.pack(fill="both", expand=True)

        self._build_header(page)
        self._build_device_card(page)
        self._build_actions(page)
        self._build_status(page)
        self._build_workspace(page)

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=BG)
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)

        left = tk.Frame(header, bg=BG)
        left.grid(row=0, column=0, sticky="w")

        title_row = tk.Frame(left, bg=BG)
        title_row.pack(anchor="w")
        tk.Label(
            title_row,
            text="勇者邦邦",
            bg=BG,
            fg="#ffffff",
            font=(FONT, 21, "bold"),
        ).pack(side="left")
        tk.Label(
            title_row,
            text=" v0.6.0",
            bg=BG,
            fg=FAINT,
            font=(FONT, 9),
        ).pack(side="left", pady=(8, 0))

    def _build_device_card(self, parent: tk.Widget) -> None:
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(16, 14))
        body = tk.Frame(card, bg=CARD, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", pady=(0, 9))
        tk.Label(
            head, text="ADB 设备", bg=CARD, fg=TEXT_SOFT, font=(FONT, 11, "bold")
        ).pack(side="left")
        self.device_hint = tk.Label(
            head, text="", bg=CARD, fg=FAINT, font=(FONT, 9)
        )
        self.device_hint.pack(side="right")

        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        row.columnconfigure(0, weight=1)
        self.device_combo = ttk.Combobox(
            row,
            state="readonly",
            style="Dark.TCombobox",
            height=8,
            font=(FONT, 11),
        )
        self.device_combo.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.device_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_device_hint())
        self.refresh_button = self._button(
            row, "刷新设备", self.refresh_devices, "#273249", "#33415e", 9
        )
        self.refresh_button.grid(row=0, column=1, sticky="ns", rowspan=2)

        task_row = tk.Frame(body, bg=CARD)
        task_row.pack(fill="x", pady=(12, 0))
        task_row.columnconfigure(0, weight=1)
        self.task_combo = ttk.Combobox(
            task_row,
            state="readonly",
            style="Dark.TCombobox",
            values=[label for label, _ in TASKS],
            font=(FONT, 11),
        )
        self.task_combo.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.task_combo.current(0)
        self.task_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_task_hint())

        self.task_hint = tk.Label(
            body, text="", bg=CARD, fg=FAINT, font=(FONT, 9), anchor="w"
        )
        self.task_hint.pack(fill="x", pady=(6, 0))
        self._sync_task_hint()

        options = tk.Frame(body, bg=CARD)
        options.pack(fill="x", pady=(10, 0))
        tk.Label(
            options,
            text="内部设置",
            bg=CARD,
            fg=TEXT_SOFT,
            font=(FONT, 10, "bold"),
        ).pack(side="left", padx=(0, 14))
        self.select_stones_check = tk.Checkbutton(
            options,
            text="选择石板",
            variable=self.select_stones_var,
            command=self._sync_stone_options,
            bg=CARD,
            activebackground=CARD,
            fg=TEXT,
            activeforeground=TEXT,
            selectcolor=INPUT,
            font=(FONT, 10),
            bd=0,
            highlightthickness=0,
        )
        self.select_stones_check.pack(side="left", padx=(0, 14))
        self.bound_only_check = tk.Checkbutton(
            options,
            text="选择绑定石板",
            variable=self.bound_only_var,
            bg=CARD,
            activebackground=CARD,
            fg=TEXT,
            activeforeground=TEXT,
            disabledforeground=FAINT,
            selectcolor=INPUT,
            font=(FONT, 10),
            bd=0,
            highlightthickness=0,
        )
        self.bound_only_check.pack(side="left")
        self.auto_decompose_check = tk.Checkbutton(
            options,
            text="自动分解",
            variable=self.auto_decompose_var,
            bg=CARD,
            activebackground=CARD,
            fg=TEXT,
            activeforeground=TEXT,
            selectcolor=INPUT,
            font=(FONT, 10),
            bd=0,
            highlightthickness=0,
        )
        self.auto_decompose_check.pack(side="left", padx=(14, 0))
        tk.Label(
            options,
            text="循环次数",
            bg=CARD,
            fg=TEXT_SOFT,
            font=(FONT, 10),
        ).pack(side="left", padx=(20, 6))
        self.repeat_count_spin = tk.Spinbox(
            options,
            from_=1,
            to=999,
            textvariable=self.repeat_count_var,
            width=5,
            justify="center",
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            buttonbackground="#273249",
            relief="flat",
            font=(FONT, 10),
        )
        self.repeat_count_spin.pack(side="left")
        self._sync_stone_options()

    def _build_actions(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 12))
        row.columnconfigure(0, weight=1)

        self.start_button = self._button(
            row, "开始执行", self.start_task, PURPLE, PURPLE_HOVER, 12
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.stop_button = self._button(
            row, "停止", self.stop_task, "#4a2631", "#62303f", 9, "#ffb8c5"
        )
        self.stop_button.grid(row=0, column=1, sticky="ns")
        self._set_button_enabled(self.stop_button, False)

    def _build_status(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 12))
        row.columnconfigure(1, weight=1)

        tk.Label(
            row, text="状态", bg=BG, fg=TEXT_SOFT, font=(FONT, 10, "bold")
        ).grid(row=0, column=0, sticky="w")

        self.status_label = tk.Label(
            row, text="等待设备", bg=BG, fg=MUTED, font=(FONT, 10), anchor="e"
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(
            parent,
            style="Dark.Horizontal.TProgressbar",
            mode="indeterminate",
            length=200,
        )
        self._progress_visible = False

    def _build_workspace(self, parent: tk.Widget) -> None:
        """Build a single full-width log workspace."""
        workspace = tk.Frame(parent, bg=BG)
        workspace.pack(fill="both", expand=True)
        workspace.rowconfigure(0, weight=1)
        workspace.columnconfigure(0, weight=1)
        self._build_log(workspace)

    def _build_log(self, parent: tk.Widget) -> None:
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=0, sticky="nsew")
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)

        head = tk.Frame(card, bg=CARD, padx=14, pady=9)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        tk.Label(head, text="运行日志", bg=CARD, fg=TEXT_SOFT, font=(FONT, 10, "bold")).pack(
            side="left"
        )
        tk.Button(
            head,
            text="清空",
            command=self.clear_log,
            bg=CARD_SOFT,
            fg=TEXT_SOFT,
            activebackground="#2a3448",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=(FONT, 8),
            padx=9,
            pady=3,
        ).pack(side="right")

        wrap = tk.Frame(card, bg=LOG_BG)
        wrap.grid(row=1, column=0, columnspan=2, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.log_view = tk.Text(
            wrap,
            bg=LOG_BG,
            fg=LOG_INFO,
            insertbackground=TEXT,
            selectbackground="#34415b",
            relief="flat",
            wrap="word",
            padx=12,
            pady=10,
            font=(MONO, 10),
            state="disabled",
            spacing1=1,
            spacing3=2,
            cursor="arrow",
        )
        self.log_view.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            wrap, command=self.log_view.yview, style="Dark.Vertical.TScrollbar"
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_view.configure(yscrollcommand=scrollbar.set)

        for level, color in LEVEL_COLORS.items():
            self.log_view.tag_configure(f"msg-{level}", foreground=color)
        self.log_view.tag_configure("time", foreground=LOG_TIME)

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        command: Any,
        color: str,
        hover: str,
        width: int,
        foreground: str = "white",
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=foreground,
            activebackground=hover,
            activeforeground=foreground,
            disabledforeground="#5f6a7d",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=18,
            pady=10,
            width=width,
            font=(FONT, 10, "bold"),
        )
        button._normal_bg = color  # type: ignore[attr-defined]
        button._hover_bg = hover  # type: ignore[attr-defined]
        button._enabled = True  # type: ignore[attr-defined]
        button.bind("<Enter>", lambda _event, b=button: self._hover(b, True))
        button.bind("<Leave>", lambda _event, b=button: self._hover(b, False))
        return button

    @staticmethod
    def _hover(button: tk.Button, inside: bool) -> None:
        if not getattr(button, "_enabled", False):
            return
        button.configure(bg=button._hover_bg if inside else button._normal_bg)  # type: ignore[attr-defined]

    @staticmethod
    def _set_button_enabled(button: tk.Button, enabled: bool) -> None:
        button._enabled = enabled  # type: ignore[attr-defined]
        button.configure(
            state="normal" if enabled else "disabled",
            bg=button._normal_bg if enabled else "#242b38",  # type: ignore[attr-defined]
            cursor="hand2" if enabled else "arrow",
        )

    # ------------------------------------------------------------ status ---
    def set_status(self, message: str, level: str = "idle") -> None:
        self.status_label.configure(text=message, fg=STATUS_COLORS.get(level, MUTED))

    def _set_progress(self, active: bool) -> None:
        if active and not self._progress_visible:
            self.progress.pack(fill="x", pady=(0, 12))
            self.progress.start(14)
            self._progress_visible = True
        elif not active and self._progress_visible:
            self.progress.stop()
            self.progress.pack_forget()
            self._progress_visible = False

    # --------------------------------------------------------------- log ---
    def append_log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        prefix = LEVEL_PREFIX.get(level, "·")
        self.log_view.configure(state="normal")
        self.log_view.insert("end", f"[{stamp}] ", ("time",))
        self.log_view.insert("end", f"{prefix} {message}\n", (f"msg-{level}",))
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.configure(state="disabled")

    # ------------------------------------------------------------ devices ---
    def _sync_task_hint(self) -> None:
        index = self.task_combo.current()
        label = TASKS[index][0] if 0 <= index < len(TASKS) else TASKS[0][0]
        hints = {
            "嘉年华刷取": "进入嘉年华；是否选择石板及是否仅限绑定石板由下方设置决定",
        }
        self.task_hint.configure(text=hints.get(label, ""))

    def _sync_stone_options(self) -> None:
        enabled = bool(self.select_stones_var.get())
        if not enabled:
            self.bound_only_var.set(False)
        self.bound_only_check.configure(state="normal" if enabled else "disabled")

    def selected_entry(self) -> str:
        index = self.task_combo.current()
        return TASKS[index][1] if 0 <= index < len(TASKS) else DEFAULT_TASK

    def _sync_device_hint(self) -> None:
        index = self.device_combo.current()
        if 0 <= index < len(self.devices):
            device = self.devices[index]
            self.device_hint.configure(text=f"ADB 端口 {device.address}")
        else:
            self.device_hint.configure(text="")

    def refresh_devices(self) -> None:
        if self.scan_thread is not None and self.scan_thread.is_alive():
            return
        self._set_button_enabled(self.refresh_button, False)
        self._set_button_enabled(self.start_button, False)
        self.set_status("正在扫描设备…", "run")
        self.append_log("正在扫描 ADB 设备")
        self.scan_thread = threading.Thread(target=self._scan_devices, daemon=True)
        self.scan_thread.start()

    def _scan_devices(self) -> None:
        try:
            self.events.put(("devices", list(Toolkit.find_adb_devices())))
        except Exception as exc:
            self.events.put(("scan_error", f"扫描 ADB 设备失败：{exc}"))

    # --------------------------------------------------------------- task ---
    def start_task(self) -> None:
        index = self.device_combo.current()
        if index < 0 or index >= len(self.devices):
            messagebox.showwarning("没有设备", "请先刷新并选择一个 ADB 设备。", parent=self)
            return
        if self.runner.running:
            return

        try:
            repeat_count = normalize_repeat_count(self.repeat_count_var.get())
        except ValueError as exc:
            messagebox.showwarning("循环次数无效", str(exc), parent=self)
            self.repeat_count_spin.focus_set()
            return

        self._set_button_enabled(self.start_button, False)
        self._set_button_enabled(self.refresh_button, False)
        self._set_button_enabled(self.stop_button, True)
        self.device_combo.configure(state="disabled")
        self.task_combo.configure(state="disabled")
        self.select_stones_check.configure(state="disabled")
        self.bound_only_check.configure(state="disabled")
        self.repeat_count_spin.configure(state="disabled")
        self.auto_decompose_check.configure(state="disabled")
        self.set_status("任务执行中…", "run")
        self._set_progress(True)
        entry = self.selected_entry()
        select_stones = bool(self.select_stones_var.get())
        bound_only = bool(self.bound_only_var.get())
        auto_decompose = bool(self.auto_decompose_var.get())
        override = carnival_pipeline_override(
            select_stones, bound_only, repeat_count, auto_decompose
        )
        self.append_log(f"开始执行任务：{entry}，计划循环 {repeat_count} 轮")
        if select_stones:
            mode = "仅绑定石板" if bound_only else "任意可用石板"
            self.append_log(f"石板选择已启用：{mode}")
        else:
            self.append_log("石板选择未启用，仅打开嘉年华挑战界面")
        if auto_decompose:
            self.append_log("自动分解已启用：开始前执行一次，之后每 5 轮执行一次")
        self.runner.start(self.devices[index], entry, override, repeat_count)

    def stop_task(self) -> None:
        if not self.runner.running:
            return
        self._set_button_enabled(self.stop_button, False)
        self.set_status("正在停止…", "run")
        self.runner.request_stop()

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self.append_log(event[2], event[1])
                elif kind == "stones":
                    self.append_log("已识别的石板：" + "、".join(event[1]), "ok")
                elif kind == "devices":
                    self._show_devices(event[1])
                elif kind == "scan_error":
                    self._scan_failed(event[1])
                elif kind == "task_done":
                    self._task_done(event[1], event[2])
        except queue.Empty:
            pass

        if self.close_pending and not self.runner.running:
            self.destroy()
            return
        self.after(100, self._drain_events)

    def _show_devices(self, devices: list[Any]) -> None:
        self.devices = devices
        names = [f"{device.name or 'ADB 设备'}  ·  {device.address}" for device in devices]
        self.device_combo.configure(values=names)
        if devices:
            self.device_combo.current(0)
            self.device_combo.configure(state="readonly")
            self._sync_device_hint()
            self._set_button_enabled(self.start_button, True)
            self.set_status(f"发现 {len(devices)} 个设备", "ok")
            self.append_log(f"已发现 {len(devices)} 个可用设备", "ok")
        else:
            self.device_combo.set("")
            self.device_hint.configure(text="")
            self._set_button_enabled(self.start_button, False)
            self.set_status("未发现设备", "error")
            self.append_log("未发现 ADB 设备，请先启动模拟器并开启 ADB", "warn")
        self._set_button_enabled(self.refresh_button, True)

    def _scan_failed(self, message: str) -> None:
        self._set_button_enabled(self.refresh_button, True)
        self._set_button_enabled(self.start_button, False)
        self.set_status("扫描失败", "error")
        self.append_log(message, "error")

    def _task_done(self, succeeded: bool, message: str) -> None:
        self._set_progress(False)
        self.append_log(message, "ok" if succeeded else "error")
        self.set_status(message, "ok" if succeeded else "error")
        self._set_button_enabled(self.stop_button, False)
        self._set_button_enabled(self.refresh_button, True)
        self._set_button_enabled(self.start_button, bool(self.devices))
        self.device_combo.configure(state="readonly")
        self.task_combo.configure(state="readonly")
        self.select_stones_check.configure(state="normal")
        self.repeat_count_spin.configure(state="normal")
        self.auto_decompose_check.configure(state="normal")
        self._sync_stone_options()

    def _on_close(self) -> None:
        if self.runner.running:
            if not messagebox.askyesno(
                "任务正在运行", "关闭窗口前需要停止当前任务，是否继续？", parent=self
            ):
                return
            self.close_pending = True
            self.stop_task()
            self.set_status("正在停止任务并关闭…", "run")
            return
        self.destroy()


def main() -> int:
    configure_windows_app_id()
    if MAA_IMPORT_ERROR is not None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "缺少 MaaFramework",
            "无法导入 MaaFramework Python 绑定。\n\n"
            "请运行：python -m pip install -r requirements.txt\n\n"
            f"详细信息：{MAA_IMPORT_ERROR}",
            parent=root,
        )
        root.destroy()
        return 1

    try:
        if not Toolkit.init_option(WORK_DIR):
            raise RuntimeError("Toolkit.init_option 返回失败")
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("初始化失败", f"MaaFramework 初始化失败：\n{exc}", parent=root)
        root.destroy()
        return 1

    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
