# ojuny-installer

`ojuny-installer` builds the Calamares live ISO and the unattended installer ISO for [ojuny-template](https://github.com/ojuny-project/ojuny-template) on NixOS. The attended image runs a rebranded Calamares, partitions the target with optional LUKS2 root encryption, copies the pinned template to `/home/<user>/repos/nix-flake`, and runs `nixos-install --flake`. The unattended image does the same install without interaction, using disko for the disk layout.

> Status: untested. The ISOs build and the attended image boots in QEMU, but no install has been completed. Applies to commit `7680158`. Last verified 2026-11-03.

## Requirements

- `x86_64-linux` with Nix and flakes enabled.
- 4 GB RAM and a 30 GB target disk.
- An 8 GB USB key. The offline images are checked against 8,000,000,000 bytes.
- Network access is needed to build and for online installs. The offline images carry the target closure and the template's locked flake inputs, so the default full-system install runs without network. Non-default hardware modules, out-of-tree drivers and optional patches can still need it.

## Build

The six ISO targets in `flake.nix`:

```sh
nix build .#ojuny-iso               # attended, online
nix build .#ojuny-iso-discovery     # attended, discovery cache
nix build .#unattended-iso          # unattended, online
nix build .#unattended-iso-discovery
nix build .#ojuny-iso-offline       # attended, full system
nix build .#unattended-iso-offline  # unattended, full system
```

Images land in `result/iso/*.iso`; offline images carry the full system runtime closure. Build the unattended image with the settings wrapper:

```sh
nix run github:ojuny-project/ojuny-installer#make-unattended-iso
```

Build the persistent image:

```sh
nix run .#make-persistent-image
```

## Run in QEMU

Create a 20 GB qcow2 disk and boot the attended ISO:

```sh
qemu-img create -f qcow2 /tmp/ojuny-test.qcow2 20G
firmware="$(nix build --no-link --print-out-paths nixpkgs#OVMF.fd)/FV/OVMF.fd"
iso="$(echo result/iso/*.iso)"

qemu-system-x86_64 \
  -enable-kvm -m 4096 -smp 4 -cpu host \
  -bios "$firmware" \
  -device virtio-vga-gl \
  -device virtio-keyboard-pci -device virtio-tablet-pci \
  -drive file="$iso",media=cdrom,readonly=on \
  -drive file=/tmp/ojuny-test.qcow2,if=virtio \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
  -display gtk,gl=on
```

The VM needs `virtio-vga-gl` with `gl=on`; plain VGA, QXL and 2D `virtio-vga` render the Wayland session incorrectly. The attended ISO has been booted with 4 GB RAM and two threads; install time is not measured. Use `-nic none` to test an offline image.

## Write to USB

Write the ISO with Etcher or Rufus. For the raw persistent image, [docs/persistent-image.md](docs/persistent-image.md) gives the DD command and the Ventoy steps.

## Install paths

- Attended: boot the ISO and complete the Calamares pages. See [docs/attended-install.md](docs/attended-install.md).
- Unattended: build with `make-unattended-iso`; the service wipes the configured disk. See [docs/unattended-install.md](docs/unattended-install.md).
- Offline: use an attended or unattended full-system image. See [docs/offline-install.md](docs/offline-install.md).
- Remote: deploy-rs for an existing NixOS target, nixos-anywhere for a machine without NixOS. See [docs/remote-deployment.md](docs/remote-deployment.md).

The attended and unattended installers copy the template to
`/home/<user>/repos/nix-flake` and regenerate `modules/07-system/00-hardware.nix`
from the target mounts and `modules/01-users/01-user.nix` from the account page.
The attended installer also writes `modules/07-system/00-host.nix`, which
registers `nixosConfigurations.<hostname>`. The unattended installer updates an
existing `00-host.nix` when the template ships one.

## Limits

- `x86_64-linux` only. UEFI uses systemd-boot; BIOS uses GRUB with a generated keyfile for encrypted boot.
- The unattended ISO wipes the configured disk and does not configure Wi-Fi.
- The attended installer can shrink XFS, EXT4, BTRFS, f2fs and vfat partitions,
  and install alongside an existing system. It does not resize NTFS; shrink the
  Windows partition in Windows Disk Management first and export the BitLocker
  recovery key.
- The attended installer enables the optional rEFInd "Other systems" helper
  when another internal ESP or operating system would not be visible to
  systemd-boot.
- Offline images cover the default full system; unusual hardware, out-of-tree drivers and optional patches still need network.
- Ten prebuilt applications dominate build time.

## Documentation

- [Attended install tests](docs/attended-install.md): the attended flow and pending runs.
- [Unattended install ISO](docs/unattended-install.md): each variant and the install flow.
- [Offline install ISOs](docs/offline-install.md): store contents and size limit.
- [Persistent image](docs/persistent-image.md): the tmpfs root and persistent home.
- [Remote deployment](docs/remote-deployment.md): deploy-rs and nixos-anywhere.

## Contributing

Report issues on GitHub. A patch includes the change, a passing `nix flake check`, and a matching documentation update.

## License

GPL-3.0. See [LICENSE](LICENSE). Built on NixOS, nixpkgs and Calamares, and installs [ojuny-template](https://github.com/ojuny-project/ojuny-template).
