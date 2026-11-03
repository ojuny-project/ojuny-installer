# Unattended install ISO

Build an unattended installer ISO from an `ojuny-template` fork. The ISO
partitions the target disk, copies the flake to
`/home/<user>/repos/nix-flake`, regenerates the hardware data, writes a disko
module into the installed flake, runs `nixos-install --flake`, and leaves the
modified flake in the installed system.

There are three variants:

- Online: minimal live environment, downloads flake inputs.
- Offline: full target closure, installs without network access.
- Discovery: minimal live environment with `nix-cache-discovery`, so the flake
  closure can be pulled from other Ojuny devices on the same network.

## Build

The build script is a flake app, so it does not need a checkout:

```sh
nix run github:ojuny-project/ojuny-installer#make-unattended-iso
```

The script shows a variant menu and prompts for the template, disk, firmware,
account, password and SSH keys. Pressing Enter through the prompts uses the base
template with a generic `user` account on host `ojuny`. Those defaults are the
publishable images.

The template is passed through `--override-input ojuny-template`, so a fork URL
or local path is used directly. No clone or repository modification is needed
before building. `--template` and `--flake` accept the same value.

The variant menu is skipped when one of these flags is given:

```sh
nix run github:ojuny-project/ojuny-installer#make-unattended-iso -- --online
nix run github:ojuny-project/ojuny-installer#make-unattended-iso -- --offline
nix run github:ojuny-project/ojuny-installer#make-unattended-iso -- --discovery
```

Use `--dry-run` to inspect the settings and build command without building.

The ISO is copied to `./result-unattended/`.

## Install flow

1. The live ISO boots to a console and starts `ojuny-unattended-install`.
2. The service waits for the target disk, checks that it is not mounted, and
   optionally counts down before wiping it.
3. `disko` creates a GPT layout with a BIOS boot partition, an ESP, an ext4
   root or a LUKS2-encrypted ext4 root, and an optional swap partition.
4. The flake snapshot is copied to `/mnt/home/<user>/repos/nix-flake`.
5. `regenerate-hardware` writes the facter report and hardware data for the
   target.
6. The installer replaces `modules/07-system/00-hardware.nix` with a generic
   hardware module that contains the disko layout and bootloader. The installed
   system keeps the layout for future redeployments. The user module is the only
   other generated file.
7. The copy is initialized as a git repository and committed.
8. `nixos-install --flake /mnt/home/<user>/repos/nix-flake#<host>` installs the
   system.
9. `~/.config/nix-settings-gui/config.json` is written and the flake is chowned
   to the target user.
10. The machine reboots or powers off.

On failure the service prints the error and starts a shell on tty1. The target
is not rebooted automatically.

## Discovery variant

The discovery ISO runs `nix-cache-discovery` on port 5055 and points the install
service at the local cache. The service waits for the local cache instead of
the public cache. If no peer answers, the install continues and falls back to
the normal substituters.

## Settings

The settings are stored in a temporary flake input. They never enter the
repository. The password is hashed with `mkpasswd` before the ISO is built.

- `mode`: `prepared` or `bundled`.
- `disk`: target block device, preferably `/dev/disk/by-id/...`.
- `firmware`: `efi` or `bios`.
- `host`, `username`, `fullName`, `hashedPassword`, `sshKeys`.
- `shell`, `timezone`, `locale`, `keymap`.
- `swapSize`: `0` disables the swap partition.
- `confirmSeconds`: countdown before wiping the disk.
- `finalAction`: `reboot` or `poweroff`.
- `cloneRelative`: path below the home directory, default `repos/nix-flake`.
- `stateVersion`: used by bundled mode.

## Hardware test checklist

No QEMU run is part of this repository. Test each image on real hardware:

1. Write the ISO to a USB key.
2. Boot the target machine and confirm the unattended service starts.
3. Confirm the target disk is wiped only after the countdown.
4. Confirm the installed system boots and the Ojuny desktop starts.
5. Confirm `/home/<user>/repos/nix-flake/modules/07-system/00-hardware.nix`
   contains the disko layout.
6. Confirm the installed system still has `disko`, `deploy-rs` and
   `nixos-anywhere`.

## Limitations

- The online and discovery variants need network access.
- The offline ISO is a full-system image and is significantly larger.
- Destructive: the configured disk is wiped without an interactive installer.
- `x86_64-linux` only.
- UEFI and BIOS are supported by separate builds. The firmware setting is fixed
  at ISO build time.
- LUKS2 root encryption is optional through `--encrypt`; the passphrase is
  stored on the live ISO with mode `0600`.
- The ISO installs the flake snapshot it was built from.
- Wi-Fi is not configured by the unattended service. Use a wired connection.
