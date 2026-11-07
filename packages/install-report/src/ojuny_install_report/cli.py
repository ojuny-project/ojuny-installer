from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parse import ParseError, compute_result, load_report, parse_first_boot, parse_install_log
from .render import render_html, render_json, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install-report",
        description="Turn Ojuny install logs into a result",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="directory with ojuny-install.log, install-report.json and first-boot.log",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output_dir or args.input
    try:
        report = load_report(args.input / "install-report.json")
        log = parse_install_log(args.input / "ojuny-install.log")
        first_boot = parse_first_boot(args.input / "first-boot.log")
    except (FileNotFoundError, ParseError) as error:
        print(f"install-report: {error}", file=sys.stderr)
        return 2
    result = compute_result(report, log, first_boot)
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(render_json(result), encoding="utf-8")
    (output / "result.md").write_text(render_markdown(result), encoding="utf-8")
    (output / "result.html").write_text(render_html(result), encoding="utf-8")
    print(f"wrote {output / 'result.json'}, {output / 'result.md'} and {output / 'result.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
