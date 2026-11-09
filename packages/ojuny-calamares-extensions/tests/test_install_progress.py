import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules" / "ojuny"))

from install_progress import InstallProgress, measure_closure_items


def line(payload):
    return "@nix " + json.dumps(payload) + "\n"


def start(act_id, act_type):
    return line({"action": "start", "id": act_id, "type": act_type})


def progress(act_id, done, expected):
    return line(
        {
            "action": "result",
            "id": act_id,
            "type": 105,
            "fields": [done, expected],
        }
    )


class MeasureClosureItemsTest(unittest.TestCase):
    def test_counts_unique_closure_paths(self):
        calls = []

        def run(command):
            calls.append(command)
            if "eval" in command:
                return "warning: ignored\n/nix/store/abc-system.drv\n"
            return "/nix/store/a\n/nix/store/b\n/nix/store/a\n"

        self.assertEqual(measure_closure_items(run, "/tmp/flake", "ojuny"), 2)
        self.assertIn("nix", calls[0])
        self.assertIn("nix-store", calls[1])
        self.assertIn("/nix/store/abc-system.drv", calls[1])

    def test_rejects_empty_derivation(self):
        with self.assertRaises(RuntimeError):
            measure_closure_items(lambda command: "\n", "/tmp/flake", "ojuny")

    def test_rejects_empty_closure(self):
        def run(command):
            if "eval" in command:
                return "/nix/store/abc-system.drv\n"
            return "\n"

        with self.assertRaises(RuntimeError):
            measure_closure_items(run, "/tmp/flake", "ojuny")


class InstallProgressTest(unittest.TestCase):
    def test_build_progress(self):
        tracker = InstallProgress(10)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 0, 10))
        tracker.handle(progress(1, 5, 10))
        self.assertEqual(tracker.done, 5)
        self.assertEqual(tracker.total, 10)
        self.assertEqual(tracker.fraction, 0.5)

    def test_copy_progress(self):
        tracker = InstallProgress(9)
        tracker.handle(start(2, 103))
        tracker.handle(progress(2, 9, 9))
        self.assertEqual(tracker.done, 9)
        self.assertEqual(tracker.fraction, 1.0)

    def test_mixed_build_and_copy_progress(self):
        tracker = InstallProgress(20)
        tracker.handle(start(1, 104))
        tracker.handle(start(2, 103))
        tracker.handle(progress(1, 5, 10))
        tracker.handle(progress(2, 5, 10))
        self.assertEqual(tracker.done, 10)
        self.assertEqual(tracker.total, 20)
        self.assertEqual(tracker.fraction, 0.5)

    def test_total_grows_to_live_plan(self):
        tracker = InstallProgress(5)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 0, 10))
        self.assertEqual(tracker.total, 10)
        tracker.handle(progress(1, 5, 10))
        self.assertEqual(tracker.fraction, 0.5)

    def test_fraction_does_not_drop_when_total_grows(self):
        tracker = InstallProgress(10)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 10))
        self.assertEqual(tracker.fraction, 0.5)
        tracker.handle(start(2, 103))
        tracker.handle(progress(2, 0, 10))
        self.assertEqual(tracker.total, 20)
        self.assertEqual(tracker.fraction, 0.5)

    def test_zero_total(self):
        tracker = InstallProgress(0)
        self.assertEqual(tracker.fraction, 0.0)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 1, 1))
        self.assertEqual(tracker.total, 1)
        self.assertEqual(tracker.fraction, 1.0)

    def test_fraction_is_clamped(self):
        tracker = InstallProgress(1)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 10, 10))
        self.assertEqual(tracker.fraction, 1.0)

    def test_plain_line_is_not_json(self):
        tracker = InstallProgress(1)
        self.assertFalse(tracker.handle("installing the boot loader...\n"))

    def test_log_messages_are_collected(self):
        tracker = InstallProgress(1)
        tracker.handle(
            line({"action": "msg", "level": 1, "msg": "copying path"})
        )
        tracker.handle(
            line({"action": "msg", "level": 2, "msg": "ignored"})
        )
        self.assertEqual(tracker.log_messages, ["copying path"])


if __name__ == "__main__":
    unittest.main()
