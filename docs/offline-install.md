# Offline install ISOs

The offline ISOs are separate full-system targets. The live environment contains
the full Ojuny system instead of the cut-down installer system, so the target
closure and the live closure overlap heavily. The images also carry the build
inputs needed by `nixos-install`. See the README's
[Requirements](../README.md#requirements) for the build and install network
boundaries.

## Build

Attended offline ISO:

```sh
nix build .#ojuny-iso-offline
```

The image is written to `result/iso/*.iso`.

Unattended offline ISO:

```sh
nix run .#make-unattended-iso -- --offline \
  --flake "$HOME/repos/my-template" \
  --disk /dev/disk/by-id/...
```

The image is copied to `result-unattended/`.

## Outputs

- `packages.ojuny-iso-offline`
- `packages.unattended-iso-offline`
- `nixosConfigurations.ojuny-iso-offline`
- `nixosConfigurations.ojuny-unattended-offline`

The online outputs are unchanged.

## Size

An 8 GB USB has about 7.4 GiB usable. The hard flake check is 8,000,000,000
bytes and the warning threshold is 7,400,000,000 bytes. Check a built image
with:

```sh
scripts/check-iso-size.sh path/to/image.iso
```

If an image is too large, remove the latest-kernel target first, then the extra
bootloader packages, then the non-default shell and locale extras. Do not remove
the full system or the main target closure.

## What the offline store contains

- The full live system closure from the full-system target.
- The installed target toplevel and its `.drvPath`.
- The latest-kernel target toplevel and its `.drvPath`.
- GRUB, `grub2_efi` and `efibootmgr` for the BIOS boot path.
- `fish` and `glibcLocales` for the install-time choices.

The image does not include the full build-dependency closure. Including it pulls
in sources, `-dev` and `-man` outputs and can add tens of GiB. Add a specific
path only when a manual offline test reports it missing.

The target hardware is generated at install time. The prebuilt target uses a
generic hardware module. The package closure matches; the final toplevel and
initrd are built locally from the offline store.

## Manual hardware matrix

- Attended, EFI, ext4, network disconnected.
- Attended, EFI, LUKS, network disconnected.
- Attended, BIOS, ext4, network disconnected.
- Attended, BIOS, LUKS, network disconnected.
- Unattended, EFI, ext4, prepared and bundled, network disconnected.
- Unattended, EFI, LUKS, prepared and bundled, network disconnected.
- Unattended, BIOS, ext4, prepared and bundled, network disconnected.
- Unattended, BIOS, LUKS, prepared and bundled, network disconnected.

For each case verify that the install completes, the installed system boots, the
desktop starts, and `nixos-rebuild switch` works without network access.

## Limits

- The offline store covers the default full system and common install choices.
  Unusual hardware modules, out-of-tree drivers and optional patches still need
  network access.
- The offline ISO is significantly larger than the online ISO.
- The unattended offline ISO still needs a wired connection for the online
  variant only. The offline variant does not configure Wi-Fi either.
