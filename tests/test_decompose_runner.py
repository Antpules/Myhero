from __future__ import annotations

import json
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from app import MaaRunner  # noqa: E402
from decompose_runner import DecomposeRunner  # noqa: E402


def screenshot(name: str) -> np.ndarray:
    return np.asarray(Image.open(ROOT / "图片" / name).convert("RGB"))


class DecomposeRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = DecomposeRunner(controller=None)

    def assert_marker(
        self,
        source: str,
        template: np.ndarray,
        roi: tuple[int, int, int, int],
        threshold: float = 0.78,
    ) -> None:
        hit, _, score = self.runner._match(screenshot(source), template, roi, threshold)
        self.assertTrue(hit, f"{source} marker score={score:.3f}")

    def test_all_decompose_screens_are_recognized(self) -> None:
        self.assert_marker("自动分解_口袋.png", self.runner.pocket_title, (0, 0, 500, 120))
        self.assert_marker("自动分解_筛选.png", self.runner.filter_title, (650, 0, 630, 150))
        self.assert_marker(
            "自动分解_已选择.png", self.runner.selected_marker, (800, 500, 480, 220)
        )
        self.assert_marker(
            "自动分解_已选择.png", self.runner.selection_confirm, (150, 580, 500, 140)
        )

    def test_large_and_small_reward_dialogs_share_the_same_markers(self) -> None:
        for source in ("自动分解_奖励大窗.png", "自动分解_奖励小窗.png"):
            with self.subTest(source=source):
                self.assert_marker(source, self.runner.reward_title, (350, 50, 600, 350))
                self.assert_marker(source, self.runner.reward_confirm, (350, 350, 600, 340))


class DecomposeIntegrationTests(unittest.TestCase):
    def test_empty_selection_ends_all_remaining_rounds_successfully(self) -> None:
        runner = DecomposeRunner(controller=None)
        runner.click = Mock()  # type: ignore[method-assign]
        runner.log = Mock()
        runner._wait_match = Mock(side_effect=[(50, 50), (100, 40)])  # type: ignore[method-assign]
        runner._run_round = Mock(return_value=None)  # type: ignore[method-assign]
        runner._return_to_map = Mock(return_value=True)  # type: ignore[method-assign]

        self.assertTrue(runner.run())
        runner._run_round.assert_called_once_with(1)  # type: ignore[attr-defined]
        self.assertTrue(
            any("已无满足条件的装备" in call.args[0] for call in runner.log.call_args_list)
        )

    def test_pipeline_registers_decompose_step_before_carnival(self) -> None:
        data = json.loads(
            (ROOT / "resource" / "pipeline" / "carnival.json").read_text("utf-8")
        )
        self.assertEqual(data["嘉年华_自动分解"]["custom_action"], "AutoDecompose")
        self.assertIn(
            "识别混沌千域并点击嘉年华", data["嘉年华_自动分解"]["next"]
        )

    @patch("app.DecomposeRunner")
    def test_custom_action_runs_decompose_runner(self, decompose_class: Mock) -> None:
        decompose_class.return_value.run.return_value = True
        runner = MaaRunner(queue.Queue())
        action = runner._make_decompose_action()
        self.assertIsNotNone(action)
        controller = object()
        context = SimpleNamespace(tasker=SimpleNamespace(controller=controller))

        self.assertTrue(action.run(context, SimpleNamespace()))  # type: ignore[union-attr]
        decompose_class.assert_called_once()
        self.assertIs(decompose_class.call_args.kwargs["controller"], controller)
        decompose_class.return_value.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
