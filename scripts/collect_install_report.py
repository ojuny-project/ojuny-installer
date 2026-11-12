#!/usr/bin/env python3
"""Collect the Ojuny install report from the running live system."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PHASE_RE = re.compile(r"^\S+ \+(?P<elapsed>[0-9.]+)s PHASE (?P<name>.*)$")


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def cpu_info(root: Path) -> dict:
    text = read_text(root / "proc/cpuinfo")
    model = ""
    count = 0
    for line in text.splitlines():
        if line.startswith("model name") and not model:
            model = line.split(":", 1)[1].strip()
        if line.startswith("processor"):
            count += 1
    return {"model": model or "unknown", "cores": count or None, "threads": count or None}


def ram_info(root: Path) -> dict:
    text = read_text(root / "proc/meminfo")
    match = re.search(r"^MemTotal:\s+(\d+) kB", text, re.MULTILINE)
    return {"total_bytes": int(match.group(1)) * 1024 if match else None}


def network_info(root: Path) -> dict:
    interfaces = []
    net = root / "sys/class/net"
    if net.is_dir():
        for entry in sorted(net.iterdir()):
            if entry.name == "lo":
                continue
            speed = read_text(entry / "speed").strip()
            interfaces.append(
                {
                    "interface": entry.name,
                    "type": "wifi" if (entry / "wireless").exists() else "ethernet",
                    "link_speed_mbps": int(speed) if speed.isdigit() else None,
                    "peak_rx_bytes_per_second": 0,
                }
            )
    if interfaces:
        return interfaces[0]
    return {
        "interface": "unknown",
        "type": "unknown",
        "link_speed_mbps": None,
        "peak_rx_bytes_per_second": 0,
    }


def block_info(root: Path) -> dict:
    device = ""
    for line in read_text(root / "proc/mounts").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("/", "/mnt"):
            device = parts[0]
            break
    name = Path(device).name
    base = re.sub(r"p?\d+$", "", name)
    model = read_text(root / "sys/block" / base / "device" / "model").strip()
    return {"model": model or "unknown", "link_type": "unknown"}


def kernel_info(root: Path) -> dict:
    return {
        "release": platform.release(),
        "firmware": read_text(root / "sys/class/dmi/id/bios_version").strip() or "unknown",
    }


def template_info(source: str | None, revision: str | None) -> dict:
    if not source and not revision:
        raise ValueError("template source and revision are both missing")
    source = (source or "").strip() or "unknown"
    revision = (revision or "").strip() or "unknown"
    if revision == "unknown" and source != "unknown" and os.path.isdir(source):
        completed = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory={}".format(source),
                "-C",
                source,
                "rev-parse",
                "HEAD",
            ],
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            revision = completed.stdout.strip() or "unknown"
    return {"source": source, "revision": revision}


def flake_info(revision: str | None) -> dict:
    return {"revision": (revision or "").strip() or "unknown"}


def iso_info(root: Path, variant: str) -> dict:
    toplevel = "unknown"
    current = root / "run/current-system"
    if current.exists():
        toplevel = str(current.resolve())
    return {"variant": variant, "toplevel": toplevel, "closure_hash": ""}


def phases(root: Path) -> dict:
    result = {}
    previous = 0.0
    for line in read_text(root / "tmp/ojuny-install.log").splitlines():
        match = PHASE_RE.match(line)
        if not match:
            continue
        elapsed = float(match.group("elapsed"))
        result[match.group("name")] = round(max(elapsed - previous, 0.0), 3)
        previous = elapsed
    return result


def collect(
    root: Path,
    template_source: str | None,
    template_revision: str | None,
    variant: str,
    flake_revision: str | None = None,
) -> dict:
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "iso": iso_info(root, variant),
        "template": template_info(template_source, template_revision),
        "flake": flake_info(flake_revision),
        "environment": {
            "cpu": cpu_info(root),
            "ram": ram_info(root),
            "network": network_info(root),
            "usb": block_info(root),
            "storage": block_info(root),
            "kernel": kernel_info(root),
            "vm": None,
        },
        "phases": phases(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collect-install-report")
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--template", default=None)
    parser.add_argument("--template-revision", default=None)
    parser.add_argument("--flake-revision", default=None)
    parser.add_argument("--variant", default="unknown")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/ojuny-install-report.json"),
    )
    args = parser.parse_args(argv)
    report = collect(
        args.root,
        args.template,
        args.template_revision,
        args.variant,
        flake_revision=args.flake_revision,
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
