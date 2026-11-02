#!/usr/bin/env bash
set -euo pipefail

if [ -z "${TEMPLATE:-}" ] || [ -z "${PREPARE_REPO:-}" ] || [ -z "${EVAL_CLOSURE:-}" ]; then
  echo "check-offline-install-closure: TEMPLATE, PREPARE_REPO and EVAL_CLOSURE must be set" >&2
  exit 2
fi

work="$(mktemp -d)"
cleanup() {
  chmod -R u+w "$work" 2>/dev/null || true
  rm -rf "$work" 2>/dev/null || true
}
trap cleanup EXIT

"$PREPARE_REPO/bin/prepare-repo" \
  --root "$work/flake" \
  --template "$TEMPLATE" \
  --username fixture \
  --fullname "Fixture Account" \
  --hashed-password '$6$VHOzJbAlJ4mzcEMh$0HBRrS/wD8f8t6VqdNIpIpc54sImrnoHEMyp8PCVG/22i0nDxeGLNyWd6YyyWsCCRe33P.UTC7AL6yiNcMKHH0' \
  --shell bash \
  --hostname fixture-host \
  --state-version 26.11 \
  --clone-relative repos/nix-flake \
  --force \
  --timezone UTC \
  --locale en_US.UTF-8 \
  --keymap us

cat >"$work/flake/modules/07-system/00-hardware.nix" <<'EOF'
{ self, ... }: {

  flake.modules.nixos.system-hardware =
    { lib, ... }:
    {
      fileSystems."/" = {
        device = "/dev/disk/by-label/fixture-root";
        fsType = "ext4";
      };
      fileSystems."/boot" = {
        device = "/dev/disk/by-label/fixture-boot";
        fsType = "vfat";
      };
      boot.initrd.availableKernelModules = [
        "ahci"
        "nvme"
        "xhci_pci"
        "usb_storage"
        "sd_mod"
      ];
      boot.kernelModules = [ "kvm-amd" ];
      hardware.cpu.amd.updateMicrocode = lib.mkDefault true;
      swapDevices = [ ];
    };

  flake.modules.nixos.system-bootloader = {
    boot.loader.grub.enable = true;
    boot.loader.grub.device = "/dev/vda";
  };

}
EOF

mapfile -t flakeInputs < <(grep -v '^$' <<<"$FLAKE_INPUTS" | sort -u)
if [ "${#flakeInputs[@]}" -eq 0 ]; then
  echo "check-offline-install-closure: FLAKE_INPUTS is empty" >&2
  exit 2
fi

mapfile -t evalPaths <"$EVAL_CLOSURE/store-paths"
mapfile -t storePaths < <(printf '%s\n' "${evalPaths[@]}" "${flakeInputs[@]}" | grep -v '^$' | sort -u)

mkdir -p "$work/target/nix/store"
database="$work/target-database"
: >"$database"
echo "preloading ${#storePaths[@]} store paths into the target store"
for source in "${storePaths[@]}"; do
  nix-store --dump "$source" |
    nix-store --store "$work/target" --restore "$work/target$source"
  printf '%s\n%s\n0\n\n0\n' "$source" "$(nix-hash --type sha256 --base16 "$source")" >>"$database"
done
nix-store --store "$work/target" --load-db <"$database"

python3 - "$work/flake/flake.lock" "$FLAKE_INPUT_PATHS" <<'PY'
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

nix --extra-experimental-features "nix-command flakes" eval \
  --store "$work/target" \
  --offline \
  --raw \
  "$work/flake#nixosConfigurations.fixture-host.config.system.build.toplevel.drvPath" \
  >/dev/null

echo "evaluation succeeded against the preloaded flake inputs"

nix --extra-experimental-features "nix-command flakes" build \
  --store "$work/target" \
  --offline \
  --dry-run \
  --no-link \
  "$work/flake#nixosConfigurations.fixture-host.config.system.build.toplevel"
