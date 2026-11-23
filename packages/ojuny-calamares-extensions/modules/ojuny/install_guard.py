"""Resource contract and supervision for install-time builds.

The guard is deliberately free of Calamares imports so the attended and
unattended installers can share it and the tests can drive it directly.
"""

import os
import time

GiB = 1024 ** 3
MiB = 1024 ** 2

TARGET_RESERVE = 1 * GiB
MINIMUM_TARGET_FREE = 5 * GiB
SCRATCH_BUDGET = 4 * GiB
MISSING_ITEM_BUDGET = 8 * MiB
LIVE_RESERVE = 256 * MiB
MINIMUM_MEMORY_AVAILABLE = 64 * MiB
STALL_SECONDS = 300


class GuardFailure(RuntimeError):
    """The install cannot continue safely."""


def format_bytes(value):
    value = float(max(0, int(value)))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            if unit == "B":
                return "{} B".format(int(value))
            return "{:.1f} {}".format(value, unit)
        value /= 1024
    return "{:.1f} TiB".format(value)


def format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "{}h {:02d}m".format(hours, minutes)
    if minutes:
        return "{}m {:02d}s".format(minutes, seconds)
    return "{}s".format(seconds)


def free_bytes(path):
    try:
        stats = os.statvfs(path)
    except OSError:
        return 0
    return stats.f_bavail * stats.f_frsize


def memory_available_bytes(path="/proc/meminfo"):
    try:
        with open(path) as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def process_table(path="/proc"):
    table = {}
    try:
        names = os.listdir(path)
    except OSError:
        return table
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(path, name, "stat")) as handle:
                data = handle.read()
        except OSError:
            continue
        if ")" not in data:
            continue
        fields = data.rsplit(")", 1)[1].split()
        if len(fields) < 13:
            continue
        try:
            table[int(name)] = {
                "ppid": int(fields[1]),
                "state": fields[0],
                "ticks": int(fields[11]) + int(fields[12]),
            }
        except ValueError:
            continue
    return table


def descendants(pid, table):
    children = {}
    for child, info in table.items():
        children.setdefault(info["ppid"], []).append(child)
    result = set()
    queue = [pid]
    while queue:
        current = queue.pop()
        for child in children.get(current, []):
            if child not in result:
                result.add(child)
                queue.append(child)
    return result


def live_descendants(pid, table):
    return {
        child
        for child in descendants(pid, table)
        if table[child]["state"] not in ("Z", "X")
    }


def estimate_install_bytes(
    missing_items=0,
    scratch_bytes=SCRATCH_BUDGET,
    item_bytes=MISSING_ITEM_BUDGET,
):
    return max(0, int(missing_items)) * item_bytes + scratch_bytes


def signal_tree(pid, sig, table=None):
    table = process_table() if table is None else table
    for child in reversed(sorted(descendants(pid, table))):
        try:
            os.kill(child, sig)
        except (ProcessLookupError, PermissionError):
            continue
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        return


class ResourceGuard:
    def __init__(
        self,
        target_root,
        live_root="/",
        clock=time.monotonic,
        free=free_bytes,
        memory=memory_available_bytes,
        table=process_table,
        target_reserve=TARGET_RESERVE,
        minimum_target_free=MINIMUM_TARGET_FREE,
        live_reserve=LIVE_RESERVE,
        minimum_memory=MINIMUM_MEMORY_AVAILABLE,
        stall_seconds=STALL_SECONDS,
    ):
        self.target_root = target_root
        self.live_root = live_root
        self.clock = clock
        self.free = free
        self.memory = memory
        self.table = table
        self.target_reserve = target_reserve
        self.minimum_target_free = minimum_target_free
        self.live_reserve = live_reserve
        self.minimum_memory = minimum_memory
        self.stall_seconds = stall_seconds
        self._pid = None
        self._last_activity = 0.0
        self._last_ticks = None
        self._saw_descendants = False

    def preflight(self, required_bytes=0):
        target_free = self.free(self.target_root)
        required = max(self.minimum_target_free, required_bytes) + self.target_reserve
        if target_free < required:
            raise GuardFailure(
                "The target disk does not have enough free space to start the "
                "install. {} free, {} needed, short by {}. Free space or use a "
                "larger target disk.".format(
                    format_bytes(target_free),
                    format_bytes(required),
                    format_bytes(required - target_free),
                )
            )

        live_free = self.free(self.live_root)
        if live_free < self.live_reserve:
            raise GuardFailure(
                "The live installer has almost no space left in its RAM-backed "
                "filesystem. {} free, and at least {} is needed. Reboot from the "
                "installer and close other applications before installing.".format(
                    format_bytes(live_free), format_bytes(self.live_reserve)
                )
            )

        memory = self.memory()
        if memory is not None and memory < self.minimum_memory:
            raise GuardFailure(
                "The live installer has only {} of available memory. Reboot from "
                "the installer and close other applications before installing.".format(
                    format_bytes(memory)
                )
            )

    def start(self, pid):
        self._pid = pid
        self._last_activity = self.clock()
        self._last_ticks = self._tree_ticks(self.table())

    def note_activity(self):
        self._last_activity = self.clock()

    def check(self):
        target_free = self.free(self.target_root)
        if target_free < self.target_reserve:
            return (
                "The target disk is nearly full: {} free, and the installer "
                "keeps {} in reserve. The build cannot continue safely.".format(
                    format_bytes(target_free), format_bytes(self.target_reserve)
                )
            )

        live_free = self.free(self.live_root)
        if live_free < self.live_reserve:
            return (
                "The live installer's RAM-backed filesystem is full: {} free. "
                "The install cannot continue on this machine.".format(
                    format_bytes(live_free)
                )
            )

        memory = self.memory()
        if memory is not None and memory < self.minimum_memory:
            return (
                "The machine has only {} of available memory left. The install "
                "cannot continue safely.".format(format_bytes(memory))
            )

        if self._pid is not None:
            table = self.table()
            live = live_descendants(self._pid, table)
            if live:
                self._saw_descendants = True
            ticks = self._tree_ticks(table)
            stalled = self.clock() - self._last_activity
            if (
                self._saw_descendants
                and not live
                and ticks == self._last_ticks
                and stalled >= self.stall_seconds
            ):
                return (
                    "The build stopped responding: no output and no build process "
                    "for {}. This usually means the build ran out of disk space or "
                    "memory before finishing.".format(format_duration(stalled))
                )
            self._last_ticks = ticks

        return None

    def describe(self):
        parts = [
            "target free {}".format(format_bytes(self.free(self.target_root))),
            "live free {}".format(format_bytes(self.free(self.live_root))),
        ]
        memory = self.memory()
        if memory is not None:
            parts.append("memory available {}".format(format_bytes(memory)))
        if self._pid is not None:
            parts.append(
                "build processes {}".format(
                    len(live_descendants(self._pid, self.table()))
                )
            )
        return ", ".join(parts)

    def _tree_ticks(self, table):
        if self._pid is None:
            return 0
        total = table.get(self._pid, {}).get("ticks", 0)
        for pid in descendants(self._pid, table):
            total += table[pid]["ticks"]
        return total
