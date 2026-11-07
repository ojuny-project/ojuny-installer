from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

LOG_RE = re.compile(r"^(?P<timestamp>\S+) \+(?P<elapsed>[0-9]+(?:\.[0-9]+)?)s (?P<message>.*)$")
PHASE_PREFIX = "PHASE "


class ParseError(ValueError):
    pass


@dataclass
class InstallLog:
    started_at: str
    phases: dict[str, float]
    last_elapsed: float


@dataclass
class FirstBoot:
    values: dict[str, str]


def parse_install_log(path: Path) -> InstallLog:
    phases: dict[str, float] = {}
    started_at: str | None = None
    last_elapsed = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOG_RE.match(line)
        if not match:
            continue
        if started_at is None:
            started_at = match.group("timestamp")
        last_elapsed = float(match.group("elapsed"))
        message = match.group("message")
        if message.startswith(PHASE_PREFIX):
            phases[message[len(PHASE_PREFIX) :]] = last_elapsed
    if started_at is None:
        raise ParseError(f"no timestamped lines in {path}")
    return InstallLog(started_at=started_at, phases=phases, last_elapsed=last_elapsed)


def parse_first_boot(path: Path) -> FirstBoot:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return FirstBoot(values=values)


def load_report(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ParseError(f"{path} must contain a JSON object")
    return data


def phase_durations(log: InstallLog) -> dict[str, float]:
    durations: dict[str, float] = {}
    previous = 0.0
    for name, elapsed in log.phases.items():
        durations[name] = round(max(elapsed - previous, 0.0), 3)
        previous = elapsed
    return durations


def config_fingerprint(report: dict) -> str:
    payload = {
        "iso": report.get("iso"),
        "template": report.get("template"),
        "environment": report.get("environment"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def compute_result(report: dict, log: InstallLog, first_boot: FirstBoot) -> dict:
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": "install-report.json",
        "config_fingerprint": config_fingerprint(report),
        "timings": {
            "installer_start": log.started_at,
            "disk_write_complete": _add_seconds(log.started_at, log.last_elapsed),
            "first_boot": first_boot.values.get("kernel_start"),
            "login_ready": first_boot.values.get("login_ready"),
        },
        "phases": phase_durations(log),
    }


def _add_seconds(timestamp: str, seconds: float) -> str:
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    return (parsed + timedelta(seconds=seconds)).isoformat()
