from __future__ import annotations

import unittest

from ojuny_install_report.parse import compute_result, load_report, parse_first_boot, parse_install_log
from ojuny_install_report.render import render_html, render_json, render_markdown
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class RenderTests(unittest.TestCase):
    def setUp(self):
        report = load_report(FIXTURES / "install-report.json")
        log = parse_install_log(FIXTURES / "ojuny-install.log")
        boot = parse_first_boot(FIXTURES / "first-boot.log")
        self.result = compute_result(report, log, boot)

    def test_markdown(self):
        text = render_markdown(self.result)
        self.assertIn("# Install time result", text)
        self.assertIn("partitioning and mounting", text)
        self.assertIn("Config fingerprint", text)

    def test_html(self):
        text = render_html(self.result)
        self.assertIn("<!doctype html>", text)
        self.assertIn("<svg", text)
        self.assertIn("partitioning and mounting", text)

    def test_json(self):
        text = render_json(self.result)
        self.assertIn('"config_fingerprint"', text)
        self.assertIn('"phases"', text)


if __name__ == "__main__":
    unittest.main()
