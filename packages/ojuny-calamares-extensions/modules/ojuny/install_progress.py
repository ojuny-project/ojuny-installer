"""Item-count progress for the Ojuny installer."""

import json

_ACT_COPY_PATHS = 103
_ACT_BUILDS = 104
_RES_PROGRESS = 105


def measure_closure_items(run, staging, hostname):
    """Return the number of unique store paths in the target system closure."""

    installable = (
        '{}#nixosConfigurations."{}".config.system.build.toplevel.drvPath'
    ).format(staging, hostname)
    drv_output = run(
        [
            "nix",
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

    closure_output = run(["nix-store", "-qR", "--include-outputs", drv_path])
    paths = {line.strip() for line in closure_output.splitlines() if line.strip()}
    if not paths:
        raise RuntimeError("the target system closure is empty")
    return len(paths)


class InstallProgress:
    """Track completed store items against a precomputed closure total."""

    def __init__(self, total=0):
        self._total = max(0, int(total))
        self._done = 0
        self._fraction = 0.0
        self._per_act_progress = {}
        self._activities = {}
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
            self._activities[message["id"]] = message.get("type", 0)
        elif action == "stop":
            self._activities.pop(message["id"], None)
        elif action == "result":
            self._on_result(message)
        elif action == "msg":
            level = message.get("level", 0)
            text = message.get("msg", "")
            if level <= 1 and text:
                self.log_messages.append(text)

        self._update()
        return True

    def _on_result(self, message):
        if message.get("type", 0) != _RES_PROGRESS:
            return
        fields = message.get("fields", [])
        if len(fields) < 2:
            return
        act_id = message.get("id")
        act_type = self._activities.get(act_id, 0)
        if act_type == _ACT_BUILDS:
            kind = "builds"
        elif act_type == _ACT_COPY_PATHS:
            kind = "copies"
        else:
            return
        self._per_act_progress[(act_type, act_id)] = (kind, fields[0], fields[1])

    def _update(self):
        builds_done = builds_expected = 0
        copies_done = copies_expected = 0
        for kind, done, expected in self._per_act_progress.values():
            if kind == "builds":
                builds_done += done
                builds_expected += expected
            else:
                copies_done += done
                copies_expected += expected

        live_total = builds_expected + copies_expected
        if live_total > self._total:
            self._total = live_total

        done = builds_done + copies_done
        if done > self._done:
            self._done = done

        if self._total > 0:
            candidate = min(1.0, self._done / self._total)
            if candidate > self._fraction:
                self._fraction = candidate
        elif self._done > 0:
            self._fraction = 1.0
