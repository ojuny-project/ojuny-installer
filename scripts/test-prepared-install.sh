#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=test-qemu-common.sh
source "$script_dir/test-qemu-common.sh"

iso_arg=""
disk="/tmp/ojuny-prepared.qcow2"
user="ojuny"
template=""
template_dir="${HOME}/repos/ojuny-template"
branch=""
token=""
check_only=0
git_daemon_pid=""

usage() {
    cat <<'EOF'
Usage: scripts/test-prepared-install.sh [options]

Boot the attended ISO and install from a prepared ojuny-template repository,
then inspect the installed disk. The Calamares pages are completed by hand.

Options:
  --iso PATH            Attended ISO to boot. Default: result-installer/iso/*.iso
  --disk PATH           Target qcow2. Default: /tmp/ojuny-prepared.qcow2
  --user NAME           Account to check. Default: ojuny
  --template URL        Prepared repository URL. Disables the local git daemon.
  --template-dir PATH   Local repository to export over git://.
                        Default: ~/repos/ojuny-template
  --branch NAME         Branch to enter on the template page.
  --token TOKEN         HTTPS token to enter on the template page.
  --check-only          Inspect an existing disk and skip QEMU.
  --help                Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --iso) iso_arg=$2; shift 2 ;;
        --disk) disk=$2; shift 2 ;;
        --user) user=$2; shift 2 ;;
        --template) template=$2; shift 2 ;;
        --template-dir) template_dir=$2; shift 2 ;;
        --branch) branch=$2; shift 2 ;;
        --token) token=$2; shift 2 ;;
        --check-only) check_only=1; shift ;;
        --help) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

if [[ -n "$token" && "$template" != https://* ]]; then
    fail "--token requires an https:// --template URL"
fi

if [[ -z "$template" ]]; then
    [[ -d "$template_dir/.git" ]] || fail "not a git repository: $template_dir"
    template_base=$(cd "$(dirname "$template_dir")" && pwd)
    template="git://10.0.2.2/$(basename "$template_dir")"
fi

expected_remote="$template"
expect_credentials=no
[[ -n "$token" ]] && expect_credentials=yes

cleanup() {
    if [[ -n "$git_daemon_pid" ]]; then
        kill "$git_daemon_pid"  || true
        git_daemon_pid=""
    fi
    cleanup_disk
}
trap cleanup EXIT

if [[ "$check_only" == 0 ]]; then
    iso=$(resolve_iso "$iso_arg")
    create_disk "$disk"

    if [[ -n "${template_base:-}" ]]; then
        require git
        git daemon \
            --reuseaddr --export-all \
            --base-path="$template_base" \
            --listen=0.0.0.0 --port=9418 \
            "$template_base" &
        git_daemon_pid=$!
        sleep 1
    fi

    echo "ISO: $iso"
    echo "Disk: $disk"
    echo
    echo "In Calamares:"
    echo "  Template page: choose the prepared repository."
    echo "  Repository URL: $template"
    [[ -n "$branch" ]] && echo "  Branch: $branch"
    [[ -n "$token" ]] && echo "  Git token: the token passed on the command line."
    echo "  Users page: create account '$user'."
    echo "  Partition page: use the target disk shown in QEMU."
    echo "  Summary page: confirm the template and repository names."
    echo "  When the install finishes, power off the machine."
    echo

    boot_vm "$iso" "$disk"
fi

mount_installed_root "$disk" 
home="$MOUNT_DIR/home/$user"
repo="$home/repos/nix-flake"

assert_file "$repo"
assert_git_repo "$repo"
assert_remote "$repo" "$expected_remote"
assert_credentials "$home" "$expect_credentials"

if [[ "$expect_credentials" == "yes" ]]; then
    assert_credential_helper "$repo"
fi

if [[ -n "$branch" ]]; then
    actual_branch=$(git -c safe.directory='*' -C "$repo" branch --show-current)
    [[ "$actual_branch" == "$branch" ]] ||
        fail "branch is '$actual_branch', expected '$branch'"
fi

git -c safe.directory='*' -C "$repo" log --format=%s |
    grep -q "Regenerate hardware for this machine" ||
    fail "missing the hardware regeneration commit"

echo "PASS: prepared install from $template"
