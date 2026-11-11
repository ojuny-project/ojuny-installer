#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

cores="${PRELOAD_CORES:-}"
if [ -n "$cores" ] && command -v taskset >/dev/null 2>&1 && [ -z "${PRELOAD_TASKSET:-}" ]; then
  export PRELOAD_TASKSET=1
  exec nice -n 10 taskset -c "0-$((cores - 1))" "$0" "$@"
fi
parallel="${cores:-8}"

system="x86_64-linux"
work="$(mktemp -d)"
previous="$work/previous-paths.txt"
cp "$repo/nixos/preload-paths.txt" "$previous" 2>/dev/null || : >"$previous"
keep=0
cleanup() {
  if [ "$keep" -ne 1 ]; then
    cp "$previous" "$repo/nixos/preload-paths.txt" 2>/dev/null || true
    git -C "$repo" add nixos/preload-paths.txt 2>/dev/null || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT

: >"$repo/nixos/preload-paths.txt"

flake_ref="path:$repo"
template="$(nix eval --impure --raw --expr "(builtins.getFlake \"$flake_ref\").inputs.ojuny-template.outPath")"
prepare="$(nix build --no-link --print-out-paths --impure --expr "(builtins.getFlake \"$flake_ref\").inputs.ojuny-template.packages.$system.prepare-repo" | tail -1)"
mapping="$(nix eval --raw ".#nixosConfigurations.ojuny-iso-offline.config.environment.etc.\"ojuny/flake-input-paths\".text")"
echo "collecting the current ISO store contents"
nix eval --json ".#nixosConfigurations.ojuny-iso-offline.config.isoImage.storeContents" >"$work/baseline.json"

prepare_fixture() {
  local root="$1" user="$2" host="$3" timezone="$4" locale="$5" keymap="$6"
  local password
  password="$(openssl passwd -6 "fixture-$user")"
  "$prepare/bin/prepare-repo" \
    --root "$root" \
    --template "$template" \
    --username "$user" \
    --fullname "$user" \
    --hashed-password "$password" \
    --shell zsh \
    --hostname "$host" \
    --state-version 26.11 \
    --clone-relative repos/nix-flake \
    --force \
    --non-interactive \
    --timezone "$timezone" \
    --locale "$locale" \
    --keymap "$keymap"
}

write_hardware() {
  local root="$1" body="$2" hardware
  hardware="$(python3 "$root/scripts/flake_structure.py" --root "$root" --non-interactive path --module hardware --fallback modules/00-hardware.nix)"
  mkdir -p "$(dirname "$hardware")"
  cat >"$hardware" <<EOF
{ self, ... }: {
  flake.modules.nixos.system-hardware =
    { lib, ... }:
    {
$body
      nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
    };

  flake.modules.nixos.system-bootloader = {
    boot.loader.grub.enable = true;
    boot.loader.grub.device = "/dev/vda";
  };
}
EOF
  python3 "$root/scripts/flake_structure.py" --root "$root" --non-interactive ensure-imports \
    --name system-hardware --name system-bootloader >/dev/null
}

rewrite_lock() {
  local root="$1"
  python3 - "$root/flake.lock" "$mapping" <<'PY'
import json
import subprocess
import sys

lock_path, mapping = sys.argv[1], sys.argv[2]
lock = json.load(open(lock_path))
for name, path in json.loads(mapping).items():
    node = lock["nodes"].get(name)
    if node is None or "locked" not in node:
        continue
    nar_hash = subprocess.check_output(
        ["nix", "--extra-experimental-features", "nix-command", "hash", "path", "--sri", path],
        text=True,
    ).strip()
    node["locked"] = {"type": "path", "path": path, "narHash": nar_hash}
with open(lock_path, "w") as handle:
    json.dump(lock, handle, indent=2)
    handle.write("\n")
PY
}

prepare_config() {
  local name="$1" timezone="$2" locale="$3" keymap="$4"
  local root="$work/$name"
  echo "preparing fixture $name ($locale, $timezone, $keymap)"
  prepare_fixture "$root" "$name" "$name" "$timezone" "$locale" "$keymap"
  rewrite_lock "$root"
}

hardware_plain_ext4='      fileSystems."/" = {
        device = "/dev/disk/by-label/PLAIN-root";
        fsType = "ext4";
      };
      fileSystems."/boot" = {
        device = "/dev/disk/by-label/PLAIN-boot";
        fsType = "vfat";
      };
      boot.initrd.availableKernelModules = [ "nvme" "xhci_pci" "sd_mod" ];
      boot.kernelModules = [ ];
      hardware.cpu.intel.updateMicrocode = lib.mkDefault true;'

hardware_luks_xfs='      fileSystems."/" = {
        device = "/dev/mapper/cryptroot";
        fsType = "xfs";
      };
      fileSystems."/boot" = {
        device = "/dev/disk/by-label/LUKS-boot";
        fsType = "vfat";
      };
      boot.initrd.luks.devices."cryptroot".device = "/dev/disk/by-label/LUKS-root";
      boot.initrd.luks.devices."cryptswap".device = "/dev/disk/by-label/LUKS-swap";
      swapDevices = [ { device = "/dev/mapper/cryptswap"; } ];
      boot.initrd.availableKernelModules = [ "nvme" "xhci_pci" "usbhid" "dm_mod" ];
      boot.kernelModules = [ ];
      hardware.cpu.amd.updateMicrocode = lib.mkDefault true;'

hardware_btrfs='      fileSystems."/" = {
        device = "/dev/disk/by-label/BTRFS-root";
        fsType = "btrfs";
        options = [ "subvol=@" ];
      };
      fileSystems."/boot" = {
        device = "/dev/disk/by-label/BTRFS-boot";
        fsType = "vfat";
      };
      swapDevices = [ { device = "/dev/disk/by-label/BTRFS-swap"; } ];
      boot.initrd.availableKernelModules = [ "virtio_blk" "usbhid" "sd_mod" ];
      boot.kernelModules = [ "kvm-intel" ];
      hardware.cpu.intel.updateMicrocode = lib.mkDefault true;'

hardware_luks_ext4='      fileSystems."/" = {
        device = "/dev/mapper/cryptroot";
        fsType = "ext4";
      };
      fileSystems."/boot" = {
        device = "/dev/disk/by-label/LUKSE-boot";
        fsType = "vfat";
      };
      boot.initrd.luks.devices."cryptroot".device = "/dev/disk/by-label/LUKSE-root";
      boot.initrd.availableKernelModules = [ "virtio_blk" "xhci_pci" "sd_mod" ];
      boot.kernelModules = [ ];
      hardware.cpu.amd.updateMicrocode = lib.mkDefault true;'

hardware_plain_xfs='      fileSystems."/" = {
        device = "/dev/disk/by-label/XFS-root";
        fsType = "xfs";
      };
      fileSystems."/boot" = {
        device = "/dev/disk/by-label/XFS-boot";
        fsType = "vfat";
      };
      swapDevices = [ { device = "/dev/disk/by-label/XFS-swap"; } ];
      boot.initrd.availableKernelModules = [ "nvme" "usbhid" "sd_mod" ];
      boot.kernelModules = [ ];
      hardware.cpu.intel.updateMicrocode = lib.mkDefault true;'

prepare_config alpha UTC en_US.UTF-8 us
write_hardware "$work/alpha" "$hardware_plain_ext4"

prepare_config beta Europe/Berlin de_DE.UTF-8 de
write_hardware "$work/beta" "$hardware_luks_xfs"

prepare_config gamma Europe/Amsterdam nl_NL.UTF-8 nl
write_hardware "$work/gamma" "$hardware_btrfs"

prepare_config delta America/New_York fr_FR.UTF-8 fr
write_hardware "$work/delta" "$hardware_luks_ext4"

prepare_config epsilon Europe/London en_GB.UTF-8 uk
write_hardware "$work/epsilon" "$hardware_plain_xfs"

tops=()
for name in alpha beta gamma delta epsilon; do
  echo "evaluating fixture $name"
  tops+=("$(nix eval --raw "path:$work/$name#nixosConfigurations.$name.config.system.build.toplevel.drvPath")")
done

echo "computing the stable frontier across ${#tops[@]} configurations"
echo '[]' >"$work/build.json"
: >"$work/failed.txt"
converged=0
for round in 1 2 3 4 5 6 7 8 9 10; do
  python3 "$repo/scripts/offline-preload-paths.py" \
    --baseline "$work/baseline.json" \
    --build "$work/build.json" \
    "${tops[@]}" >"$work/frontier.txt"
  mapfile -t paths <"$work/frontier.txt"
  if [ "${#paths[@]}" -eq 0 ]; then
    converged=1
    break
  fi
  printf '%s\n' "${paths[@]}" |
    xargs -P "$parallel" -I{} sh -c 'nix path-info --store https://cache.nixos.org "$1" >/dev/null 2>&1 && printf "%s\n" "$1" || true' _ {} |
    sort -u >"$work/cached.txt"
  comm -23 <(printf '%s\n' "${paths[@]}" | sort -u) "$work/cached.txt" >"$work/uncached.txt"
  if [ ! -s "$work/uncached.txt" ]; then
    converged=1
    break
  fi
  echo "round $round: $(wc -l <"$work/uncached.txt") paths are not substitutable, tracing their inputs"
  cat "$work/uncached.txt" >>"$work/failed.txt"
  python3 -c 'import json, sys; print(json.dumps(sorted(set(open(sys.argv[1]).read().split()))))' \
    "$work/failed.txt" >"$work/build.json"
done

if [ "$converged" -ne 1 ]; then
  echo "offline-preload-frontier: frontier did not converge" >&2
  exit 1
fi

echo "preloading ${#paths[@]} frontier paths"
cp "$work/frontier.txt" "$repo/nixos/preload-paths.txt"
git -C "$repo" add nixos/preload-paths.txt 2>/dev/null || true
keep=1
echo "wrote $repo/nixos/preload-paths.txt with ${#paths[@]} paths"
echo "now build the ISO with: nix build .#ojuny-iso-offline"
