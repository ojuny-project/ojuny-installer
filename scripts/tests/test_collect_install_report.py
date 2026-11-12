from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.collect_install_report import collect, template_info


class CollectInstallReportTests(unittest.TestCase):
    def test_collects_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "proc").mkdir()
            (root / "sys/class/net/eth0").mkdir(parents=True)
            (root / "sys/class/dmi/id").mkdir(parents=True)
            (root / "tmp").mkdir()
            (root / "proc/cpuinfo").write_text(
                "processor\t: 0\nmodel name\t: Test CPU\n"
            )
            (root / "proc/meminfo").write_text("MemTotal:       1024 kB\n")
            (root / "proc/mounts").write_text("/dev/vda1 / ext4 rw 0 0\n")
            (root / "sys/class/net/eth0/speed").write_text("1000\n")
            (root / "sys/class/dmi/id/bios_version").write_text("1.0\n")
            (root / "sys/block/vda/device").mkdir(parents=True)
            (root / "sys/block/vda/device/model").write_text("Test Disk\n")
            (root / "tmp/ojuny-install.log").write_text(
                "2026-11-07T12:00:00 +0.000s PHASE partitioning and mounting\n"
                "2026-11-07T12:00:05 +5.000s PHASE installation finished\n"
            )
            report = collect(root, "/template", "a" * 40, "offline")
            self.assertEqual(report["version"], 1)
            self.assertEqual(report["iso"]["variant"], "offline")
            self.assertEqual(report["template"]["source"], "/template")
            self.assertEqual(report["template"]["revision"], "a" * 40)
            self.assertEqual(report["flake"]["revision"], "unknown")
            self.assertEqual(report["environment"]["cpu"]["model"], "Test CPU")
            self.assertEqual(report["environment"]["ram"]["total_bytes"], 1024 * 1024)
            self.assertEqual(report["environment"]["network"]["interface"], "eth0")
            self.assertEqual(report["environment"]["storage"]["model"], "Test Disk")
            self.assertEqual(report["phases"]["partitioning and mounting"], 0.0)
            self.assertEqual(report["phases"]["installation finished"], 5.0)

    def test_writes_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "report.json"
            from scripts.collect_install_report import main

            code = main([
                "--root", str(root),
                "--output", str(output),
                "--variant", "test",
                "--template", "/template",
                "--template-revision", "b" * 40,
                "--flake-revision", "c" * 40,
            ])
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["iso"]["variant"], "test")
            self.assertEqual(payload["template"]["revision"], "b" * 40)
            self.assertEqual(payload["flake"]["revision"], "c" * 40)

    def test_template_info_preserves_supplied_identity(self):
        info = template_info("https://example.test/o/template", "d" * 40)
        self.assertEqual(info["source"], "https://example.test/o/template")
        self.assertEqual(info["revision"], "d" * 40)

    def test_template_info_rejects_missing_identity(self):
        with self.assertRaises(ValueError):
            template_info(None, None)



if __name__ == "__main__":
    unittest.main()
