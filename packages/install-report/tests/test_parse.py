from __future__ import annotations

import unittest
from pathlib import Path

from ojuny_install_report.parse import (
    compute_result,
    config_fingerprint,
    load_report,
    parse_first_boot,
    parse_install_log,
    phase_durations,
)

FIXTURES = Path(__file__).parent / "fixtures"


class ParseTests(unittest.TestCase):
    def test_parse_install_log(self):
        log = parse_install_log(FIXTURES / "ojuny-install.log")
        self.assertEqual(log.started_at, "2026-11-07T12:00:00")
        self.assertIn("partitioning and mounting", log.phases)
        self.assertEqual(log.phases["installation finished"], 3045.0)
        self.assertEqual(log.last_elapsed, 3045.0)

    def test_phase_durations(self):
        log = parse_install_log(FIXTURES / "ojuny-install.log")
        phases = phase_durations(log)
        self.assertEqual(phases["partitioning and mounting"], 1.0)
        self.assertEqual(phases["disk layout ready"], 4.0)
        self.assertEqual(phases["installation finished"], 5.0)

    def test_first_boot(self):
        boot = parse_first_boot(FIXTURES / "first-boot.log")
        self.assertEqual(boot.values["kernel_start"], "2026-11-07T12:51:00Z")
        self.assertEqual(boot.values["login_ready"], "2026-11-07T12:51:40Z")

    def test_compute_result(self):
        report = load_report(FIXTURES / "install-report.json")
        log = parse_install_log(FIXTURES / "ojuny-install.log")
        boot = parse_first_boot(FIXTURES / "first-boot.log")
        result = compute_result(report, log, boot)
        self.assertEqual(result["timings"]["installer_start"], "2026-11-07T12:00:00")
        self.assertTrue(result["timings"]["disk_write_complete"].startswith("2026-11-07T12:50:45"))
        self.assertEqual(result["timings"]["first_boot"], "2026-11-07T12:51:00Z")
        self.assertTrue(result["config_fingerprint"].startswith("sha256:"))
        self.assertEqual(result["phases"]["partitioning and mounting"], 1.0)

    def test_fingerprint_is_stable(self):
        report = load_report(FIXTURES / "install-report.json")
        self.assertEqual(config_fingerprint(report), config_fingerprint(report))


if __name__ == "__main__":
    unittest.main()
