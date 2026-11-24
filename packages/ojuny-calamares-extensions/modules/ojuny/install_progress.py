"""Item-count progress for the Ojuny installer."""

import json
import os
import re
import time

_ACT_COPY_PATH = 100
_ACT_COPY_PATHS = 103
_ACT_BUILDS = 104
_RES_PROGRESS = 105

_STORE_PATH = re.compile(r"/nix/store/[^\s']+")


def is_install_item(path):
    name = path.rsplit("/", 1)[-1]
    return not name.endswith(".drv") and not name.endswith("-source")


def display_name(path):
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".drv"):
        name = name[:-4]
    return re.sub(r"^[a-z0-9]{32}-", "", name)


def format_elapsed(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "{}s".format(seconds)
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return "{}m {:02d}s".format(minutes, seconds)
    hours, minutes = divmod(minutes, 60)
    return "{}h {:02d}m".format(hours, minutes)


def measure_closure_items(run, store, staging, hostname, env=None):
    """Return the number of installed store items in the target closure."""

    env_prefix = list(env or [])
    installable = (
        '{}#nixosConfigurations."{}".config.system.build.toplevel.drvPath'
    ).format(staging, hostname)
    drv_output = run(
        env_prefix
        + [
            "nix",
            "eval",
            "--store",
            store,
            "--eval-store",
            store,
            "--extra-experimental-features",
            "nix-command flakes",
            "--raw",
            installable,
        ]
    )
    lines = [line.strip() for line in drv_output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("nix eval returned an empty derivation path")
    drv_path = lines[-1]

    closure_output = run(
        env_prefix
        + ["nix-store", "--store", store, "-qR", "--include-outputs", drv_path]
    )
    paths = {line.strip() for line in closure_output.splitlines() if line.strip()}
    items = {path for path in paths if is_install_item(path)}
    if not items:
        raise RuntimeError("the target system closure has no install items")
    return len(items)


def measure_realized_items(run, store, system_path):
    """Return the number of installed store items in a realised system."""

    closure_output = run(["nix-store", "--store", store, "-qR", system_path])
    paths = {line.strip() for line in closure_output.splitlines() if line.strip()}
    items = {path for path in paths if is_install_item(path)}
    if not items:
        raise RuntimeError("the realised system closure has no install items")
    return len(items)


class InstallProgress:
    """Track installed store items against a precomputed closure total."""

    def __init__(self, total=0):
        self._total = max(0, int(total))
        self._done = 0
        self._fraction = 0.0
        self._active = False
        self._activities = {}
        self._copy_paths = {}
        self._copy_items = 0
        self._builds = {}
        self._copies = {}
        self._build_baseline = {}
        self._built_items = 0
        self._active_copies = {}
        self._active_builds = []
        self._builds_done_seen = 0
        self._last_activity = time.monotonic()
        self.log_messages = []

    @property
    def total(self):
        return self._total

    @property
    def done(self):
        return self._done

    @property
    def fraction(self):
        return self._fraction

    def set_total(self, total):
        total = max(0, int(total))
        if total > self._total:
            self._total = total
        if self._total > 0:
            self._fraction = max(self._fraction, min(1.0, self._done / self._total))

    def start(self):
        self._active = True
        self._done = 0
        self._fraction = 0.0
        self._expected_known = False
        self._copy_paths.clear()
        self._copy_items = 0
        self._active_copies.clear()
        self._active_builds.clear()
        self._builds_done_seen = 0
        self._last_activity = time.monotonic()
        self._build_baseline = {
            act_id: done for act_id, (done, _) in self._builds.items()
        }
        self._built_items = 0

    def handle(self, line):
        line = line.strip()
        if not line:
            return True
        self._last_activity = time.monotonic()
        if not line.startswith("@nix "):
            return False
        try:
            message = json.loads(line[5:])
        except (json.JSONDecodeError, ValueError):
            return False

        action = message.get("action")
        if action == "start":
            self._on_start(message)
        elif action == "stop":
            self._on_stop(message)
        elif action == "result":
            self._on_result(message)
        elif action == "msg":
            level = message.get("level", 0)
            text = message.get("msg", "")
            if level <= 1 and text:
                self.log_messages.append(text)
                self.note_build(text)

        self._update()
        return True

    def _on_start(self, message):
        act_id = message["id"]
        act_type = message.get("type", 0)
        self._activities[act_id] = act_type
        text = message.get("text", "")
        if text and message.get("level", 5) <= 3:
            self.log_messages.append(text)
        if act_type == _ACT_COPY_PATH:
            match = _STORE_PATH.search(text)
            if match:
                path = match.group(0)
                self._copy_paths[act_id] = path
                self._active_copies[act_id] = {
                    "path": path,
                    "text": text,
                    "start": time.monotonic(),
                }

    def note_build(self, text):
        match = re.search(r"building '(/nix/store/[^']+)'", text)
        if not match:
            return
        path = match.group(1)
        if any(build["path"] == path for build in self._active_builds):
            return
        now = time.monotonic()
        self._active_builds.append({"path": path, "start": now})
        self._last_activity = now
        if len(self._active_builds) > 16:
            del self._active_builds[0]

    def _on_stop(self, message):
        act_id = message["id"]
        act_type = self._activities.pop(act_id, 0)
        path = self._copy_paths.pop(act_id, None)
        self._active_copies.pop(act_id, None)
        if self._active and act_type == _ACT_COPY_PATH and path and is_install_item(path):
            self._copy_items += 1

    def _on_result(self, message):
        if message.get("type", 0) != _RES_PROGRESS:
            return
        fields = message.get("fields", [])
        if len(fields) < 2:
            return
        act_id = message.get("id")
        if self._activities.get(act_id, 0) == _ACT_BUILDS:
            self._builds[act_id] = (fields[0], fields[1])
        elif self._activities.get(act_id, 0) == _ACT_COPY_PATHS:
            self._copies[act_id] = (fields[0], fields[1])

    def active_entries(self):
        now = time.monotonic()
        entries = []
        for copy in self._active_copies.values():
            action = "Downloading" if "from 'http" in copy["text"] else "Copying"
            entries.append((action, display_name(copy["path"]), now - copy["start"]))
        for build in self._active_builds:
            entries.append(("Building", display_name(build["path"]), now - build["start"]))
        return entries

    def status_text(self, cursor=0):
        entries = self.active_entries()
        if entries:
            index = cursor % len(entries)
            action, name, elapsed = entries[index]
            suffix = "item {}/{}".format(self._done, self._total) if self._total else ""
            text = "{} {} ({})".format(action, name, format_elapsed(elapsed))
            if suffix:
                text += " | " + suffix
            return text, (index + 1) % len(entries)

        suffix = "item {}/{}".format(self._done, self._total) if self._total else "starting"
        builds_done = sum(done for done, _ in self._builds.values())
        builds_expected = sum(expected for _, expected in self._builds.values())
        if builds_expected > builds_done:
            return "Building derivations ({}/{}) | {}".format(builds_done, builds_expected, suffix), 0
        idle = time.monotonic() - self._last_activity
        return "Installing NixOS ({}, no new Nix activity for {})".format(
            suffix, format_elapsed(idle)
        ), 0

    def _update(self):
        if not self._active:
            return

        self._built_items = sum(
            max(0, done - self._build_baseline.get(act_id, 0))
            for act_id, (done, _) in self._builds.items()
        )
        done = self._copy_items + self._built_items
        if done > self._done:
            self._done = done

        builds_done = sum(done for done, _ in self._builds.values())
        if builds_done > self._builds_done_seen:
            completed = builds_done - self._builds_done_seen
            self._builds_done_seen = builds_done
            for _ in range(min(completed, len(self._active_builds))):
                self._active_builds.pop(0)

        builds_expected = sum(expected for _, expected in self._builds.values())
        copies_done = sum(done for done, _ in self._copies.values())
        copies_expected = sum(expected for _, expected in self._copies.values())
        remaining = max(0, builds_expected - builds_done) + max(
            0, copies_expected - copies_done
        )

        known = self._done + remaining
        if known > self._total:
            self._total = known

        if self._total > 0:
            self._fraction = max(self._fraction, min(1.0, self._done / self._total))
