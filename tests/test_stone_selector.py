from __future__ import annotations

import json
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stone_selector import (  # noqa: E402
    ADD_BUTTON,
    ADD_LABEL,
    CANCEL_LABEL,
    StoneSelector,
    button_kind,
    clean_name,
    is_dim_tile,
    tile_brightness,
)
from app import MaaRunner, carnival_pipeline_override, normalize_repeat_count  # noqa: E402


class TextNormalizationTests(unittest.TestCase):
    def test_clean_name_only_removes_trailing_bound_marker(self) -> None:
        self.assertEqual(clean_name("异·传奇鬼手惊梦石板(绑定） "), "异·传奇鬼手惊梦石板")
        self.assertEqual(clean_name("绑定之力石板"), "绑定之力石板")

    def test_button_kind_tolerates_ocr_noise(self) -> None:
        self.assertEqual(button_kind("（ 添 加 ）"), ADD_LABEL)
        self.assertEqual(button_kind("取消。"), CANCEL_LABEL)
        self.assertEqual(button_kind("4"), "")


class SelectionAccountingTests(unittest.TestCase):
    def make_selector(
        self, raw: str, button: str, *, bound_only: bool = True
    ) -> StoneSelector:
        selector = StoneSelector(context=None, controller=None, bound_only=bound_only)
        selector._pick_tile = Mock(return_value=(raw, button))  # type: ignore[method-assign]
        selector.click = Mock()  # type: ignore[method-assign]
        return selector

    def test_already_selected_stone_counts_as_progress(self) -> None:
        selector = self.make_selector("测试石板（绑定）", " 取 消 ")

        self.assertTrue(selector._try_add(0))
        self.assertEqual(selector._added, ["测试石板"])
        selector.click.assert_not_called()  # type: ignore[attr-defined]

    def test_new_stone_is_recorded_after_click(self) -> None:
        selector = self.make_selector("测试石板（绑定）", "添加")

        self.assertTrue(selector._try_add(0))
        self.assertEqual(selector._added, ["测试石板"])
        selector.click.assert_called_once_with(  # type: ignore[attr-defined]
            *selector._center(ADD_BUTTON), settle=1.1
        )

    def test_unbound_stone_is_allowed_when_filter_is_off(self) -> None:
        selector = self.make_selector("普通石板", "添加", bound_only=False)

        self.assertTrue(selector._try_add(0))
        self.assertEqual(selector._added, ["普通石板"])

    def test_dim_tile_is_skipped_without_clicking_or_ocr(self) -> None:
        from PIL import Image
        import numpy as np

        frame = np.array(Image.open(ROOT / "图片" / "石板选择界面.png").convert("RGB"))
        selector = self.make_selector("不应读取（绑定）", "添加")

        self.assertTrue(is_dim_tile(frame, 1))
        self.assertFalse(selector._try_add(1, frame))
        selector._pick_tile.assert_not_called()  # type: ignore[attr-defined]
        selector.click.assert_not_called()  # type: ignore[attr-defined]

    def test_owned_and_unowned_tiles_have_clear_brightness_gap(self) -> None:
        from PIL import Image
        import numpy as np

        frame = np.array(Image.open(ROOT / "图片" / "石板选择界面.png").convert("RGB"))
        self.assertGreater(tile_brightness(frame, 0) or 0, 150)
        self.assertLess(tile_brightness(frame, 1) or 999, 100)
        self.assertFalse(is_dim_tile(frame, 0))
        self.assertTrue(is_dim_tile(frame, 1))


class PipelineTests(unittest.TestCase):
    @patch("app.StoneSelector")
    def test_insufficient_stones_still_continue_to_battle(
        self, selector_class: Mock
    ) -> None:
        selector_class.return_value.bound_only = True
        selector_class.return_value.select.return_value = SimpleNamespace(
            names=["石板甲", "石板乙"], wanted=3, ok=False
        )
        events: queue.Queue = queue.Queue()
        runner = MaaRunner(events)
        action = runner._make_stone_action()
        context = SimpleNamespace(tasker=SimpleNamespace(controller=object()))
        argv = SimpleNamespace(custom_action_param=json.dumps({"bound_only": True}))

        self.assertTrue(action.run(context, argv))  # type: ignore[union-attr]
        logs = []
        while not events.empty():
            logs.append(events.get_nowait())
        self.assertTrue(any("继续点击前往" in event[2] for event in logs if event[0] == "log"))

    def test_entry_can_start_from_map(self) -> None:
        data = json.loads((ROOT / "resource" / "pipeline" / "stone.json").read_text("utf-8"))
        self.assertIn("石板_进入嘉年华", data["选择石板并前往"]["next"])

    def test_both_stone_paths_continue_into_battle(self) -> None:
        carnival = json.loads(
            (ROOT / "resource" / "pipeline" / "carnival.json").read_text("utf-8")
        )
        stone = json.loads(
            (ROOT / "resource" / "pipeline" / "stone.json").read_text("utf-8")
        )
        self.assertIn("嘉年华_点击前往", carnival["确认嘉年华挑战界面"]["next"])
        self.assertIn("嘉年华_点击前往", stone["选择石板"]["next"])
        self.assertEqual(
            carnival["嘉年华_执行战斗"]["custom_action"], "CarnivalBattle"
        )

    def test_interface_exposes_one_carnival_task_with_nested_options(self) -> None:
        interface = json.loads((ROOT / "interface.json").read_text("utf-8"))
        self.assertEqual(interface["label"], "勇者邦邦")
        self.assertEqual([task["label"] for task in interface["task"]], ["嘉年华刷取"])
        self.assertEqual(
            interface["task"][0]["option"],
            ["SelectStones", "AutoDecompose", "RepeatCount"],
        )
        yes_case = interface["option"]["SelectStones"]["cases"][0]
        self.assertEqual(yes_case["option"], ["BoundStones"])
        repeat = interface["option"]["RepeatCount"]
        self.assertEqual(repeat["type"], "input")
        self.assertEqual(repeat["inputs"][0]["default"], "1")

    def test_local_ui_override_only_enables_selected_features(self) -> None:
        self.assertEqual(carnival_pipeline_override(False, True), {})
        any_stone = carnival_pipeline_override(True, False)
        bound_stone = carnival_pipeline_override(True, True)
        self.assertFalse(any_stone["选择石板"]["custom_action_param"]["bound_only"])
        self.assertTrue(bound_stone["选择石板"]["custom_action_param"]["bound_only"])
        decompose = carnival_pipeline_override(False, False, 1, True)
        self.assertEqual(decompose["嘉年华刷取"]["next"], ["嘉年华_自动分解"])
        self.assertTrue(
            decompose["嘉年华_执行战斗"]["custom_action_param"]["auto_decompose"]
        )

    def test_repeat_override_is_passed_to_battle_action(self) -> None:
        override = carnival_pipeline_override(True, True, 12)
        params = override["嘉年华_执行战斗"]["custom_action_param"]
        self.assertEqual(params["repeat_count"], 12)
        self.assertTrue(params["select_stones"])
        self.assertTrue(params["bound_only"])

    def test_repeat_count_validation(self) -> None:
        self.assertEqual(normalize_repeat_count("1"), 1)
        self.assertEqual(normalize_repeat_count(" 23 "), 23)
        for invalid in ("", "0", "1.5", "abc", "1000", -1):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    normalize_repeat_count(invalid)

    @patch("app.CarnivalBattleRunner")
    def test_battle_action_runs_requested_number_of_rounds(self, battle_class: Mock) -> None:
        battle_class.return_value.run.return_value = True
        runner = MaaRunner(queue.Queue())
        action = runner._make_battle_action()
        self.assertIsNotNone(action)
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=object()),
            run_task=Mock(
                return_value=SimpleNamespace(status=SimpleNamespace(succeeded=True))
            ),
        )
        argv = SimpleNamespace(
            custom_action_param=json.dumps(
                {"repeat_count": 3, "select_stones": True, "bound_only": True}
            )
        )

        self.assertTrue(action.run(context, argv))  # type: ignore[union-attr]
        battle_class.return_value.run.assert_called_once()
        self.assertEqual(
            battle_class.call_args.kwargs["smart_cast_start_delay"], 1.0
        )
        self.assertEqual(battle_class.call_args.kwargs["smart_cast_click_count"], 2)
        self.assertEqual(battle_class.call_args.kwargs["smart_cast_click_interval"], 1.0)
        self.assertEqual(context.run_task.call_count, 2)
        for call in context.run_task.call_args_list:
            nested_override = call.args[1]
            self.assertIn("石板_打开石板界面", nested_override["确认嘉年华挑战界面"]["next"])
            self.assertTrue(
                nested_override["选择石板"]["custom_action_param"]["bound_only"]
            )

    @patch("app.DecomposeRunner")
    @patch("app.CarnivalBattleRunner")
    def test_auto_decompose_runs_after_every_five_rounds(
        self, battle_class: Mock, decompose_class: Mock
    ) -> None:
        battle_class.return_value.run.return_value = True
        decompose_class.return_value.run.return_value = True
        runner = MaaRunner(queue.Queue())
        action = runner._make_battle_action()
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=object()),
            run_task=Mock(
                return_value=SimpleNamespace(status=SimpleNamespace(succeeded=True))
            ),
        )
        argv = SimpleNamespace(
            custom_action_param=json.dumps(
                {"repeat_count": 10, "auto_decompose": True}
            )
        )

        self.assertTrue(action.run(context, argv))  # type: ignore[union-attr]
        self.assertEqual(context.run_task.call_count, 9)
        self.assertEqual(decompose_class.call_count, 2)
        self.assertEqual(decompose_class.return_value.run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
