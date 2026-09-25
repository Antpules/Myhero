from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from battle_runner import (  # noqa: E402
    EIGHT_DIRECTIONS,
    EIGHT_WAY_SECONDS,
    PLAYER_AVATAR,
    RANDOM_STEP_SECONDS,
    RANDOM_WALK_SECONDS,
    SMART_CAST_CHECK_DELAY,
    STONE_SMART_CAST_CLICK_COUNT,
    STONE_SMART_CAST_CLICK_INTERVAL,
    STONE_SMART_CAST_START_DELAY,
    CarnivalBattleRunner,
    patrol_sweep,
    smart_cast_enabled,
)


def screenshot(name: str) -> np.ndarray:
    return np.asarray(Image.open(ROOT / "图片" / name).convert("RGB"))


class BattleRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = CarnivalBattleRunner.__new__(CarnivalBattleRunner)
        load = lambda name: np.asarray(  # noqa: E731
            Image.open(ROOT / "resource" / "image" / "混沌千域" / name).convert("RGB")
        )
        cls.runner.target_templates = [load(f"战斗目标_{i}.png") for i in range(1, 8)]
        cls.runner.boss_template = load("Boss倒计时.png")
        cls.runner.exit_template = load("Boss出口.png")
        cls.runner.settlement_template = load("退出副本.png")
        cls.runner.death_template = load("玩家死亡复活币.png")
        cls.runner.revive_confirm_template = load("复活确定.png")

    def test_all_battle_scenes_are_recognized(self) -> None:
        for index in range(1, 8):
            with self.subTest(scene=index):
                self.assertTrue(self.runner._battle(screenshot(f"战斗场景{index}.png")))

    def test_boss_and_settlement_states_are_distinct(self) -> None:
        boss = screenshot("boss战.png")
        result = screenshot("boss战结算.png")
        settlement = screenshot("结算界面.png")
        self.assertTrue(self.runner._boss(boss))
        self.assertFalse(self.runner._boss_exit(boss)[0])
        self.assertTrue(self.runner._boss_exit(result)[0])
        self.assertTrue(self.runner._settlement(settlement)[0])

    def test_death_coin_only_matches_dead_player_frame(self) -> None:
        dead = screenshot("战斗死亡.png")
        hit, _, score = self.runner._match(
            dead, self.runner.death_template, (45, 20, 115, 105), 0.80
        )
        self.assertTrue(hit)
        self.assertGreater(score, 0.95)
        for index in range(1, 8):
            with self.subTest(scene=index):
                normal = screenshot(f"战斗场景{index}.png")
                self.assertFalse(
                    self.runner._match(
                        normal, self.runner.death_template, (45, 20, 115, 105), 0.80
                    )[0]
                )

    def test_revive_confirmation_is_recognized(self) -> None:
        self.assertTrue(self.runner._revive_confirm(screenshot("复活确认.png"))[0])

    def test_dead_player_opens_dialog_and_confirms_revive(self) -> None:
        runner = CarnivalBattleRunner.__new__(CarnivalBattleRunner)
        runner.death_template = self.runner.death_template
        runner.revive_confirm_template = self.runner.revive_confirm_template
        runner.click = Mock()
        runner.screenshot = Mock(return_value=screenshot("复活确认.png"))
        runner.log = Mock()
        runner.should_stop = lambda: False

        with patch("battle_runner.time.sleep"):
            self.assertTrue(runner._handle_revive(screenshot("战斗死亡.png")))

        confirm_center = runner._revive_confirm(screenshot("复活确认.png"))[1]
        self.assertEqual(runner.click.call_args_list, [call(PLAYER_AVATAR), call(confirm_center)])


class SmartCastTests(unittest.TestCase):
    """`图片/` 里的 PNG 由 Pillow 读成 RGB，检测时需要 red_index=0。"""

    def test_disabled_button_is_detected_as_closed(self) -> None:
        for name in ("战斗场景1.png", "战斗场景7.png"):
            with self.subTest(image=name):
                ratio = smart_cast_enabled(screenshot(name), red_index=0)
                self.assertLess(ratio, 0.05)

    def test_enabled_button_is_detected_as_open(self) -> None:
        for name in (
            "战斗场景2.png",
            "战斗场景3.png",
            "战斗场景4.png",
            "战斗场景5.png",
            "战斗场景6.png",
            "boss战.png",
        ):
            with self.subTest(image=name):
                ratio = smart_cast_enabled(screenshot(name), red_index=0)
                self.assertGreater(ratio, 0.05)

    def test_frames_without_battle_ui_are_treated_as_closed(self) -> None:
        for name in ("结算界面.png", "混沌千域大地图.png", "嘉年华挑战.png"):
            with self.subTest(image=name):
                ratio = smart_cast_enabled(screenshot(name), red_index=0)
                self.assertLess(ratio, 0.05)

    def test_bgr_frames_use_the_same_threshold(self) -> None:
        """Maa 截图是 BGR：把 RGB 图翻转通道后检测结果应保持一致。"""
        for name in ("战斗场景1.png", "战斗场景2.png"):
            with self.subTest(image=name):
                rgb = screenshot(name)
                expected = smart_cast_enabled(rgb, red_index=0)
                bgr = smart_cast_enabled(rgb[..., ::-1], red_index=2)
                self.assertAlmostEqual(expected, bgr, places=6)

    def test_runner_helper_matches_rgb_ratio(self) -> None:
        runner = CarnivalBattleRunner.__new__(CarnivalBattleRunner)
        frame = screenshot("战斗场景2.png")
        opened, ratio = runner.smart_cast_open(frame[..., ::-1])
        self.assertTrue(opened)
        self.assertAlmostEqual(ratio, smart_cast_enabled(frame, red_index=0), places=6)


class PatrolTests(unittest.TestCase):
    def test_patrol_constants(self) -> None:
        self.assertEqual(RANDOM_WALK_SECONDS, 10.0)
        self.assertEqual(RANDOM_STEP_SECONDS, 1.0)
        self.assertEqual(EIGHT_WAY_SECONDS, 1.0)
        self.assertEqual(SMART_CAST_CHECK_DELAY, 5.0)
        self.assertEqual(STONE_SMART_CAST_START_DELAY, 1.0)
        self.assertEqual(STONE_SMART_CAST_CLICK_COUNT, 2)
        self.assertEqual(STONE_SMART_CAST_CLICK_INTERVAL, 1.0)

    def test_eight_way_cycle_is_normalized_and_closes(self) -> None:
        self.assertEqual(len(EIGHT_DIRECTIONS), 8)
        self.assertEqual(EIGHT_DIRECTIONS[0], (0.0, -1.0))
        self.assertEqual(EIGHT_DIRECTIONS[2], (1.0, 0.0))
        self.assertEqual(EIGHT_DIRECTIONS[4], (0.0, 1.0))
        self.assertEqual(EIGHT_DIRECTIONS[6], (-1.0, 0.0))
        for x, y in EIGHT_DIRECTIONS:
            self.assertAlmostEqual(x * x + y * y, 1.0)

    def test_patrol_goes_clockwise_then_counter_clockwise(self) -> None:
        total = len(EIGHT_DIRECTIONS)
        clockwise = [patrol_sweep(step) for step in range(total)]
        counter = [patrol_sweep(step) for step in range(total, 2 * total)]
        self.assertEqual([phase for phase, _ in clockwise], ["顺时针"] * total)
        self.assertEqual([phase for phase, _ in counter], ["逆时针"] * total)
        self.assertEqual([d for _, d in clockwise], list(EIGHT_DIRECTIONS))
        self.assertEqual(
            [d for _, d in counter], list(reversed(EIGHT_DIRECTIONS))
        )
        self.assertEqual(clockwise[0][1], EIGHT_DIRECTIONS[0])
        self.assertEqual(counter[0][1], EIGHT_DIRECTIONS[-1])
        self.assertIsNone(patrol_sweep(2 * total))
        self.assertIsNone(patrol_sweep(-1))


if __name__ == "__main__":
    unittest.main()
