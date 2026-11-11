"""Item-count progress for the Ojuny installer."""

import json
import re

_ACT_COPY_PATH = 100
_ACT_COPY_PATHS = 103
_ACT_BUILDS = 104
_RES_PROGRESS = 105

_STORE_PATH = re.compile(r"/nix/store/[^\s']+")


def is_install_item(path):
    name = path.rsplit("/", 1)[-1]
    return not name.endswith(".drv") and not name.endswith("-source")


def measure_closure_items(run, store, staging, hostname):
    """Return the number of installed store items in the target closure."""

    installable = (
        '{}#nixosConfigurations."{}".config.system.build.toplevel.drvPath'
    ).format(staging, hostname)
    drv_output = run(
        [
            "nix",
            "--store",
            store,
            "--extra-experimental-features",
            "nix-command flakes",
            "eval",
            "--raw",
            installable,
        ]
    )
    lines = [line.strip() for line in drv_output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("nix eval returned an empty derivation path")
    drv_path = lines[-1]

    closure_output = run(
        ["nix-store", "--store", store, "-qR", "--include-outputs", drv_path]
    )
    paths = {line.strip() for line in closure_output.splitlines() if line.strip()}
    items = {path for path in paths if is_install_item(path)}
    if not items:
        raise RuntimeError("the target system closure has no install items")
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

    def start(self):
        self._active = True
        self._done = 0
        self._fraction = 0.0
        self._copy_paths.clear()
        self._copy_items = 0
        self._build_baseline = {
            act_id: done for act_id, (done, _) in self._builds.items()
        }
        self._built_items = 0

    def handle(self, line):
        line = line.strip()
        if not line:
            return True
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
                self._copy_paths[act_id] = match.group(0)

    def _on_stop(self, message):
        act_id = message["id"]
        act_type = self._activities.pop(act_id, 0)
        path = self._copy_paths.pop(act_id, None)
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
        builds_expected = sum(expected for _, expected in self._builds.values())
        copies_done = sum(done for done, _ in self._copies.values())
        copies_expected = sum(expected for _, expected in self._copies.values())
        remaining = max(0, builds_expected - builds_done) + max(
            0, copies_expected - copies_done
        )

        grew = False
        if self._done >= self._total and remaining > 0:
            self._total = self._done + remaining
            grew = True
        elif self._done > self._total:
            self._total = self._done
            grew = True

        if self._total > 0:
            candidate = min(1.0, self._done / self._total)
            if grew:
                self._fraction = candidate
            elif candidate > self._fraction:
                self._fraction = candidate
