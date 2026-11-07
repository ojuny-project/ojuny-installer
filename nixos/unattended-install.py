#!/usr/bin/env python3
import glob
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
from pathlib import Path

SETTINGS_PATH = "/etc/ojuny/settings.json"
FLAKE_SOURCE = "/etc/ojuny/flake"
DISKO_CONFIG = "/etc/ojuny/disk-config.nix"
MOUNT = "/mnt"
MIN_DISK_BYTES = 8 * 1024**3
OFFLINE = os.path.exists("/etc/ojuny/offline")
DISCOVERY = os.path.exists("/etc/ojuny/discovery")
INSTALL_LOG = "/tmp/ojuny-install.log"
START_TIME = time.monotonic()
TARGET_USER = None
TARGET_UID = 1000
TARGET_GID = 100
LOG_SAVED = False


def log(message):
    print(message, flush=True)


def append_log(message):
    elapsed = time.monotonic() - START_TIME
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        with open(INSTALL_LOG, "a") as handle:
            handle.write("{stamp} +{elapsed:.3f}s {message}\n".format(
                stamp=stamp, elapsed=elapsed, message=message
            ))
    except OSError:
        pass


def phase(message):
    log(message)
    append_log("PHASE " + message)


def write_install_report():
    try:
        import collect_install_report
    except ImportError:
        return
    try:
        variant = "offline" if OFFLINE else "discovery" if DISCOVERY else "online"
        report = collect_install_report.collect(Path("/"), FLAKE_SOURCE, variant)
        with open("/tmp/ojuny-install-report.json", "w") as handle:
            json.dump(report, handle, indent=2)
    except Exception as error:
        log("warning: could not collect the install report: {}".format(error))


def save_install_log():
    global LOG_SAVED
    if LOG_SAVED or not TARGET_USER:
        return
    home = os.path.join(MOUNT, "home", TARGET_USER)
    if not os.path.isdir(home):
        return
    target = os.path.join(home, "ojuny-install.log")
    try:
        shutil.copyfile(INSTALL_LOG, target)
        os.chmod(target, 0o644)
        os.chown(target, TARGET_UID, TARGET_GID)
        report = "/tmp/ojuny-install-report.json"
        if os.path.exists(report):
            target_report = os.path.join(home, "install-report.json")
            shutil.copyfile(report, target_report)
            os.chmod(target_report, 0o644)
            os.chown(target_report, TARGET_UID, TARGET_GID)
        LOG_SAVED = True
    except OSError as error:
        log("warning: could not save the install log to {}: {}".format(target, error))


def run(command):
    log("+ " + " ".join(str(part) for part in command))
    subprocess.run(command, check=True)


def output(command):
    return subprocess.check_output(command, text=True).strip()


def run_logged(command):
    log("+ " + " ".join(str(part) for part in command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in process.stdout:
        print(line, end="", flush=True)
        append_log(line.rstrip("\n"))
    code = process.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, command)


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


def mount_source(mountpoint):
    try:
        return output(["findmnt", "-no", "SOURCE", mountpoint])
    except Exception:
        return ""


def live_medium_disks():
    disks = set()
    for mountpoint in ("/iso", "/nix/.ro-store", "/nix/store"):
        source = mount_source(mountpoint)
        if not source.startswith("/dev/"):
            continue
        try:
            parents = output(["lsblk", "-no", "PKNAME", source]).splitlines()
        except Exception:
            parents = []
        if parents:
            disks.add("/dev/" + parents[0].strip())
        else:
            disks.add(os.path.realpath(source))
    return disks


def stable_disk_path(path):
    target = os.path.realpath(path)
    for candidate in sorted(glob.glob("/dev/disk/by-id/*")):
        if candidate.endswith("-part") or "-part" in os.path.basename(candidate):
            continue
        if os.path.realpath(candidate) == target:
            return candidate
    return path


def disk_candidates(settings):
    report = json.loads(
        output(
            [
                "lsblk",
                "-J",
                "-b",
                "-o",
                "NAME,PATH,TYPE,SIZE,RM,RO,TRAN,FSTYPE,MOUNTPOINTS,MODEL,PARTLABEL",
            ]
        )
    )
    live = live_medium_disks()
    candidates = []
    skipped = []

    def children(node):
        for child in node.get("children") or []:
            yield child
            yield from children(child)

    for node in report.get("blockdevices", []):
        path = node.get("path") or ""
        if node.get("type") != "disk":
            continue
        size = int(node.get("size") or 0)
        reason = None
        if node.get("rm"):
            reason = "removable or external"
        elif node.get("ro"):
            reason = "read-only"
        elif (node.get("tran") or "").lower() == "usb":
            reason = "USB or external"
        elif size < MIN_DISK_BYTES:
            reason = "smaller than 8 GiB"
        elif os.path.realpath(path) in live:
            reason = "live install medium"
        else:
            for child in children(node):
                if (child.get("fstype") or "").lower() == "vfat":
                    reason = "contains an existing vfat partition"
                    break
                if any(child.get("mountpoints") or []):
                    reason = "contains a mounted partition"
                    break
            if reason is None and any(node.get("mountpoints") or []):
                reason = "mounted"

        if reason:
            skipped.append((path or node.get("name") or "unknown", reason))
            continue
        candidates.append(
            {
                "path": stable_disk_path(path),
                "size": size,
                "model": (node.get("model") or "unknown").strip(),
            }
        )

    for path, reason in skipped:
        log("skipping {}: {}".format(path, reason))
    return candidates


def resolve_disk(settings):
    requested = settings.get("disk")
    if requested and requested != "auto":
        return requested

    candidates = disk_candidates(settings)
    if not candidates:
        raise RuntimeError(
            "no eligible target disk found; connect an internal disk without a vfat partition"
        )
    if len(candidates) == 1:
        candidate = candidates[0]
        log(
            "selected {} ({}, {:.1f} GiB)".format(
                candidate["path"], candidate["model"], candidate["size"] / 1024**3
            )
        )
        return candidate["path"]

    log("multiple eligible target disks found:")
    for index, candidate in enumerate(candidates, 1):
        log(
            "  {}) {} ({}, {:.1f} GiB)".format(
                index,
                candidate["path"],
                candidate["model"],
                candidate["size"] / 1024**3,
            )
        )
    while True:
        sys.stdout.write("Select the target disk number: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("no target disk selected")
        try:
            choice = int(line.strip())
        except ValueError:
            continue
        if 1 <= choice <= len(candidates):
            return candidates[choice - 1]["path"]


def resolve_firmware(settings):
    requested = settings.get("firmware")
    if requested and requested != "auto":
        return requested
    return "efi" if os.path.isdir("/sys/firmware/efi") else "bios"


def write_runtime_disk_config(disk):
    with open(DISKO_CONFIG) as handle:
        text = handle.read()
    if "@OJUNY_DISK@" not in text:
        return DISKO_CONFIG
    runtime_dir = "/run/ojuny"
    os.makedirs(runtime_dir, exist_ok=True)
    path = os.path.join(runtime_dir, "disk-config.nix")
    with open(path, "w") as handle:
        handle.write(text.replace("@OJUNY_DISK@", disk))
    return path


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
    url = (
        "http://127.0.0.1:5055/nix-cache-info"
        if DISCOVERY
        else "https://cache.nixos.org/nix-cache-info"
    )
    for _ in range(60):
        result = subprocess.run(
            [
                "curl",
                "-sSf",
                "--max-time",
                "5",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    if DISCOVERY:
        log("discovery cache is not answering yet, continuing with the local daemon")
        return
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
        settings.get("stateVersion") or "26.11",
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


LUKS_DEVICE_LINE = re.compile(r'boot\.initrd\.luks\.devices\."([^"]+)"\.device\s*=')


def open_crypt_devices():
    report = json.loads(output(["lsblk", "-J", "-o", "NAME,TYPE,UUID"]))
    devices = {}

    def walk(node, parent_uuid=None):
        if node.get("type") == "crypt":
            name = node.get("name")
            uuid = parent_uuid or node.get("uuid")
            if name and uuid:
                devices[name] = uuid
        for child in node.get("children") or []:
            walk(child, node.get("uuid") or parent_uuid)

    for node in report.get("blockdevices", []):
        walk(node)
    return devices


def sanitize_hardware_module(root):
    path = os.path.join(root, "modules/07-system/00-hardware.nix")
    if not os.path.exists(path):
        return
    with open(path) as handle:
        lines = handle.read().splitlines()

    defined = {}
    deduped = []
    for line in lines:
        match = LUKS_DEVICE_LINE.search(line)
        if match:
            name = match.group(1)
            if name in defined:
                if defined[name] != line.strip():
                    raise RuntimeError(
                        'conflicting boot.initrd.luks.devices."{}" definitions'.format(
                            name
                        )
                    )
                continue
            defined[name] = line.strip()
        deduped.append(line)

    crypt = open_crypt_devices()
    referenced = set(re.findall(r"/dev/mapper/([A-Za-z0-9_.+-]+)", "\n".join(deduped)))
    for name in sorted((referenced & set(crypt)) - set(defined)):
        line = 'boot.initrd.luks.devices."{}".device = "/dev/disk/by-uuid/{}";'.format(
            name, crypt[name]
        )
        deduped.append(line)
        defined[name] = line

    missing = sorted((referenced & set(crypt)) - set(defined))
    if missing:
        raise RuntimeError(
            "hardware module is missing boot.initrd.luks.devices entries for: {}".format(
                ", ".join(missing)
            )
        )
    with open(path, "w") as handle:
        handle.write("\n".join(deduped) + "\n")


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

    sanitize_hardware_module(root)

    for name in ("configuration.nix", "hardware-configuration.nix"):
        path = os.path.join(MOUNT, "etc/nixos", name)
        if os.path.exists(path):
            os.unlink(path)


def write_hardware(root, settings):
    encryption = settings.get("encryption") or {}
    root_content = (
        """{
          type = "luks";
          name = "cryptroot";
          settings.allowDiscards = true;
          passwordFile = null;
          content = {
            type = "filesystem";
            format = "ext4";
            mountpoint = "/";
          };
        }"""
        if encryption.get("enable")
        else """{
          type = "filesystem";
          format = "ext4";
          mountpoint = "/";
        }"""
    )

    swap = ""
    if settings.get("swapSize") not in (None, "0"):
        swap = """
          swap = {
            size = %s;
            priority = 3;
            content = {
              type = "swap";
            };
          };""" % nix_string(settings["swapSize"])

    disk = settings["disk"]
    firmware = settings["firmware"]
    path = os.path.join(root, "modules/07-system/00-hardware.nix")
    with open(path, "w") as handle:
        handle.write(
            """{{ self, inputs, ... }}: {{

  flake.modules.nixos.system-hardware =
    {{ lib, ... }}:
    {{
      imports = [ inputs.disko.nixosModules.disko ];

      boot.initrd.availableKernelModules = [
        "ahci"
        "dm_mod"
        "hid_generic"
        "nvme"
        "sd_mod"
        "sr_mod"
        "usb_storage"
        "usbhid"
        "xhci_pci"
      ];

      disko.devices.disk.main = {{
        device = {disk};
        type = "disk";
        content = {{
          type = "gpt";
          partitions = {{
            boot = {{
              size = "1M";
              type = "EF02";
              priority = 1;
            }};
            ESP = {{
              size = "1G";
              type = "EF00";
              priority = 2;
              content = {{
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot";
                mountOptions = [ "umask=0077" ];
              }};
            }};
            root = {{
              size = "100%";
              priority = 4;
              content = {root_content};
            }};{swap}
          }};
        }};
      }};

      boot.loader.systemd-boot.enable = lib.mkForce {efi};
      boot.loader.efi.canTouchEfiVariables = lib.mkForce {efi};
      boot.loader.grub.enable = lib.mkForce {bios};
      boot.loader.grub.devices = lib.mkIf {bios} [ {disk} ];

      ojuny.network.deploy-rs.enable = lib.mkDefault {remote};

      nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
    }};

  flake.modules.nixos.system-bootloader =
    {{ lib, ... }}:
    {{
      boot.loader.systemd-boot.enable = lib.mkDefault false;
      boot.loader.efi.canTouchEfiVariables = lib.mkDefault false;
      boot.loader.grub.enable = lib.mkDefault false;
      boot.loader.grub.devices = lib.mkDefault [ ];
    }};

}}
""".format(
                disk=nix_string(disk),
                root_content=root_content,
                swap=swap,
                efi="true" if firmware == "efi" else "false",
                bios="true" if firmware == "bios" else "false",
                remote="true",
            )
        )


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


def rewrite_offline_inputs(flake):
    mapping_path = "/etc/ojuny/flake-input-paths"
    lock_path = os.path.join(flake, "flake.lock")
    if not os.path.exists(mapping_path) or not os.path.exists(lock_path):
        return None
    with open(mapping_path) as handle:
        mapping = json.load(handle)
    if not mapping:
        return None
    with open(lock_path) as handle:
        original = handle.read()
    lock = json.loads(original)
    for name, path in mapping.items():
        node = lock.get("nodes", {}).get(name)
        if node is None or "locked" not in node:
            continue
        nar_hash = output(
            [
                "nix",
                "--extra-experimental-features",
                "nix-command",
                "hash",
                "path",
                "--sri",
                path,
            ]
        )
        node["locked"] = {"type": "path", "path": path, "narHash": nar_hash}
    with open(lock_path, "w") as handle:
        json.dump(lock, handle, indent=2)
        handle.write("\n")
    log("rewrote {} flake inputs for offline evaluation".format(len(mapping)))
    return lock_path, original


def restore_offline_inputs(rewrite):
    if rewrite is None:
        return
    lock_path, original = rewrite
    with open(lock_path, "w") as handle:
        handle.write(original)


def install():
    global START_TIME, LOG_SAVED, TARGET_USER, TARGET_UID, TARGET_GID
    START_TIME = time.monotonic()
    LOG_SAVED = False
    try:
        open(INSTALL_LOG, "w").close()
    except OSError:
        pass
    append_log("Ojuny unattended installer")
    append_log("started={}".format(time.strftime("%Y-%m-%d %H:%M:%S")))

    settings = read_settings()
    disk = resolve_disk(settings)
    firmware = resolve_firmware(settings)
    settings["disk"] = disk
    settings["firmware"] = firmware
    mode = settings["mode"]
    clone_relative = settings.get("cloneRelative") or "repos/nix-flake"
    append_log("mode={}".format(mode))
    append_log("disk={}".format(disk))
    append_log("firmware={}".format(firmware))
    append_log("offline={}".format(OFFLINE))
    append_log("discovery={}".format(DISCOVERY))

    validate_disk(disk)
    confirm(disk, settings.get("confirmSeconds", 10))
    if not OFFLINE:
        wait_for_network()

    phase("partitioning and mounting")
    disk_config = write_runtime_disk_config(disk)
    run(
        [
            "disko",
            "--mode",
            "destroy,format,mount",
            "--root-mountpoint",
            MOUNT,
            disk_config,
        ]
    )
    phase("disk layout ready")

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
    TARGET_USER = username
    append_log("username={}".format(username))
    append_log("hostname={}".format(host))

    phase("preparing target flake")

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
    append_log("hostname={}".format(host))

    phase("applying settings and hardware")
    apply_settings(target, settings, username, host, runtime_flake)
    regenerate_hardware(target, firmware, disk)
    write_hardware(target, settings)
    git_init(target)

    if OFFLINE:
        phase("preloading offline store")
        preload_store_paths(MOUNT)

    phase("installing NixOS from {}#{}".format(target, host))
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
    offline_rewrite = rewrite_offline_inputs(target) if OFFLINE else None
    try:
        run_logged(install_command)
    finally:
        restore_offline_inputs(offline_rewrite)
    phase("nixos-install finished")

    shell = detect_shell(target)
    home = os.path.join(MOUNT, "home", username)
    write_gui_config(home, runtime_flake, host, shell)

    uid, gid = lookup_ids(username)
    TARGET_UID = uid
    TARGET_GID = gid
    chown_tree(home, uid, gid)

    phase("collecting install report")
    write_install_report()

    phase("saving install log")
    save_install_log()

    unmount()

    phase("installation finished")
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
    except Exception as error:
        append_log("ERROR: {}".format(error))
        append_log(traceback.format_exc())
        traceback.print_exc()
        save_install_log()
        log("installation failed, starting a shell on tty1")
        failure_shell()


if __name__ == "__main__":
    main()
