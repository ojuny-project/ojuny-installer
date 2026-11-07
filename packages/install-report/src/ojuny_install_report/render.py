from __future__ import annotations

import html
import json


def render_json(result: dict) -> str:
    return json.dumps(result, indent=2) + "\n"


def render_markdown(result: dict) -> str:
    lines = [
        "# Install time result",
        "",
        f"- Config fingerprint: `{result['config_fingerprint']}`",
        "",
        "| Timing | Value |",
        "| --- | --- |",
    ]
    for key, value in result["timings"].items():
        lines.append(f"| {key} | {value or 'unknown'} |")
    lines += ["", "## Phases", "", "| Phase | Seconds |", "| --- | --- |"]
    for name, seconds in result["phases"].items():
        lines.append(f"| {name} | {seconds:.1f} |")
    return "\n".join(lines) + "\n"


def render_html(result: dict) -> str:
    phases = result["phases"]
    max_seconds = max(phases.values(), default=1.0) or 1.0
    row_height = 28
    width = 640
    chart_width = width - 220
    rows = []
    for index, (name, seconds) in enumerate(phases.items()):
        bar_width = max(int((seconds / max_seconds) * chart_width), 1)
        y = index * row_height
        rows.append(
            f'<text x="0" y="{y + 18}" font-size="13">{html.escape(name)}</text>'
            f'<rect x="210" y="{y + 5}" width="{bar_width}" height="18" fill="#4c7a9b" />'
            f'<text x="{220 + bar_width}" y="{y + 18}" font-size="12">{seconds:.1f}s</text>'
        )
    chart_height = max(len(phases) * row_height, row_height)
    timing_rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(value or 'unknown')}</td></tr>"
        for key, value in result["timings"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ojuny install time result</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; color: #1f2933; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
td, th {{ border: 1px solid #cbd2d9; padding: 0.4rem 0.6rem; text-align: left; }}
code {{ background: #f5f7fa; padding: 0.1rem 0.3rem; }}
</style>
</head>
<body>
<h1>Ojuny install time result</h1>
<p>Config fingerprint: <code>{html.escape(result["config_fingerprint"])}</code></p>
<table><thead><tr><th>Timing</th><th>Value</th></tr></thead><tbody>{timing_rows}</tbody></table>
<h2>Phases</h2>
<svg width="{width}" height="{chart_height}" role="img" aria-label="Phase durations">
{''.join(rows)}
</svg>
</body>
</html>
"""
