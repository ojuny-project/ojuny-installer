#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: check-offline-install-vm.sh [ISO]

Boots the offline unattended ISO in QEMU with no network device and waits for
the install to power the machine off. The install failing leaves the VM in the
failure shell, so the timeout is the failure signal.

Arguments:
  ISO                   Use an existing ISO instead of building one.

Environment:
  TIMEOUT               Seconds to wait for the install (default: 3600)
  MEMORY                VM memory in MiB (default: 4096)
  CPUS                  VM CPU count (default: 2)
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

iso="${1:-}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
timeout_seconds="${TIMEOUT:-3600}"
memory="${MEMORY:-4096}"
cpus="${CPUS:-2}"

if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
  echo "check-offline-install-vm: qemu-system-x86_64 not found" >&2
  exit 2
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [ -z "$iso" ]; then
  mkdir -p "$work/settings"
  cat >"$work/settings/flake.nix" <<'EOF'
{
  outputs = _: {
    settings = builtins.fromJSON (builtins.readFile ./settings.json);
  };
}
EOF
  cat >"$work/settings/settings.json" <<'EOF'
{
  "mode": "bundled",
  "disk": "/dev/vda",
  "firmware": "bios",
  "host": "fixture-host",
  "username": "fixture",
  "fullName": "Fixture Account",
  "hashedPassword": "!",
  "sshKeys": [],
  "shell": "bash",
  "timezone": "UTC",
  "locale": "en_US.UTF-8",
  "keymap": "us",
  "swapSize": "0",
  "encryption": {
    "enable": false,
    "passphrase": null
  },
  "cloneRelative": "repos/nix-flake",
  "stateVersion": "26.11",
  "confirmSeconds": 0,
  "finalAction": "poweroff"
}
EOF

  echo "building offline unattended ISO"
  out="$(nix build "$repo_root#unattended-iso-offline" \
    --override-input settings "path:$work/settings" \
    --no-write-lock-file \
    --no-link \
    --print-out-paths)"
  iso="$(find "$out" -type f -name '*.iso' -print -quit)"
fi

if [ ! -f "$iso" ]; then
  echo "check-offline-install-vm: no ISO at $iso" >&2
  exit 2
fi

qemu-img create -f qcow2 "$work/disk.qcow2" 20G >/dev/null

qemu_args=(
  -m "$memory"
  -smp "$cpus"
  -drive "file=$work/disk.qcow2,if=virtio,format=qcow2"
  -cdrom "$iso"
  -boot order=d
  -nic none
  -no-reboot
  -display none
  -serial null
)

if [ -w /dev/kvm ]; then
  qemu_args+=(-enable-kvm -cpu host)
else
  qemu_args+=(-cpu max)
fi

echo "booting offline ISO with no network device"
if timeout "$timeout_seconds" qemu-system-x86_64 "${qemu_args[@]}"; then
  echo "offline install completed and powered off"
else
  status=$?
  if [ "$status" -eq 124 ]; then
    echo "check-offline-install-vm: install did not power off within ${timeout_seconds}s" >&2
  else
    echo "check-offline-install-vm: qemu exited with status $status" >&2
  fi
  exit 1
fi
