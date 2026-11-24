import json
import sys
import types
import importlib.util
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules" / "ojuny"))

from install_progress import (
    InstallProgress,
    is_install_item,
    measure_closure_items,
    measure_realized_items,
)


def line(payload):
    return "@nix " + json.dumps(payload) + "\n"


def copy_start(act_id, path):
    return line(
        {
            "action": "start",
            "id": act_id,
            "type": 100,
            "level": 3,
            "text": "copying path '{}' from 'https://cache.nixos.org'".format(path),
        }
    )


def stop(act_id):
    return line({"action": "stop", "id": act_id})


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


class MeasureRealizedItemsTest(unittest.TestCase):
    def test_counts_only_install_items(self):
        calls = []

        def run(command):
            calls.append(command)
            return "\n".join(
                ["/nix/store/a", "/nix/store/b.drv", "/nix/store/c-source", "/nix/store/d"]
            )

        self.assertEqual(
            measure_realized_items(run, "/tmp/root", "/nix/store/abc-system"), 2
        )
        self.assertIn("--store", calls[0])
        self.assertIn("/tmp/root", calls[0])
        self.assertIn("/nix/store/abc-system", calls[0])

    def test_rejects_closure_without_install_items(self):
        with self.assertRaises(RuntimeError):
            measure_realized_items(
                lambda command: "/nix/store/a.drv\n", "/tmp/root", "/nix/store/x"
            )


class MeasureClosureItemsTest(unittest.TestCase):
    def test_counts_only_install_items(self):
        calls = []

        def run(command):
            calls.append(command)
            if "eval" in command:
                return "warning: ignored\n/nix/store/abc-system.drv\n"
            return "\n".join(
                [
                    "/nix/store/a",
                    "/nix/store/b-source",
                    "/nix/store/c.drv",
                    "/nix/store/d",
                    "/nix/store/a",
                ]
            )

        self.assertEqual(
            measure_closure_items(run, "/tmp/root", "/tmp/flake", "ojuny"), 2
        )
        self.assertIn("nix", calls[0])
        self.assertIn("--store", calls[0])
        self.assertIn("/tmp/root", calls[0])
        self.assertIn("nix-store", calls[1])
        self.assertIn("--store", calls[1])
        self.assertIn("/tmp/root", calls[1])
        self.assertIn("/nix/store/abc-system.drv", calls[1])

    def test_env_prefix_and_eval_store_are_applied(self):
        calls = []

        def run(command):
            calls.append(command)
            if "eval" in command:
                return "/nix/store/abc-system.drv\n"
            return "/nix/store/a\n"

        measure_closure_items(
            run,
            "/tmp/root",
            "/tmp/flake",
            "ojuny",
            env=["env", "TMPDIR=/tmp/scratch"],
        )
        self.assertEqual(calls[0][0], "env")
        self.assertIn("TMPDIR=/tmp/scratch", calls[0])
        self.assertIn("--eval-store", calls[0])
        self.assertIn("/tmp/root", calls[0])
        self.assertEqual(calls[1][0], "env")

    def test_rejects_empty_derivation(self):
        with self.assertRaises(RuntimeError):
            measure_closure_items(
                lambda command: "\n", "/tmp/root", "/tmp/flake", "ojuny"
            )

    def test_rejects_closure_without_install_items(self):
        def run(command):
            if "eval" in command:
                return "/nix/store/abc-system.drv\n"
            return "/nix/store/a.drv\n/nix/store/b-source\n"

        with self.assertRaises(RuntimeError):
            measure_closure_items(run, "/tmp/root", "/tmp/flake", "ojuny")

    def test_install_item_filter(self):
        self.assertTrue(is_install_item("/nix/store/abc-hello-2.12"))
        self.assertFalse(is_install_item("/nix/store/abc-hello-2.12.drv"))
        self.assertFalse(is_install_item("/nix/store/abc-source"))


class InstallProgressTest(unittest.TestCase):
    def test_events_before_start_are_ignored(self):
        tracker = InstallProgress(10)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 10))
        tracker.handle(copy_start(2, "/nix/store/abc-hello"))
        tracker.handle(stop(2))
        self.assertEqual(tracker.done, 0)
        self.assertEqual(tracker.fraction, 0.0)

    def test_build_progress_after_start(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 10))
        self.assertEqual(tracker.done, 5)
        self.assertEqual(tracker.fraction, 0.5)

    def test_copy_progress_counts_output_paths(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-hello"))
        tracker.handle(stop(2))
        self.assertEqual(tracker.done, 1)
        self.assertEqual(tracker.fraction, 0.1)

    def test_copy_progress_ignores_derivations_and_sources(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-hello.drv"))
        tracker.handle(stop(2))
        tracker.handle(copy_start(3, "/nix/store/abc-source"))
        tracker.handle(stop(3))
        self.assertEqual(tracker.done, 0)
        self.assertEqual(tracker.fraction, 0.0)

    def test_mixed_build_and_copy_progress(self):
        tracker = InstallProgress(20)
        tracker.start()
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 10))
        for index, path in enumerate(
            ["/nix/store/abc-one", "/nix/store/abc-two"], start=10
        ):
            tracker.handle(copy_start(index, path))
            tracker.handle(stop(index))
        self.assertEqual(tracker.done, 7)
        self.assertEqual(tracker.fraction, 0.35)

    def test_build_baseline_is_removed_at_start(self):
        tracker = InstallProgress(10)
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 10))
        tracker.start()
        tracker.handle(progress(1, 10, 10))
        self.assertEqual(tracker.done, 5)
        self.assertEqual(tracker.fraction, 0.5)

    def test_expected_work_does_not_change_total(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 10))
        self.assertEqual(tracker.total, 10)
        self.assertEqual(tracker.fraction, 0.5)

    def test_expected_work_above_total_keeps_measured_total(self):
        tracker = InstallProgress(100)
        tracker.start()
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 90, 200))
        self.assertEqual(tracker.total, 100)
        self.assertEqual(tracker.fraction, 0.9)

    def test_fraction_does_not_drop_when_later_work_arrives(self):
        tracker = InstallProgress(100)
        tracker.start()
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 90, 100))
        self.assertEqual(tracker.fraction, 0.9)
        tracker.handle(start(2, 104))
        tracker.handle(progress(2, 0, 100))
        self.assertEqual(tracker.total, 100)
        self.assertEqual(tracker.fraction, 0.9)

    def test_completed_items_use_measured_total(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-hello"))
        tracker.handle(stop(2))
        self.assertEqual(tracker.done, 1)
        self.assertEqual(tracker.fraction, 0.1)

    def test_fraction_caps_at_one(self):
        tracker = InstallProgress(5)
        tracker.start()
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 5, 50))
        self.assertEqual(tracker.total, 5)
        self.assertEqual(tracker.fraction, 1.0)

    def test_aggregate_copy_paths_are_ignored(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(start(1, 103))
        tracker.handle(progress(1, 5, 10))
        self.assertEqual(tracker.done, 0)
        self.assertEqual(tracker.fraction, 0.0)

    def test_zero_total_reports_no_fraction(self):
        tracker = InstallProgress(0)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-hello"))
        tracker.handle(stop(2))
        self.assertEqual(tracker.done, 1)
        self.assertEqual(tracker.total, 0)
        self.assertEqual(tracker.fraction, 0.0)

    def test_set_total_after_realisation_updates_fraction(self):
        tracker = InstallProgress(0)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-hello"))
        tracker.handle(stop(2))
        tracker.set_total(4)
        self.assertEqual(tracker.total, 4)
        self.assertEqual(tracker.fraction, 0.25)

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

    def test_activity_text_is_logged(self):
        tracker = InstallProgress(1)
        tracker.handle(copy_start(2, "/nix/store/abc-hello"))
        self.assertIn("copying path '/nix/store/abc-hello", tracker.log_messages[0])

    def test_active_status_rotates_between_copy_and_build(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-firefox-1.0"))
        tracker.note_build("building '/nix/store/abc-linux-6.18.60.drv'")

        text, cursor = tracker.status_text(0)
        self.assertIn("Downloading", text)
        self.assertIn("firefox-1.0", text)

        text, cursor = tracker.status_text(cursor)
        self.assertIn("Building", text)
        self.assertIn("linux-6.18.60", text)

    def test_stopped_copy_is_removed_from_status(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.handle(copy_start(2, "/nix/store/abc-firefox-1.0"))
        tracker.handle(stop(2))
        text, _ = tracker.status_text(0)
        self.assertNotIn("Downloading", text)
        self.assertIn("Installing NixOS", text)

    def test_completed_build_is_removed_from_status(self):
        tracker = InstallProgress(10)
        tracker.start()
        tracker.note_build("building '/nix/store/abc-linux-6.18.60.drv'")
        tracker.handle(start(1, 104))
        tracker.handle(progress(1, 0, 1))
        text, _ = tracker.status_text(0)
        self.assertIn("linux-6.18.60", text)

        tracker.handle(progress(1, 1, 1))
        text, _ = tracker.status_text(0)
        self.assertNotIn("linux-6.18.60", text)


class MainImportTest(unittest.TestCase):
    def test_main_finds_sibling_progress_module(self):
        module_dir = Path(__file__).resolve().parents[1] / "modules" / "ojuny"
        fake = types.ModuleType("libcalamares")
        fake.globalstorage = types.SimpleNamespace(value=lambda *args, **kwargs: None)
        fake.job = types.SimpleNamespace(
            configuration={}, setprogress=lambda value: None
        )
        fake.utils = types.SimpleNamespace(
            debug=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
        )
        sys.modules["libcalamares"] = fake
        try:
            spec = importlib.util.spec_from_file_location(
                "ojuny_main", module_dir / "main.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop("libcalamares", None)
        self.assertTrue(hasattr(module, "InstallProgress"))


if __name__ == "__main__":
    unittest.main()
