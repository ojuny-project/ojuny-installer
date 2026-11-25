#!/usr/bin/env bash
set -euo pipefail

NBD_DEVICE="${NBD_DEVICE:-/dev/nbd0}"
MOUNT_DIR=""
ATTACHED=0

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require() {
    command -v "$1"  || fail "missing command: $1"
}

firmware_path() {
    if [[ -n "${OVMF_FD:-}" ]]; then
        printf '%s\n' "$OVMF_FD"
        return
    fi
    require nix
    local store_path
    store_path=$(nix build --no-link --print-out-paths nixpkgs#OVMF.fd)
    printf '%s/FV/OVMF.fd\n' "$store_path"
}

resolve_iso() {
    local requested="${1:-}"
    if [[ -n "$requested" ]]; then
        printf '%s\n' "$requested"
        return
    fi
    local found
    found=$(ls result-installer/iso/*.iso  | head -n1 || true)
    [[ -n "$found" ]] || fail "no ISO found; pass --iso or build result-installer"
    printf '%s\n' "$found"
}

create_disk() {
    local disk=$1
    require qemu-img
    if [[ ! -e "$disk" ]]; then
        qemu-img create -f qcow2 "$disk" 30G >/dev/null
    fi
}

cleanup_disk() {
    if [[ -n "$MOUNT_DIR" ]]; then
        sudo umount "$MOUNT_DIR"  || true
        rmdir "$MOUNT_DIR"  || true
        MOUNT_DIR=""
    fi
    if [[ "$ATTACHED" == 1 ]]; then
        sudo qemu-nbd --disconnect "$NBD_DEVICE"  || true
        ATTACHED=0
    fi
}

trap cleanup_disk EXIT

boot_vm() {
    local iso=$1
    local disk=$2
    local firmware
    require qemu-system-x86_64
    firmware=$(firmware_path)
    qemu-system-x86_64 \
        -enable-kvm -m 4096 -smp 4 -cpu host \
        -bios "$firmware" \
        -device virtio-vga-gl \
        -device virtio-keyboard-pci -device virtio-tablet-pci \
        -drive file="$iso",media=cdrom,readonly=on \
        -drive file="$disk",if=virtio \
        -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
        -display "${QEMU_DISPLAY:-gtk,gl=on}"
}

mount_installed_root() {
    local disk=$1
    require sudo
    require qemu-nbd
    require lsblk
    sudo modprobe nbd max_part=16
    sudo qemu-nbd --disconnect "$NBD_DEVICE"  || true
    sudo qemu-nbd --connect="$NBD_DEVICE" --read-only "$disk"
    ATTACHED=1
    sudo partprobe "$NBD_DEVICE"  || true

    local root_part=""
    local attempt
    for attempt in $(seq 1 20); do
        root_part=$(lsblk -ln -o NAME,FSTYPE "$NBD_DEVICE" |
            awk '$2 == "ext4" { print "/dev/" $1; exit }')
        [[ -n "$root_part" ]] && break
        sleep 0.5
    done
    [[ -n "$root_part" ]] || fail "no ext4 root partition on $NBD_DEVICE"

    MOUNT_DIR=$(mktemp -d)
    sudo mount -o ro,noload "$root_part" "$MOUNT_DIR"
    printf '%s\n' "$MOUNT_DIR"
}

assert_file() {
    [[ -e "$1" ]] || fail "missing $1"
}

assert_git_repo() {
    [[ -d "$1/.git" ]] || fail "not a git repository: $1"
}

assert_commit_author() {
    local repo=$1
    require git
    local author
    author=$(git -c safe.directory='*' -C "$repo" log -1 --format='%an <%ae>')
    [[ "$author" == "Ojuny Installer <installer@ojuny.local>" ]] ||
        fail "commit author is '$author'"
}

assert_remote() {
    local repo=$1
    local expected=$2
    require git
    if [[ -z "$expected" ]]; then
        local remotes
        remotes=$(git -c safe.directory='*' -C "$repo" remote)
        [[ -z "$remotes" ]] || fail "unexpected remotes: $remotes"
        return
    fi
    local actual
    actual=$(git -c safe.directory='*' -C "$repo" remote get-url origin)
    [[ "$actual" == "$expected" ]] ||
        fail "origin is '$actual', expected '$expected'"
}

assert_credentials() {
    local home=$1
    local expected=$2
    local credentials="$home/.git-credentials"
    if [[ "$expected" == "yes" ]]; then
        [[ -f "$credentials" ]] || fail "expected $credentials"
        local mode
        mode=$(stat -c '%a' "$credentials")
        [[ "$mode" == "600" ]] ||
            fail "$credentials mode is $mode, expected 600"
    else
        [[ ! -e "$credentials" ]] || fail "unexpected $credentials"
    fi
}

assert_credential_helper() {
    local repo=$1
    require git
    local helper
    helper=$(git -c safe.directory='*' -C "$repo" config --get credential.helper || true)
    [[ "$helper" == *".git-credentials"* ]] ||
        fail "credential helper is '$helper'"
}
