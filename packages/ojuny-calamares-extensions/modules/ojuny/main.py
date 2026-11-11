import configparser
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import libcalamares

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flake_structure
from install_progress import InstallProgress, measure_closure_items


def pretty_name():
    return "Installing Ojuny"


status = pretty_name()

INSTALL_LOG = "/tmp/ojuny-install.log"
START_TIME = time.monotonic()
TARGET_ROOT = None
TARGET_USER = None
TEMPLATE_PATH = None
LOG_SAVED = False

PROGRESS_ITEMS_START = 0.20
PROGRESS_ITEMS_END = 0.95

ESP_PARTTYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
XBOOTLDR_PARTTYPE = "bc13c2ff-59e6-4262-a352-b275fd6f7172"



def pretty_status_message():
    return status


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
    append_log("PHASE " + message)
    libcalamares.utils.debug("Ojuny: " + message)


def write_install_report():
    try:
        import collect_install_report
    except ImportError:
        return
    try:
        report = collect_install_report.collect(Path("/"), TEMPLATE_PATH, "calamares")
        with open("/tmp/ojuny-install-report.json", "w") as handle:
            json.dump(report, handle, indent=2)
    except Exception as error:
        libcalamares.utils.warning(
            "could not collect the install report: {}".format(error)
        )


def save_install_log():
    global LOG_SAVED
    if LOG_SAVED or not TARGET_ROOT or not TARGET_USER:
        return
    home = os.path.join(TARGET_ROOT, "home", TARGET_USER)
    if not os.path.isdir(home):
        return
    target = os.path.join(home, "ojuny-install.log")
    try:
        if os.path.exists("/var/log/calamares.log"):
            with open("/var/log/calamares.log") as source, open(INSTALL_LOG, "a") as dest:
                dest.write("\n## Calamares log\n")
                shutil.copyfileobj(source, dest)
        run_command([cmd("pkexec"), cmd("install"), "-m", "0644", INSTALL_LOG, target])
        run_command([cmd("pkexec"), cmd("chown"), "1000:100", target])
        report = "/tmp/ojuny-install-report.json"
        if os.path.exists(report):
            target_report = os.path.join(home, "install-report.json")
            run_command([cmd("pkexec"), cmd("install"), "-m", "0644", report, target_report])
            run_command([cmd("pkexec"), cmd("chown"), "1000:100", target_report])
        LOG_SAVED = True
    except Exception as error:
        libcalamares.utils.warning(
            "could not save the install log to {}: {}".format(target, error)
        )


def run_command(cmd, input=None):
    result = subprocess.run(
        cmd,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "command failed ({code}): {cmd}\n{output}".format(
                code=result.returncode,
                cmd=" ".join(cmd),
                output=result.stdout,
            )
        )
    return result.stdout


def run_command_output(cmd, input=None):
    result = subprocess.run(
        cmd,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "command failed ({code}): {cmd}\n{output}".format(
                code=result.returncode,
                cmd=" ".join(cmd),
                output=(result.stdout or "") + (result.stderr or ""),
            )
        )
    return result.stdout


def stream_with_progress(command, progress, start, end, label):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output = []
    for line in process.stdout:
        was_json = progress.handle(line)
        if not was_json:
            text = line.strip()
            if text:
                output.append(text)
                libcalamares.utils.debug("{}: {}".format(label, text))
                append_log("{}: {}".format(label, text))

        for log_line in progress.log_messages:
            output.append(log_line)
            libcalamares.utils.debug("{}: {}".format(label, log_line))
            append_log("{}: {}".format(label, log_line))
        progress.log_messages.clear()

        if len(output) > 400:
            del output[:-400]

        libcalamares.job.setprogress(
            start + progress.fraction * (end - start)
        )

    exit_code = process.wait()
    return exit_code, output


def cmd(name):
    path = shutil.which(name)
    if path is None:
        raise RuntimeError("required command not found: {name}".format(name=name))
    return path


def write_file(path, content):
    run_command([cmd("pkexec"), cmd("tee"), path], input=content)


def nix_string(value):
    text = str(value).replace("${", "''${")
    return json.dumps(text, ensure_ascii=False)


def unobscure(value):
    if not isinstance(value, str):
        return ""
    return "".join(
        chr(0x1001F - ord(char)) if ord(char) > 0x21 else char
        for char in value
    )


def proxy_env():
    result = []
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        value = os.environ.get(name)
        if value:
            result.append("{name}={value}".format(name=name, value=value))
    if result:
        result.insert(0, cmd("env"))
    return result


def hash_password(password, mkpasswd):
    if not password:
        return "!"

    if not mkpasswd:
        raise RuntimeError("mkpasswd not found in the live environment")

    for method in ("yescrypt", "sha-512"):
        result = subprocess.run(
            [mkpasswd, "-m", method, "--", password],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    raise RuntimeError("mkpasswd failed: {error}".format(error=result.stderr.strip()))


def state_version():
    try:
        with open("/etc/os-release") as handle:
            for line in handle:
                if line.startswith("VERSION_ID="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    match = re.match(r"(\d+\.\d+)", value)
                    if match is not None:
                        return match.group(1)
    except OSError:
        pass

    for command in ("/run/current-system/sw/bin/nixos-version", "nixos-version"):
        try:
            output = subprocess.check_output([command], text=True).strip()
        except OSError:
            continue
        match = re.match(r"(\d+\.\d+)", output)
        if match is not None:
            return match.group(1)

    raise RuntimeError("could not determine the NixOS release")


def boot_device():
    loader = libcalamares.globalstorage.value("bootLoader")
    if not loader:
        return "nodev"
    return loader.get("installPath", "nodev")


def root_is_btrfs(hardware):
    return re.search(
        r'fileSystems\."/"\s*=\s*\{[^}]*fsType\s*=\s*"btrfs"',
        hardware,
        re.DOTALL,
    ) is not None


def bootloader_module(firmware_type, device, extra_lines, btrfs_root):
    lines = []
    if firmware_type == "efi":
        lines += [
            "boot.loader.systemd-boot.enable = true;",
            "boot.loader.efi.canTouchEfiVariables = true;",
        ]
    elif device and device != "nodev":
        lines += [
            "boot.loader.grub.enable = true;",
            "boot.loader.grub.device = {device};".format(device=nix_string(device)),
            "boot.loader.grub.useOSProber = true;",
        ]
        if btrfs_root:
            lines.append('boot.loader.grub.fsIdentifier = "provided";')
    else:
        lines.append("boot.loader.grub.enable = false;")

    lines += extra_lines
    return "\n".join("    " + line if line else line for line in lines)


def hardware_module(hardware, firmware_type, device, extra_lines):
    indented = "\n".join(
        "    " + line if line else line for line in hardware.splitlines()
    )
    return """# Generated by the Ojuny installer. Do not edit by hand.
{{ self, inputs, ... }}: {{

  flake.modules.nixos.system-hardware =
{hardware}
  ;

  flake.modules.nixos.system-bootloader = {{ pkgs, ... }}: {{
{bootloader}
  }};

}}
""".format(
        hardware=indented,
        bootloader=bootloader_module(
            firmware_type, device, extra_lines, root_is_btrfs(hardware)
        ),
    )


def uses_home_manager(clone):
    try:
        with open(os.path.join(clone, "flake.nix")) as handle:
            return "home-manager" in handle.read()
    except OSError:
        return False


def user_module(username, fullname, hashed_password, shell, version, home_manager):
    home_import = (
        " inputs.home-manager.nixosModules.home-manager" if home_manager else ""
    )
    home_option = " homeManager = true;" if home_manager else ""
    home_block = (
        """
      home-manager.users = {{
        {username} = {{
          home.stateVersion = "{version}";
        }};
      }};"""
        if home_manager
        else ""
    )
    return """/* @menu
   displayname = "Users";
   icon = "avatar-default-symbolic";
   order = 10;
   description = "User Accounts";
   category = "01-Users";
*/

{{ self, inputs, ... }}: {{

  flake.modules.nixos.users = {{ pkgs, ... }}: {{

    imports = [{home_import} ];

    config = {{
      /* @option widget = "users"; label = "Accounts";{home_option} */
      users.users = {{
        {username} = {{
          isNormalUser = true;
          uid = 1000;
          description = {fullname};
          extraGroups = [ "networkmanager" "wheel" "video" "input" ];
          hashedPassword = {hashed_password};
          openssh.authorizedKeys.keys = [ ];
          shell = pkgs.{shell};
        }};
      }};
{home_block}
    }};

  }};

}}
""".format(
        username=username,
        fullname=nix_string(fullname),
        hashed_password=nix_string(hashed_password),
        shell=shell,
        version=version,
        home_import=home_import,
        home_option=home_option,
        home_block=home_block,
    )


def fix_btrfs_subvolumes(hardware_config, partitions):
    root_is_btrfs = any(
        part.get("mountPoint") == "/" and part.get("fs") == "btrfs"
        for part in partitions
    )
    if not root_is_btrfs:
        return hardware_config

    for mount_point, subvolume in {"/home": "home", "/nix": "nix"}.items():
        pattern = r'(fileSystems\."{}"[^;]*"subvol=)[^"]*"'.format(
            re.escape(mount_point)
        )
        hardware_config = re.sub(
            pattern,
            '\\g<1>{subvolume}"'.format(subvolume=subvolume),
            hardware_config,
            flags=re.DOTALL,
        )
    return hardware_config


def read_kernel_latest():
    try:
        parser = configparser.ConfigParser()
        parser.read("/etc/nixos-generate-config.conf")
        return parser["Defaults"]["Kernel"] == "latest"
    except Exception:
        return False


def partition_type(device):
    if not device:
        return ""
    try:
        return run_command_output([cmd("lsblk"), "-no", "PARTTYPE", device]).strip()
    except Exception:
        return ""


def boot_mount_lines(partitions):
    mounts = {
        part.get("mountPoint"): part
        for part in partitions
        if part.get("mountPoint")
    }
    if mounts.get("/efi") is None or mounts.get("/boot") is None:
        return []
    if partition_type(mounts["/boot"].get("device")) != XBOOTLDR_PARTTYPE:
        return []
    return [
        'boot.loader.efi.efiSysMountPoint = "/efi";',
        'boot.loader.systemd-boot.xbootldrMountPoint = "/boot";',
    ]


def multiboot_needed(partitions):
    claimed = set()
    for part in partitions:
        device = part.get("device")
        if not device:
            continue
        if part.get("mountPoint") in ("/boot", "/boot/efi", "/efi"):
            claimed.add(os.path.realpath(device))
            continue
        if part.get("claimed") is True and part.get("fsName") in (
            "fat16",
            "fat32",
            "vfat",
        ):
            claimed.add(os.path.realpath(device))

    try:
        report = json.loads(
            run_command_output(
                [cmd("lsblk"), "-J", "-o", "PATH,TYPE,RM,TRAN,PARTTYPE,MOUNTPOINT"]
            )
        )
    except Exception:
        return False

    for disk in report.get("blockdevices", []):
        if disk.get("type") != "disk":
            continue
        if disk.get("rm"):
            continue
        if disk.get("tran") == "usb":
            continue
        for child in disk.get("children") or []:
            if child.get("parttype") != ESP_PARTTYPE:
                continue
            child_path = os.path.realpath(child.get("path") or "")
            if child_path in claimed:
                continue
            return True
    return False


def enable_multiboot(clone):
    if flake_structure.ensure_multiboot(clone, interactive=False):
        return True
    libcalamares.utils.warning(
        "multiboot module is missing; detected other systems stay unregistered"
    )
    return False


def extra_boot_lines(root, partitions, firmware):
    lines = []
    if read_kernel_latest():
        lines.append("boot.kernelPackages = pkgs.linuxPackages_latest;")

    root_is_encrypted = any(
        part.get("mountPoint") == "/" and part.get("fsName") in ("luks", "luks2")
        for part in partitions
    )
    boot_part = next(
        (part for part in partitions if part.get("mountPoint") == "/boot"), None
    )
    boot_is_partition = boot_part is not None
    boot_is_encrypted = (
        boot_is_partition and boot_part.get("fsName") in ("luks", "luks2")
    )

    if firmware != "efi" and (
        (boot_is_partition and boot_is_encrypted)
        or (root_is_encrypted and not boot_is_partition)
    ):
        keyfile = os.path.join(root, "boot", "crypto_keyfile.bin")
        run_command([cmd("pkexec"), cmd("mkdir"), "-p", os.path.dirname(keyfile)])
        run_command(
            [
                cmd("pkexec"),
                cmd("dd"),
                "bs=512",
                "count=4",
                "if=/dev/random",
                "of=" + keyfile,
                "iflag=fullblock",
            ]
        )
        run_command([cmd("pkexec"), cmd("chmod"), "600", keyfile])
        lines.append('boot.initrd.secrets."/boot/crypto_keyfile.bin" = null;')
        lines.append("boot.loader.grub.enableCryptodisk = true;")

        for part in partitions:
            if (
                part.get("luksMapperName")
                and part.get("device") is not None
                and (
                    part.get("claimed") is True
                    or part.get("fs") in ("linuxswap", "swap")
                )
            ):
                mapper = part.get("luksMapperName")
                lines.append(
                    'boot.initrd.luks.devices."{}".keyFile = "/boot/crypto_keyfile.bin";'.format(
                        mapper
                    )
                )
                passphrase = part.get("luksPassphrase")
                run_command(
                    [
                        cmd("pkexec"),
                        cmd("cryptsetup"),
                        "luksConvertKey",
                        "--hash",
                        "sha256",
                        "--pbkdf",
                        "pbkdf2",
                        part["device"],
                    ],
                    input=passphrase,
                )
                run_command(
                    [
                        cmd("pkexec"),
                        cmd("cryptsetup"),
                        "luksAddKey",
                        "--hash",
                        "sha256",
                        "--pbkdf",
                        "pbkdf2",
                        part["device"],
                        keyfile,
                    ],
                    input=passphrase,
                )

    if firmware == "efi":
        lines += boot_mount_lines(partitions)

    return lines


def write_extra_file(lines):
    handle = tempfile.NamedTemporaryFile(
        mode="w", delete=False, prefix="ojuny-boot-"
    )
    try:
        handle.write("\n".join(lines) + "\n")
        handle.close()
        return handle.name
    except Exception:
        handle.close()
        raise


def configure_template(
    clone,
    runtime_clone,
    hostname,
    username,
    fullname,
    hashed_password,
    shell,
    version,
    hardware,
    firmware_type,
    device,
    extra_lines,
):
    global TEMPLATE_PATH
    TEMPLATE_PATH = clone
    global_storage = libcalamares.globalstorage

    region = global_storage.value("locationRegion")
    zone = global_storage.value("locationZone")
    locale_conf = global_storage.value("localeConf") or {}
    locale = (locale_conf.get("LANG") or "").split("/")[0]
    keymap = global_storage.value("keyboardVConsoleKeymap") or global_storage.value(
        "keyboardLayout"
    )

    flake_structure.ensure_configuration(
        clone,
        {
            "hostname": hostname,
            "state_version": version,
            "timezone": region + "/" + zone if region and zone else None,
            "locale": locale or None,
            "keymap": keymap.strip() if keymap else None,
            "repo_path": runtime_clone,
        },
        interactive=False,
        fallback_rel="modules/00-configuration.nix",
    )
    flake_structure.ensure_users(
        clone,
        user_module(
            username,
            fullname,
            hashed_password,
            shell,
            version,
            uses_home_manager(clone),
        ),
        interactive=False,
        fallback_rel="modules/00-user.nix",
    )
    flake_structure.ensure_host(
        clone,
        hostname,
        runtime_clone,
        interactive=False,
        fallback_rel="modules/00-host.nix",
    )
    flake_structure.ensure_hardware(
        clone,
        hardware_module(hardware, firmware_type, device, extra_lines),
        interactive=False,
        fallback_rel="modules/00-hardware.nix",
    )
    imports = [
        name
        for name in (
            "system-configuration",
            "users",
            "system-hardware",
            "system-bootloader",
            "system-hardware-quirks",
        )
        if flake_structure.find_modules(clone, name)
    ]
    flake_structure.ensure_imports(
        clone,
        imports,
        interactive=False,
        fallback_rel="modules/00-imports.nix",
    )


def run_script(path, args):
    run_command([cmd("pkexec"), path] + args)


def clone_prepared(url, token, branch, clone):
    git = cmd("git")
    if os.path.exists(clone):
        run_command([cmd("pkexec"), cmd("rm"), "-rf", clone])

    clone_args = ["clone"]
    if branch:
        clone_args += ["--branch", branch]
    clone_args += [url, clone]

    if token and url.startswith(("http://", "https://")):
        parsed = urlparse(url)
        host = parsed.hostname
        user = parsed.username or "x-access-token"
        if not host:
            raise RuntimeError("invalid repository URL: {url}".format(url=url))

        temp_dir = tempfile.mkdtemp(prefix="ojuny-git-")
        try:
            os.chmod(temp_dir, 0o700)
            credentials = os.path.join(temp_dir, "credentials")
            with open(credentials, "w") as handle:
                handle.write(
                    "https://{user}:{token}@{host}\n".format(
                        user=user, token=quote(token, safe=""), host=host
                    )
                )
            os.chmod(credentials, 0o600)
            run_command(
                [
                    cmd("pkexec"),
                    git,
                    "-c",
                    "credential.helper=store --file={path}".format(path=credentials),
                ]
                + clone_args
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        run_command([cmd("pkexec"), git] + clone_args)


def prepared_hostname(clone):
    host = flake_structure.preferred_host(clone)
    if not host:
        raise RuntimeError(
            "could not find a nixosConfigurations host in the prepared repository"
        )
    return host


def write_credentials(cred_path, url, token):
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise RuntimeError("invalid git URL: {url}".format(url=url))
    user = parsed.username or "x-access-token"
    write_file(
        cred_path,
        "https://{user}:{token}@{host}\n".format(
            user=user, token=quote(token, safe=""), host=host
        ),
    )
    run_command([cmd("pkexec"), cmd("chmod"), "600", cred_path])


def chroot_git(root, runtime_clone, username, origin_url, token):
    repo = shlex.quote(runtime_clone)
    commands = [
        "git -C {repo} init -q".format(repo=repo),
        "git -C {repo} add -A".format(repo=repo),
        "git -C {repo} -c user.name='Ojuny Installer' -c user.email='installer@ojuny.local' commit -qm 'Initial Ojuny configuration'".format(
            repo=repo
        ),
    ]

    if origin_url:
        commands.append(
            "git -C {repo} remote remove origin 2>/dev/null || true".format(repo=repo)
        )
        commands.append(
            "git -C {repo} remote add origin {url}".format(
                repo=repo, url=shlex.quote(origin_url)
            )
        )

    if token and origin_url and origin_url.startswith(("http://", "https://")):
        commands.append(
            "git -C {repo} config credential.helper {helper}".format(
                repo=repo,
                helper=shlex.quote(
                    "store --file=/home/{username}/.git-credentials".format(
                        username=username
                    )
                ),
            )
        )

    run_command(
        [
            cmd("pkexec"),
            cmd("nixos-enter"),
            "--root",
            root,
            "-c",
            " && ".join(commands),
        ]
    )


def set_credential_helper(root, runtime_clone, username):
    run_command(
        [
            cmd("pkexec"),
            cmd("nixos-enter"),
            "--root",
            root,
            "-c",
            "git -C {repo} config credential.helper {helper}".format(
                repo=shlex.quote(runtime_clone),
                helper=shlex.quote(
                    "store --file=/home/{username}/.git-credentials".format(
                        username=username
                    )
                ),
            ),
        ]
    )


def generate_hardware(root):
    run_command([cmd("pkexec"), cmd("nixos-generate-config"), "--root", root])
    hardware_path = os.path.join(root, "etc/nixos/hardware-configuration.nix")
    with open(hardware_path) as handle:
        hardware = fix_btrfs_subvolumes(
            handle.read(), libcalamares.globalstorage.value("partitions") or []
        )
    run_command(
        [cmd("pkexec"), cmd("rm"), "-f", os.path.join(root, "etc/nixos/configuration.nix")]
    )
    run_command([cmd("pkexec"), cmd("rm"), "-f", hardware_path])
    return hardware


def generate_facter(staging):
    report = run_command([cmd("nixos-facter")])
    flake_structure.ensure_facter(
        staging,
        report,
        interactive=False,
        fallback_rel="modules/facter.json",
    )


LUKS_DEVICE_LINE = re.compile(r'boot\.initrd\.luks\.devices\."([^"]+)"\.device\s*=')


def open_crypt_devices():
    report = json.loads(run_command_output([cmd("lsblk"), "-J", "-o", "NAME,TYPE,UUID"]))
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


def sanitize_hardware_module(staging):
    candidates = flake_structure.find_modules(staging, "system-hardware") or flake_structure.find_modules(
        staging, "system-bootloader"
    )
    path = str(candidates[0]) if candidates else os.path.join(
        staging, "modules/00-hardware.nix"
    )
    if not os.path.exists(path):
        return
    with open(path) as handle:
        lines = [
            line
            for line in handle.read().splitlines()
            if "hardware.facter.reportPath" not in line
        ]

    crypt = open_crypt_devices()

    existing = {}
    kept = []
    for line in lines:
        match = LUKS_DEVICE_LINE.search(line)
        if match:
            existing.setdefault(match.group(1), line.strip())
            continue
        kept.append(line)

    referenced = set(re.findall(r"/dev/mapper/([A-Za-z0-9_.+-]+)", "\n".join(kept)))
    for part in libcalamares.globalstorage.value("partitions") or []:
        if (
            part.get("fs") == "linuxswap"
            and part.get("claimed")
            and part.get("luksMapperName")
        ):
            referenced.add(part["luksMapperName"])

    insert_at = len(kept)
    for index in range(len(kept) - 1, -1, -1):
        if kept[index].strip() == "};":
            insert_at = index
            break

    for name in sorted(referenced):
        if name in crypt:
            line = '    boot.initrd.luks.devices."{}".device = "/dev/disk/by-uuid/{}";'.format(
                name, crypt[name]
            )
        elif name in existing:
            line = existing[name]
        else:
            continue
        kept.insert(insert_at, line)
        insert_at += 1

    write_file(path, "\n".join(kept) + "\n")


def hardware_script_args(clone, root, firmware, device, extra_file):
    args = ["--root", clone, "--target-root", root]
    if firmware:
        args += ["--firmware", firmware]
    if device and device != "nodev":
        args += ["--boot-device", device]
    if extra_file:
        args += ["--extra-boot-config", extra_file]
    return args


def write_gui_config(home, clone, host, shell):
    config_dir = os.path.join(home, ".config", "nix-settings-gui")
    config_path = os.path.join(config_dir, "config.json")
    run_command([cmd("pkexec"), cmd("install"), "-d", "-m", "0755", config_dir])
    payload = {
        "flake_path": clone,
        "terminal_command": "ghostty -e {} -c".format(shell),
        "rebuild_command": 'sudo echo "starting rebuild"; sudo nixos-rebuild switch --flake {}#{} |& nom; echo "finished build, press any button to close the window"; read -n 1'.format(
            clone, host
        ),
        "reload_dms_on_rebuild": True,
    }
    write_file(config_path, json.dumps(payload, indent=2) + "\n")
    run_command([cmd("pkexec"), cmd("chown"), "1000:100", config_dir, config_path])


def preload_paths():
    paths = []
    for name in ("/etc/ojuny/flake-inputs", "/etc/ojuny/target-toplevels"):
        if not os.path.exists(name):
            continue
        with open(name) as handle:
            paths += [line.strip() for line in handle if line.strip()]
    return paths


def preload_store_paths(root, paths, progress):
    if not paths:
        return

    libcalamares.utils.debug(
        "Ojuny: copying {} store paths to the target store".format(len(paths))
    )
    command = [
        cmd("pkexec"),
        cmd("nix"),
        "--extra-experimental-features",
        "nix-command",
        "--log-format",
        "internal-json",
        "copy",
        "--no-check-sigs",
        "--to",
        root,
    ] + paths
    exit_code, output = stream_with_progress(
        command, progress, PROGRESS_ITEMS_START, PROGRESS_ITEMS_END, "nix copy"
    )
    if exit_code != 0:
        raise RuntimeError("nix copy failed:\n{}".format("\n".join(output)))


def rewrite_offline_inputs(staging):
    mapping_path = "/etc/ojuny/flake-input-paths"
    lock_path = os.path.join(staging, "flake.lock")
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
        nar_hash = run_command_output(
            [
                cmd("nix"),
                "--extra-experimental-features",
                "nix-command",
                "hash",
                "path",
                "--sri",
                path,
            ]
        ).strip()
        node["locked"] = {"type": "path", "path": path, "narHash": nar_hash}
    write_file(lock_path, json.dumps(lock, indent=2) + "\n")
    libcalamares.utils.debug(
        "Ojuny: rewrote {} flake inputs for offline evaluation".format(len(mapping))
    )
    return lock_path, original


def restore_offline_inputs(rewrite):
    if rewrite is None:
        return
    lock_path, original = rewrite
    write_file(lock_path, original)


def reject_reused_windows_esp(root):
    for mount in ("boot", "efi", "boot/efi"):
        marker = os.path.join(root, mount, "EFI/Microsoft/Boot/bootmgfw.efi")
        if os.path.exists(marker):
            raise RuntimeError(
                "The install is using the Windows EFI system partition as the Ojuny "
                "boot partition. Create a separate 4 GiB Ojuny ESP in the replaced "
                "partition or free space and leave the Windows ESP, Microsoft reserved "
                "partition and recovery partition unassigned. This keeps the Ojuny "
                "bootloader and recovery entry independent of Windows updates."
            )


def install():
    global TARGET_ROOT, TARGET_USER, START_TIME, LOG_SAVED, status
    global_storage = libcalamares.globalstorage
    job_configuration = libcalamares.job.configuration

    START_TIME = time.monotonic()
    LOG_SAVED = False
    try:
        open(INSTALL_LOG, "w").close()
    except OSError:
        pass
    append_log("Ojuny installer")
    append_log("started={}".format(time.strftime("%Y-%m-%d %H:%M:%S")))

    root = global_storage.value("rootMountPoint")
    if not root or not os.path.isdir(root):
        raise RuntimeError("invalid rootMountPoint: {root}".format(root=root))

    efi_mount = global_storage.value("efiSystemPartition") or "/boot"
    boot_mount = os.path.join(root, efi_mount.lstrip("/"))

    template_path = job_configuration.get("templatePath")
    if not template_path or not os.path.isdir(template_path):
        raise RuntimeError("template not found: {path}".format(path=template_path))

    prepare_repo = job_configuration.get("prepareRepo") or None
    regenerate_hardware = job_configuration.get("regenerateHardware") or None
    bootorder = job_configuration.get("bootorder") or None

    required = [
        "pkexec",
        "tee",
        "install",
        "rm",
        "cp",
        "chmod",
        "chown",
        "mkdir",
        "dd",
        "cryptsetup",
        "nixos-generate-config",
        "nixos-install",
        "nixos-enter",
        "nix",
        "nix-store",
        "git",
        "env",
    ]
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        raise RuntimeError(
            "missing required commands: {commands}".format(commands=", ".join(missing))
        )

    for label, path in (
        ("prepare-repo", prepare_repo),
        ("regenerate-hardware", regenerate_hardware),
        ("bootorder", bootorder),
    ):
        if path and (not os.path.isfile(path) or not os.access(path, os.X_OK)):
            raise RuntimeError("{label} is not executable: {path}".format(label=label, path=path))

    mkpasswd_path = job_configuration.get("mkpasswd") or cmd("mkpasswd")
    if not os.path.exists(mkpasswd_path):
        raise RuntimeError("mkpasswd not found in the live environment")

    username = global_storage.value("username") or "user"
    fullname = global_storage.value("fullname") or username
    hostname = global_storage.value("hostname") or "ojuny"

    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
        raise RuntimeError("invalid username: {username}".format(username=username))
    if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?", hostname):
        raise RuntimeError("invalid hostname: {hostname}".format(hostname=hostname))

    TARGET_ROOT = root
    TARGET_USER = username
    append_log("root={}".format(root))
    append_log("username={}".format(username))
    append_log("hostname={}".format(hostname))

    clone_relative = job_configuration.get("cloneRelativePath", "repos/nix-flake")
    home = os.path.join(root, "home", username)
    clone = os.path.join(home, clone_relative)
    runtime_clone = os.path.join("/home", username, clone_relative)
    staging = tempfile.mkdtemp(prefix="ojuny-flake-")

    shell = "zsh"
    runtime_shell = global_storage.value("userShell") or ""
    for candidate in ("zsh", "bash", "fish"):
        if candidate in runtime_shell:
            shell = candidate
            break

    password = unobscure(global_storage.value("password"))
    hashed_password = hash_password(password, mkpasswd_path)
    version = state_version()

    mode = global_storage.value("ojuny_template_mode") or "bundled"
    append_log("mode={}".format(mode))
    append_log("state_version={}".format(version))
    append_log("offline={}".format(os.path.exists("/etc/ojuny/offline")))
    append_log("discovery={}".format(os.path.exists("/etc/ojuny/discovery")))
    template_url = (global_storage.value("ojuny_template_url") or "").strip()
    template_token = (global_storage.value("ojuny_template_token") or "").strip()
    template_branch = (global_storage.value("ojuny_template_branch") or "").strip()
    origin_url = (global_storage.value("ojuny_origin_url") or "").strip()
    origin_token = (global_storage.value("ojuny_origin_token") or "").strip()

    region = global_storage.value("locationRegion")
    zone = global_storage.value("locationZone")
    timezone = region + "/" + zone if region and zone else None

    locale_conf = global_storage.value("localeConf") or {}
    locale = (locale_conf.get("LANG") or "").split("/")[0] or None

    keymap = global_storage.value("keyboardVConsoleKeymap") or global_storage.value(
        "keyboardLayout"
    )
    keymap = keymap.strip() if keymap else None

    firmware = global_storage.value("firmwareType")
    device = boot_device()
    partitions = global_storage.value("partitions") or []
    reject_reused_windows_esp(root)

    libcalamares.job.setprogress(0.01)
    phase("preparing boot configuration")
    extra_lines = extra_boot_lines(root, partitions, firmware)
    extra_file = write_extra_file(extra_lines) if extra_lines else None
    phase("creating target home")
    run_command([cmd("pkexec"), cmd("install"), "-d", "-m", "0755", home])
    if os.path.exists(clone):
        run_command([cmd("pkexec"), cmd("rm"), "-rf", clone])

    phase("preparing template and hardware")
    if mode == "prepared":
        if not template_url:
            raise RuntimeError("a prepared template repository URL is required")
        if not regenerate_hardware:
            raise RuntimeError(
                "the template input does not provide regenerate-hardware"
            )

        libcalamares.job.setprogress(0.02)
        try:
            clone_prepared(template_url, template_token, template_branch, staging)
        except Exception as error:
            raise RuntimeError(
                "could not clone the prepared template repository {url}: {error}\n"
                "The install stopped. Close and reopen the installer from the "
                "Install Ojuny entry, return to the Ojuny template page, correct "
                "the URL, token or branch, and retry.".format(
                    url=template_url, error=error
                )
            )

        try:
            hostname = prepared_hostname(staging)
        except Exception as error:
            raise RuntimeError(
                "could not read the hostname from the prepared repository: {error}\n"
                "The repository must contain a nixosConfigurations entry. The install stopped. Close and reopen "
                "the installer from the Install Ojuny entry, return to the Ojuny "
                "template page, correct the repository, and retry.".format(
                    error=error
                )
            )

        libcalamares.job.setprogress(0.04)
        run_script(
            regenerate_hardware,
            hardware_script_args(staging, root, firmware, device, extra_file),
        )
        git = cmd("git")
        run_command([cmd("pkexec"), git, "-C", staging, "add", "-A"])
        run_command(
            [
                cmd("pkexec"),
                git,
                "-C",
                staging,
                "-c",
                "user.name=Ojuny Installer",
                "-c",
                "user.email=installer@ojuny.local",
                "commit",
                "-qm",
                "Regenerate hardware for this machine",
                "--allow-empty",
            ]
        )
    else:
        if prepare_repo:
            libcalamares.job.setprogress(0.02)
            prepare_args = [
                "--root",
                staging,
                "--template",
                template_path,
                "--username",
                username,
                "--fullname",
                fullname,
                "--hashed-password",
                hashed_password,
                "--shell",
                shell,
                "--hostname",
                hostname,
                "--state-version",
                version,
                "--clone-relative",
                clone_relative,
                "--force",
                "--non-interactive",
            ]
            if timezone:
                prepare_args += ["--timezone", timezone]
            if locale:
                prepare_args += ["--locale", locale]
            if keymap:
                prepare_args += ["--keymap", keymap]
            run_script(prepare_repo, prepare_args)

            libcalamares.job.setprogress(0.04)
            if regenerate_hardware:
                run_script(
                    regenerate_hardware,
                    hardware_script_args(staging, root, firmware, device, extra_file),
                )
            else:
                hardware = generate_hardware(root)
                flake_structure.ensure_hardware(
                    staging,
                    hardware_module(hardware, firmware, device, extra_lines),
                    interactive=False,
                    fallback_rel="modules/00-hardware.nix",
                )
            sanitize_hardware_module(staging)
            generate_facter(staging)
        else:
            libcalamares.job.setprogress(0.02)
            run_command([cmd("pkexec"), cmd("cp"), "-a", template_path, staging])
            run_command([cmd("pkexec"), cmd("chmod"), "-R", "u+w", staging])

            libcalamares.job.setprogress(0.04)
            hardware = generate_hardware(root)
            configure_template(
                staging,
                runtime_clone,
                hostname,
                username,
                fullname,
                hashed_password,
                shell,
                version,
                hardware,
                firmware,
                device,
                extra_lines,
            )
            sanitize_hardware_module(staging)
            generate_facter(staging)

    multiboot = multiboot_needed(partitions)
    append_log(
        "multiboot helper: {}".format("enabled" if multiboot else "not needed")
    )
    if multiboot and not enable_multiboot(staging):
        append_log("multiboot helper could not be enabled in the staged template")

    if extra_file:
        os.unlink(extra_file)

    offline_mode = os.path.exists("/etc/ojuny/offline")
    preload = preload_paths() if offline_mode else []
    status = "counting install items"
    append_log("counting install items")
    total_items = 0
    if offline_mode:
        total_items = len(set(preload))
    else:
        try:
            total_items = measure_closure_items(
                run_command_output, root, staging, hostname
            )
        except Exception as error:
            append_log("could not measure the install closure: {}".format(error))
    append_log("install items={}".format(total_items))
    progress = InstallProgress(total_items)
    progress.start()
    status = "installing NixOS"
    libcalamares.job.setprogress(PROGRESS_ITEMS_START)

    if offline_mode:
        phase("preloading offline store")
        preload_store_paths(root, preload, progress)

    previous_boot = None
    if bootorder:
        handle, previous_boot = tempfile.mkstemp(prefix="ojuny-bootorder-", suffix=".txt")
        os.close(handle)
        snapshot = subprocess.run(
            [bootorder],
            env=dict(os.environ, OJUNY_BOOTORDER_MODE="snapshot"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with open(previous_boot, "w") as handle:
            handle.write(snapshot.stdout)
        append_log("boot order before install:")
        for line in snapshot.stdout.splitlines():
            append_log("  " + line)

    status = "installing NixOS"
    phase("starting nixos-install")
    run_command([cmd("pkexec"), cmd("chmod"), "755", root])
    command = [cmd("pkexec")] + proxy_env() + [
        cmd("nixos-install"),
        "--no-root-passwd",
        "--log-format",
        "internal-json",
        "--root",
        root,
        "--flake",
        "{staging}#{hostname}".format(staging=staging, hostname=hostname),
        "--option",
        "build-dir",
        "/nix/var/nix/builds",
    ]
    if offline_mode:
        command += ["--option", "substituters", "auto?trusted=1"]

    offline_rewrite = None
    if offline_mode:
        offline_rewrite = rewrite_offline_inputs(staging)

    exit_code, output = stream_with_progress(
        command,
        progress,
        PROGRESS_ITEMS_START,
        PROGRESS_ITEMS_END,
        "nixos-install",
    )
    restore_offline_inputs(offline_rewrite)
    if exit_code != 0:
        raise RuntimeError("nixos-install failed:\n{}".format("\n".join(output)))

    phase("nixos-install finished")

    if bootorder and previous_boot and os.path.exists(previous_boot):
        try:
            result = subprocess.run(
                [bootorder],
                env=dict(
                    os.environ,
                    OJUNY_BOOTORDER_MODE="install",
                    OJUNY_BOOT_MOUNT=boot_mount,
                    OJUNY_RECOVERY_ENABLED="true",
                    OJUNY_BOOTORDER_PREVIOUS=previous_boot,
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            append_log("boot order after install:")
            for line in (result.stdout or "").splitlines():
                append_log("  " + line)
            if result.returncode != 0:
                append_log("bootorder exited with {}".format(result.returncode))
        except OSError as error:
            append_log("bootorder failed: {}".format(error))
        finally:
            os.unlink(previous_boot)

    libcalamares.job.setprogress(PROGRESS_ITEMS_END)
    phase("copying generated configuration")
    repos_dir = os.path.dirname(clone)
    run_command([cmd("pkexec"), cmd("rm"), "-rf", clone])
    run_command([cmd("pkexec"), cmd("install"), "-d", "-m", "0755", repos_dir])
    run_command([cmd("pkexec"), cmd("install"), "-d", "-m", "0755", clone])
    run_command([cmd("pkexec"), cmd("cp"), "-a", staging + "/.", clone])
    run_command([cmd("pkexec"), cmd("rm"), "-rf", staging])

    libcalamares.job.setprogress(0.99)
    phase("setting up git")

    credential_path = os.path.join(root, "home", username, ".git-credentials")
    try:
        if mode == "prepared":
            if template_token and template_url.startswith(("http://", "https://")):
                write_credentials(credential_path, template_url, template_token)
                set_credential_helper(root, runtime_clone, username)
        else:
            chroot_git(
                root,
                runtime_clone,
                username,
                origin_url,
                origin_token,
            )
            if origin_token and origin_url.startswith(("http://", "https://")):
                write_credentials(credential_path, origin_url, origin_token)
    except Exception as error:
        raise RuntimeError(
            "could not finish the git setup: {error}\n"
            "The install stopped. Close and reopen the installer from the "
            "Install Ojuny entry, return to the Git origin page, or to the "
            "Ojuny template page for a prepared repository, correct the remote "
            "or token, and retry.".format(error=error)
        )

    run_command([cmd("pkexec"), cmd("chown"), "1000:100", repos_dir])
    run_command([cmd("pkexec"), cmd("chown"), "-R", "1000:100", clone])
    run_command([cmd("pkexec"), cmd("chown"), "1000:100", home])
    write_gui_config(home, runtime_clone, hostname, shell)
    if os.path.exists(credential_path):
        run_command([cmd("pkexec"), cmd("chown"), "1000:100", credential_path])
        run_command([cmd("pkexec"), cmd("chmod"), "600", credential_path])

    # home-manager activation runs as root during nixos-install and creates
    # ~/.config entries owned by root. Hand the whole home tree back to the
    # user so the desktop session can write its own configuration.
    phase("fixing home ownership")
    run_command([cmd("pkexec"), cmd("chown"), "-R", "1000:100", home])

    phase("collecting install report")
    write_install_report()

    phase("saving install log")
    save_install_log()

    libcalamares.job.setprogress(1.0)
    phase("installation finished")
    return None


def run():
    libcalamares.utils.debug("Ojuny installer starting")
    try:
        return install()
    except Exception as error:
        append_log("ERROR: {}".format(error))
        libcalamares.utils.error(str(error))
        save_install_log()
        return ("Ojuny installation failed", str(error))
