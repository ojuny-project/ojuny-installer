# Persistent image

The base persistent image is a raw `.img` built from the Ojuny template. It can
be written directly with Etcher or Rufus in DD mode. Ventoy can boot the same
image as a virtual disk. Ventoy is not required.

## Runtime layout

- `/` is tmpfs. Every write outside the persisted paths is lost at reboot.
- `/persist` is the ext4 image partition, mounted read-write.
- `/nix/.rw-store` is tmpfs.
- `/nix/store` is an overlay. Its lower layer is `/persist/nix/store`, which is
  never written to by the running system. Its upper layer is the tmpfs.
- `/home` is bind-mounted from `/persist/home` by impermanence.
- `/var/lib/nixos` is also persisted so system user and group IDs stay stable.
- `/etc`, `/var`, `/nix/var` and all other root paths are transient.

Package installs and system changes written to `/nix` live in the tmpfs overlay
until reboot. Updates are not persistent. Home files are persistent.

## Build

```sh
nix run github:ojuny-project/ojuny-installer#make-persistent-image
```

The script runs the disko image builder and writes:

- `ojuny-persistent.img`
- `ojuny-persistent.qcow2` when `--qcow2` is given

Options:

```sh
nix run github:ojuny-project/ojuny-installer#make-persistent-image -- \
  --output ~/images \
  --qcow2 \
  --build-memory 4096
```

The image size is configured in `nixos/persistent.nix`.

## Write to a USB key

Use Etcher or Rufus in DD mode. The image is a complete GPT disk with an ESP
and an ext4 persistence partition.

On Linux:

```sh
sudo dd if=ojuny-persistent.img of=/dev/sdX bs=4M status=progress conv=fsync
```

## Ventoy

Copy the image to a Ventoy data partition. Ventoy's Linux virtual-disk mode maps
the raw image as a writable disk, so `/home` changes persist in the image file.
Keep the original `.img` name and use Ventoy's virtual-disk menu entry. If the
Ventoy version requires the `.vtoy` suffix, copy the file as
`ojuny-persistent.img.vtoy`.

The image does not depend on Ventoy's persistence plugin, a separate `.dat`
file, or a persistence partition on the Ventoy disk.

## Limitations

- The image is UEFI and BIOS bootable through GRUB.
- `/home` and `/var/lib/nixos` persist. System updates and package installs are transient.
- The first boot needs the image's full store, so the image is larger than the
  live ISOs.
- The image is x86_64 only.
