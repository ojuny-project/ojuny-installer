import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules" / "ojuny"))

import install_guard


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_guard(target_free, live_free=10 * install_guard.GiB, memory=None, table=None):
    clock = FakeClock()
    guard = install_guard.ResourceGuard(
        "/target",
        "/",
        clock=clock,
        free=lambda path: target_free if path == "/target" else live_free,
        memory=lambda: memory,
        table=lambda: table or {},
    )
    return guard, clock


def process(ppid, state="S", ticks=0):
    return {"ppid": ppid, "state": state, "ticks": ticks}


class FormatTest(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(install_guard.format_bytes(512), "512 B")
        self.assertEqual(install_guard.format_bytes(1536), "1.5 KiB")
        self.assertEqual(install_guard.format_bytes(5 * install_guard.GiB), "5.0 GiB")

    def test_format_duration(self):
        self.assertEqual(install_guard.format_duration(45), "45s")
        self.assertEqual(install_guard.format_duration(125), "2m 05s")
        self.assertEqual(install_guard.format_duration(7325), "2h 02m")

    def test_estimate_grows_with_missing_items(self):
        base = install_guard.estimate_install_bytes(0)
        self.assertEqual(base, install_guard.SCRATCH_BUDGET)
        grown = install_guard.estimate_install_bytes(10)
        self.assertEqual(
            grown, install_guard.SCRATCH_BUDGET + 10 * install_guard.MISSING_ITEM_BUDGET
        )
        self.assertGreater(grown, base)


class PreflightTest(unittest.TestCase):
    def test_accepts_enough_space(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=4 * install_guard.GiB)
        guard.preflight(install_guard.estimate_install_bytes(100))

    def test_rejects_small_target(self):
        guard, _ = make_guard(install_guard.GiB, memory=4 * install_guard.GiB)
        with self.assertRaises(install_guard.GuardFailure) as caught:
            guard.preflight()
        message = str(caught.exception)
        self.assertIn("target disk", message)
        self.assertIn("short by", message)

    def test_rejects_full_live_layer(self):
        guard, _ = make_guard(50 * install_guard.GiB, live_free=100 * install_guard.MiB)
        with self.assertRaises(install_guard.GuardFailure) as caught:
            guard.preflight()
        self.assertIn("RAM-backed", str(caught.exception))

    def test_rejects_low_memory(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=32 * install_guard.MiB)
        with self.assertRaises(install_guard.GuardFailure) as caught:
            guard.preflight()
        self.assertIn("available memory", str(caught.exception))

    def test_allows_unknown_memory(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=None)
        guard.preflight()


class RuntimeTest(unittest.TestCase):
    def test_reports_target_reserve_breach(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=4 * install_guard.GiB)
        guard.start(10)
        guard.free = lambda path: (
            512 * install_guard.MiB if path == "/target" else 50 * install_guard.GiB
        )
        reason = guard.check()
        self.assertIn("nearly full", reason)

    def test_reports_live_layer_breach(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=4 * install_guard.GiB)
        guard.start(10)
        guard.free = lambda path: (
            50 * install_guard.GiB if path == "/target" else 10 * install_guard.MiB
        )
        reason = guard.check()
        self.assertIn("RAM-backed", reason)

    def test_reports_memory_breach(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=4 * install_guard.GiB)
        guard.start(10)
        guard.memory = lambda: 32 * install_guard.MiB
        reason = guard.check()
        self.assertIn("available memory", reason)

    def test_reports_stalled_dead_build(self):
        table = {
            10: process(1, state="S", ticks=100),
            11: process(10, state="R", ticks=50),
        }
        guard, clock = make_guard(
            50 * install_guard.GiB, memory=4 * install_guard.GiB, table=table
        )
        guard.start(10)
        self.assertIsNone(guard.check())
        del table[11]
        self.assertIsNone(guard.check())
        clock.advance(install_guard.STALL_SECONDS + 10)
        reason = guard.check()
        self.assertIn("stopped responding", reason)

    def test_ignores_stall_while_build_process_is_alive(self):
        table = {
            10: process(1, state="S", ticks=100),
            11: process(10, state="R", ticks=50),
        }
        guard, clock = make_guard(
            50 * install_guard.GiB, memory=4 * install_guard.GiB, table=table
        )
        guard.start(10)
        table[11]["ticks"] = 900
        clock.advance(install_guard.STALL_SECONDS + 10)
        self.assertIsNone(guard.check())

    def test_ignores_stall_while_output_arrives(self):
        table = {
            10: process(1, state="S", ticks=100),
            11: process(10, state="R", ticks=50),
        }
        guard, clock = make_guard(
            50 * install_guard.GiB, memory=4 * install_guard.GiB, table=table
        )
        guard.start(10)
        self.assertIsNone(guard.check())
        del table[11]
        clock.advance(install_guard.STALL_SECONDS + 10)
        guard.note_activity()
        self.assertIsNone(guard.check())

    def test_ignores_silence_before_any_build_process(self):
        table = {10: process(1, state="S", ticks=100)}
        guard, clock = make_guard(
            50 * install_guard.GiB, memory=4 * install_guard.GiB, table=table
        )
        guard.start(10)
        clock.advance(install_guard.STALL_SECONDS + 10)
        self.assertIsNone(guard.check())

    def test_describe_reports_numbers(self):
        guard, _ = make_guard(50 * install_guard.GiB, memory=4 * install_guard.GiB)
        text = guard.describe()
        self.assertIn("target free", text)
        self.assertIn("live free", text)
        self.assertIn("memory available", text)


class SignalTest(unittest.TestCase):
    def test_signals_children_before_parent(self):
        table = {
            10: process(1),
            11: process(10),
            12: process(10),
            13: process(12),
        }
        calls = []
        original = install_guard.os.kill
        install_guard.os.kill = lambda pid, sig: calls.append((pid, sig))
        try:
            install_guard.signal_tree(10, 15, table)
        finally:
            install_guard.os.kill = original
        self.assertEqual(calls[-1], (10, 15))
        self.assertEqual({pid for pid, _ in calls}, {10, 11, 12, 13})


if __name__ == "__main__":
    unittest.main()
