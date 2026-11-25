#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=test-qemu-common.sh
source "$script_dir/test-qemu-common.sh"

iso_arg=""
disk="/tmp/ojuny-git-presetup.qcow2"
user="ojuny"
origin=""
no_origin=0
token=""
check_only=0

usage() {
    cat <<'EOF'
Usage: scripts/test-git-presetup-install.sh [options]

Boot the attended ISO with the bundled template, set up git on the origin page,
then inspect the installed disk. The Calamares pages are completed by hand.

Options:
  --iso PATH        Attended ISO to boot. Default: result-installer/iso/*.iso
  --disk PATH       Target qcow2. Default: /tmp/ojuny-git-presetup.qcow2
  --user NAME       Account to check. Default: ojuny
  --origin URL      Origin URL to enter on the git origin page.
  --token TOKEN     HTTPS token to enter on the git origin page.
  --no-origin       Leave the origin URL empty.
  --check-only      Inspect an existing disk and skip QEMU.
  --help            Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --iso) iso_arg=$2; shift 2 ;;
        --disk) disk=$2; shift 2 ;;
        --user) user=$2; shift 2 ;;
        --origin) origin=$2; shift 2 ;;
        --token) token=$2; shift 2 ;;
        --no-origin) no_origin=1; shift ;;
        --check-only) check_only=1; shift ;;
        --help) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

if [[ -z "$origin" && "$no_origin" == 0 ]]; then
    fail "pass --origin URL or --no-origin"
fi
if [[ -n "$origin" && "$no_origin" == 1 ]]; then
    fail "--origin and --no-origin are mutually exclusive"
fi
if [[ -n "$token" && "$origin" != https://* ]]; then
    fail "--token requires an https:// --origin URL"
fi

expect_credentials=no
[[ -n "$token" ]] && expect_credentials=yes

if [[ "$check_only" == 0 ]]; then
    iso=$(resolve_iso "$iso_arg")
    create_disk "$disk"

    echo "ISO: $iso"
    echo "Disk: $disk"
    echo
    echo "In Calamares:"
    echo "  Template page: choose the bundled Ojuny template."
    echo "  Users page: create account '$user'."
    if [[ "$no_origin" == 1 ]]; then
        echo "  Git origin page: leave the origin URL empty."
    else
        echo "  Git origin page: Origin URL $origin"
        [[ -n "$token" ]] && echo "  Git token: the token passed on the command line."
    fi
    echo "  Partition page: use the target disk shown in QEMU."
    echo "  When the install finishes, power off the machine."
    echo

    boot_vm "$iso" "$disk"
fi

mount_installed_root "$disk" 
home="$MOUNT_DIR/home/$user"
repo="$home/repos/nix-flake"

assert_file "$repo"
assert_git_repo "$repo"
assert_commit_author "$repo"
assert_remote "$repo" "$origin"
assert_credentials "$home" "$expect_credentials"

if [[ "$expect_credentials" == "yes" ]]; then
    assert_credential_helper "$repo"
fi

if [[ "$no_origin" == 1 ]]; then
    echo "PASS: git pre-setup with no origin"
else
    echo "PASS: git pre-setup with origin $origin"
fi
