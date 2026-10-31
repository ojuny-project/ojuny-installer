#!/usr/bin/env python3
import json
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import time
import traceback

SETTINGS_PATH = "/etc/ojuny/settings.json"
FLAKE_SOURCE = "/etc/ojuny/flake"
DISKO_CONFIG = "/etc/ojuny/disk-config.nix"
MOUNT = "/mnt"
MIN_DISK_BYTES = 8 * 1024**3
OFFLINE = os.path.exists("/etc/ojuny/offline")


def log(message):
    print(message, flush=True)


def run(command):
    log("+ " + " ".join(str(part) for part in command))
    subprocess.run(command, check=True)


def output(command):
    return subprocess.check_output(command, text=True).strip()


def nix_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def replace_once(text, pattern, replacement, label):
    result, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        log("warning: could not set {}".format(label))
    return result


def read_settings():
    with open(SETTINGS_PATH) as handle:
        return json.load(handle)


def wait_for_disk(disk):
    for _ in range(120):
        if os.path.exists(disk):
            return
        time.sleep(1)
    raise RuntimeError("target disk did not appear: {}".format(disk))


def is_mounted(disk):
    real = os.path.realpath(disk)
    with open("/proc/mounts") as handle:
        for line in handle:
            source = line.split()[0]
            if source == real or source.startswith(real):
                return True
    return False


def validate_disk(disk):
    wait_for_disk(disk)

    if not stat.S_ISBLK(os.stat(disk).st_mode):
        raise RuntimeError("not a block device: {}".format(disk))

    if is_mounted(disk):
        raise RuntimeError("refusing to wipe mounted disk: {}".format(disk))

    size = int(output(["blockdev", "--getsize64", disk]))
    if size < MIN_DISK_BYTES:
        raise RuntimeError(
            "target disk is smaller than 8 GiB: {} ({} bytes)".format(disk, size)
        )

    log("target disk: {}".format(disk))
    log("target size: {:.1f} GiB".format(size / 1024**3))


def confirm(disk, seconds):
    if seconds is None or int(seconds) <= 0:
        return

    seconds = int(seconds)
    log("wiping {} in {} seconds, press Enter to cancel".format(disk, seconds))
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if ready:
        sys.stdin.readline()
        raise RuntimeError("cancelled by user")


def wait_for_network():
    for _ in range(60):
        result = subprocess.run(
            [
                "curl",
                "-sSf",
                "--max-time",
                "5",
                "https://cache.nixos.org/nix-cache-info",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("network is not available")


def detect_username(root):
    path = os.path.join(root, "modules/01-users/01-user.nix")
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        match = re.search(
            r'users\.users\s*=\s*\{\s*(?:"([^"]+)"|([A-Za-z0-9_][A-Za-z0-9_-]*))\s*=',
            handle.read(),
        )
    if not match:
        return None
    return match.group(1) or match.group(2)


def detect_host(root):
    path = os.path.join(root, "modules/07-system/00-host.nix")
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        match = re.search(r"nixosConfigurations\.([A-Za-z0-9._-]+)\s*=", handle.read())
    return match.group(1) if match else None


def detect_shell(root):
    path = os.path.join(root, "modules/01-users/01-user.nix")
    if not os.path.exists(path):
        return "zsh"
    with open(path) as handle:
        match = re.search(r'shell\s*=\s*pkgs\.([A-Za-z0-9_-]+)\s*;', handle.read())
    return match.group(1) if match else "zsh"


def clean_flake(target):
    for name in (".git", ".direnv", "result", "result-1"):
        path = os.path.join(target, name)
        if os.path.islink(path) or os.path.isfile(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)


def copy_flake(target):
    if os.path.exists(target):
        shutil.rmtree(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copytree(FLAKE_SOURCE, target, symlinks=True)
    run(["chmod", "-R", "u+w", target])
    clean_flake(target)


def prepare_bundled(target, settings, username, host):
    command = [
        "prepare-repo",
        "--root",
        target,
        "--template",
        FLAKE_SOURCE,
        "--username",
        username,
        "--fullname",
        settings.get("fullName") or username,
        "--hashed-password",
        settings.get("hashedPassword") or "!",
        "--shell",
        settings.get("shell") or "zsh",
        "--hostname",
        host,
        "--state-version",
        settings.get("stateVersion") or "25.05",
        "--clone-relative",
        settings.get("cloneRelative") or "repos/nix-flake",
        "--force",
    ]

    if settings.get("timezone"):
        command += ["--timezone", settings["timezone"]]
    if settings.get("locale"):
        command += ["--locale", settings["locale"]]
    if settings.get("keymap"):
        command += ["--keymap", settings["keymap"]]

    run(command)


def apply_settings(root, settings, username, host, runtime_flake):
    apply_user_settings(root, settings)
    apply_config_settings(root, settings, host)
    apply_host_settings(root, runtime_flake)


def apply_user_settings(root, settings):
    path = os.path.join(root, "modules/01-users/01-user.nix")
    if not os.path.exists(path):
        return

    with open(path) as handle:
        text = handle.read()

    if settings.get("hashedPassword") is not None:
        text = replace_once(
            text,
            r'hashedPassword\s*=\s*"[^"]*";',
            "hashedPassword = {};".format(nix_string(settings["hashedPassword"])),
            "hashedPassword",
        )

    keys = settings.get("sshKeys") or []
    if keys:
        block = "[\n" + "".join(
            "      {}\n".format(nix_string(key)) for key in keys
        ) + "    ]"
        text = replace_once(
            text,
            r"openssh\.authorizedKeys\.keys\s*=\s*\[[^\]]*\];",
            "openssh.authorizedKeys.keys = {};".format(block),
            "SSH keys",
        )

    if settings.get("shell"):
        text = replace_once(
            text,
            r'shell\s*=\s*pkgs\.[A-Za-z0-9_-]+\s*;',
            "shell = pkgs.{};".format(settings["shell"]),
            "shell",
        )

    with open(path, "w") as handle:
        handle.write(text)


def apply_config_settings(root, settings, host):
    path = os.path.join(root, "modules/07-system/01-configuration.nix")
    if not os.path.exists(path):
        return

    with open(path) as handle:
        text = handle.read()

    if host:
        text = replace_once(
            text,
            r'networking\.hostName\s*=\s*"[^"]*";',
            "networking.hostName = {};".format(nix_string(host)),
            "hostname",
        )

    if settings.get("timezone"):
        text = replace_once(
            text,
            r'time\.timeZone\s*=\s*"[^"]*";',
            "time.timeZone = {};".format(nix_string(settings["timezone"])),
            "time zone",
        )

    if settings.get("locale"):
        text = replace_once(
            text,
            r'i18n\.defaultLocale\s*=\s*"[^"]*";',
            "i18n.defaultLocale = {};".format(nix_string(settings["locale"])),
            "locale",
        )

    if settings.get("keymap"):
        text = replace_once(
            text,
            r'console\.keyMap\s*=\s*"[^"]*";',
            "console.keyMap = {};".format(nix_string(settings["keymap"])),
            "console keymap",
        )

    with open(path, "w") as handle:
        handle.write(text)


def apply_host_settings(root, runtime_flake):
    path = os.path.join(root, "modules/07-system/00-host.nix")
    if not os.path.exists(path):
        return

    with open(path) as handle:
        text = handle.read()

    text = replace_once(
        text,
        r'services\.simple-nix-update-gui\.flakeUri\s*=\s*lib\.mkDefault\s*"[^"]*";',
        "services.simple-nix-update-gui.flakeUri = lib.mkDefault {};".format(
            nix_string("path:" + runtime_flake)
        ),
        "update GUI flake URI",
    )
    text = replace_once(
        text,
        r'services\.simple-nix-update-gui\.clonePath\s*=\s*lib\.mkDefault\s*"[^"]*";',
        "services.simple-nix-update-gui.clonePath = lib.mkDefault {};".format(
            nix_string(runtime_flake)
        ),
        "update GUI clone path",
    )

    with open(path, "w") as handle:
        handle.write(text)


def regenerate_hardware(root, firmware, disk):
    command = [
        "regenerate-hardware",
        "--root",
        root,
        "--target-root",
        MOUNT,
        "--firmware",
        firmware,
    ]
    if firmware == "bios":
        command += ["--boot-device", os.path.realpath(disk)]
    run(command)

    for name in ("configuration.nix", "hardware-configuration.nix"):
        path = os.path.join(MOUNT, "etc/nixos", name)
        if os.path.exists(path):
            os.unlink(path)


def git_init(root):
    run(["git", "-C", root, "init", "-q"])
    run(["git", "-C", root, "add", "-A"])
    run(
        [
            "git",
            "-C",
            root,
            "-c",
            "user.name=Ojuny Installer",
            "-c",
            "user.email=installer@ojuny.local",
            "commit",
            "-qm",
            "Initial Ojuny configuration",
        ]
    )


def write_gui_config(home, flake, host, shell):
    config_dir = os.path.join(home, ".config", "nix-settings-gui")
    os.makedirs(config_dir, exist_ok=True)
    payload = {
        "flake_path": flake,
        "terminal_command": "ghostty -e {} -c".format(shell),
        "rebuild_command": 'sudo echo "starting rebuild"; sudo nixos-rebuild boot --flake {}#{}'.format(
            flake, host
        ),
        "reload_dms_on_rebuild": True,
    }
    with open(os.path.join(config_dir, "config.json"), "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def lookup_ids(username):
    with open(os.path.join(MOUNT, "etc/passwd")) as handle:
        for line in handle:
            fields = line.strip().split(":")
            if len(fields) >= 4 and fields[0] == username:
                return int(fields[2]), int(fields[3])
    raise RuntimeError("user not found after install: {}".format(username))


def chown_tree(path, uid, gid):
    os.lchown(path, uid, gid)
    for current, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            os.lchown(os.path.join(current, name), uid, gid)


def unmount():
    subprocess.run(["umount", "-R", MOUNT], check=False)


def preload_store_paths(mount):
    paths = []
    for name in ("/etc/ojuny/flake-inputs", "/etc/ojuny/target-toplevels"):
        if not os.path.exists(name):
            continue
        with open(name) as handle:
            paths += [line.strip() for line in handle if line.strip()]

    if not paths:
        return

    log("preloading {} store paths".format(len(paths)))
    run(["nix", "copy", "--no-check-sigs", "--to", mount] + paths)


def install():
    settings = read_settings()
    disk = settings["disk"]
    firmware = settings["firmware"]
    mode = settings["mode"]
    clone_relative = settings.get("cloneRelative") or "repos/nix-flake"

    validate_disk(disk)
    confirm(disk, settings.get("confirmSeconds", 10))
    if not OFFLINE:
        wait_for_network()

    run(
        [
            "disko",
            "--mode",
            "destroy,format,mount",
            "--root-mountpoint",
            MOUNT,
            DISKO_CONFIG,
        ]
    )

    source_user = detect_username(FLAKE_SOURCE)

    if mode == "prepared":
        username = settings.get("username") or source_user
        if not username:
            raise RuntimeError("could not detect a username in the prepared flake")
        if settings.get("username") and source_user and settings["username"] != source_user:
            raise RuntimeError(
                "configured username {} does not match the prepared flake user {}".format(
                    settings["username"], source_user
                )
            )
        host = settings.get("host")
    else:
        username = settings.get("username") or "user"
        host = settings.get("host") or "ojuny"

    target = os.path.join(MOUNT, "home", username, clone_relative)
    runtime_flake = os.path.join("/home", username, clone_relative)

    log("installing flake to {}".format(runtime_flake))

    if mode == "bundled":
        if os.path.exists(target):
            shutil.rmtree(target)
        prepare_bundled(target, settings, username, host)
        clean_flake(target)
    else:
        copy_flake(target)

    target_user = detect_username(target)
    if target_user and target_user != username:
        raise RuntimeError(
            "installed user {} does not match target path user {}".format(
                target_user, username
            )
        )

    target_host = detect_host(target)
    if mode == "prepared":
        if settings.get("host") and target_host and settings["host"] != target_host:
            raise RuntimeError(
                "configured host {} does not match the prepared flake host {}".format(
                    settings["host"], target_host
                )
            )
        host = target_host or settings.get("host")
    else:
        host = target_host or host

    if not host:
        raise RuntimeError("could not determine the target host")

    apply_settings(target, settings, username, host, runtime_flake)
    regenerate_hardware(target, firmware, disk)
    git_init(target)

    if OFFLINE:
        preload_store_paths(MOUNT)

    log("installing NixOS from {}#{}".format(target, host))
    install_command = [
        "nixos-install",
        "--no-root-passwd",
        "--root",
        MOUNT,
        "--flake",
        "{}#{}".format(target, host),
        "--option",
        "build-dir",
        "/nix/var/nix/builds",
    ]
    if OFFLINE:
        install_command += ["--option", "substituters", "auto?trusted=1"]
    run(install_command)

    shell = detect_shell(target)
    home = os.path.join(MOUNT, "home", username)
    write_gui_config(home, runtime_flake, host, shell)

    uid, gid = lookup_ids(username)
    chown_tree(home, uid, gid)

    unmount()

    log("install complete")
    log("configuration: {}".format(runtime_flake))
    log("rebooting" if settings.get("finalAction") == "reboot" else "powering off")

    subprocess.run(["sync"], check=False)
    subprocess.run(["systemctl", settings.get("finalAction") or "reboot"], check=False)


def failure_shell():
    try:
        tty = os.open("/dev/tty1", os.O_RDWR)
        os.dup2(tty, 0)
        os.dup2(tty, 1)
        os.dup2(tty, 2)
    except OSError:
        pass
    os.execv("/bin/bash", ["/bin/bash", "-i"])


def main():
    log("Ojuny unattended installation starting")
    try:
        install()
    except Exception:
        traceback.print_exc()
        log("installation failed, starting a shell on tty1")
        failure_shell()


if __name__ == "__main__":
    main()
