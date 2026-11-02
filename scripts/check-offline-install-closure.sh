#!/usr/bin/env bash
set -euo pipefail

if [ -z "${TEMPLATE:-}" ] || [ -z "${PREPARE_REPO:-}" ]; then
  echo "check-offline-install-closure: TEMPLATE and PREPARE_REPO must be set" >&2
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
  --hashed-password '!' \
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

mkdir -p "$work/target/nix/store"
database="$work/target-database"
: >"$database"
echo "preloading ${#flakeInputs[@]} flake inputs into the target store"
for source in "${flakeInputs[@]}"; do
  nix-store --dump "$source" |
    nix-store --store "$work/target" --restore "$work/target$source"
  printf '%s\n%s\n0\n\n0\n' "$source" "$(nix-hash --type sha256 --base16 "$source")" >>"$database"
done
nix-store --store "$work/target" --load-db <"$database"

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
