#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${OJUNY_INSTALLER_SOURCE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

flake="${OJUNY_FLAKE:-}"
disk="auto"
firmware="auto"
mode="bundled"
host="ojuny"
username="user"
full_name="Primary account"
password=""
shell="zsh"
timezone="UTC"
locale="en_US.UTF-8"
keymap="us"
swap_size="0"
encryption_enable=0
encryption_passphrase=""
confirm_seconds="10"
final_action="reboot"
clone_relative="repos/nix-flake"
state_version="26.11"
output_dir="$PWD/result-unattended"
dry_run=0
offline=0
discovery=0
variant_set=0
interactive=0
password_prompted=0
ssh_prompted=0
ssh_keys=()

usage() {
  cat <<'EOF'
Usage: make-unattended-iso.sh [options]

Build an unattended Ojuny ISO from the base template or your own fork. The
template is passed to --override-input, so no clone is needed. The ISO installs
the flake and leaves the modified copy at /home/<user>/repos/nix-flake.

Options:
  --template URL|PATH    Template fork used through --override-input
  --flake URL|PATH       Alias for --template
  --disk DEVICE         Target disk, or auto to select at boot (default: auto)
  --firmware auto|efi|bios
                        Target firmware (default: auto)
  --mode prepared|bundled
                        Use the fork as-is or generate user/host (default: prepared)
  --host NAME           Host name for bundled mode (empty: detect or use ojuny)
  --username NAME       Account name (empty: detect in prepared mode)
  --full-name NAME      Account description for bundled mode
  --shell SHELL         zsh, bash or fish for bundled mode
  --timezone ZONE       Time zone for bundled mode
  --locale LOCALE       Locale for bundled mode
  --keymap KEYMAP       Console keymap for bundled mode
  --swap-size SIZE      Swap partition size, 0 to disable (default: 0)
  --encrypt             Enable LUKS2 root encryption
  --encryption-passphrase PASS
                        LUKS passphrase (prompted when --encrypt is used)
  --ssh-key KEY         SSH public key, repeatable
  --confirm-seconds N   Countdown before wiping (default: 10)
  --final-action ACTION reboot or poweroff (default: reboot)
  --clone-relative PATH Path under the home directory (default: repos/nix-flake)
  --state-version VER   stateVersion for bundled mode (default: 26.11)
  --output DIR          Copy the ISO here (default: ./result-unattended)
  --interactive         Show the interactive menu even when flags are given
  --online              Build the online ISO
  --offline             Build the full-system offline ISO
  --discovery           Build the local cache discovery ISO
  --dry-run             Print the settings and build command
  -h, --help            Show this help
EOF
}

if [ "$#" -eq 0 ] && [ -t 0 ]; then
  interactive=1
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --template | --flake)
      flake="${2:-}"
      shift 2
      ;;
    --disk)
      disk="${2:-}"
      shift 2
      ;;
    --firmware)
      firmware="${2:-}"
      shift 2
      ;;
    --mode)
      mode="${2:-}"
      shift 2
      ;;
    --host)
      host="${2:-}"
      shift 2
      ;;
    --username)
      username="${2:-}"
      shift 2
      ;;
    --full-name)
      full_name="${2:-}"
      shift 2
      ;;
    --shell)
      shell="${2:-}"
      shift 2
      ;;
    --timezone)
      timezone="${2:-}"
      shift 2
      ;;
    --locale)
      locale="${2:-}"
      shift 2
      ;;
    --keymap)
      keymap="${2:-}"
      shift 2
      ;;
    --swap-size)
      swap_size="${2:-}"
      shift 2
      ;;
    --encrypt)
      encryption_enable=1
      shift
      ;;
    --encryption-passphrase)
      encryption_enable=1
      encryption_passphrase="${2:-}"
      shift 2
      ;;
    --ssh-key)
      ssh_keys+=("${2:-}")
      shift 2
      ;;
    --confirm-seconds)
      confirm_seconds="${2:-}"
      shift 2
      ;;
    --final-action)
      final_action="${2:-}"
      shift 2
      ;;
    --clone-relative)
      clone_relative="${2:-}"
      shift 2
      ;;
    --state-version)
      state_version="${2:-}"
      shift 2
      ;;
    --output)
      output_dir="${2:-}"
      shift 2
      ;;
    --interactive)
      interactive=1
      shift
      ;;
    --online)
      variant_set=1
      shift
      ;;
    --offline)
      offline=1
      variant_set=1
      shift
      ;;
    --discovery)
      discovery=1
      variant_set=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "make-unattended-iso: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$interactive" -eq 1 ]; then
  cat <<'EOF'
============================================================
  Ojuny unattended ISO
============================================================

Build an unattended installer from the base template or your own fork.
Press Enter to accept a default.

EOF

  PS3="ISO variant: "
  select variant in "online" "offline" "discovery"; do
    case "$variant" in
      online) break ;;
      offline)
        offline=1
        break
        ;;
      discovery)
        discovery=1
        break
        ;;
    esac
  done
  variant_set=1

  read -r -p "Template URL or path [github:ojuny-project/ojuny-template]: " answer
  flake="${answer:-github:ojuny-project/ojuny-template}"

  read -r -p "Target disk [auto]: " answer
  disk="${answer:-auto}"

  PS3="Firmware: "
  select choice in "auto" "efi" "bios"; do
    case "$choice" in
      auto | efi | bios)
        firmware="$choice"
        break
        ;;
    esac
  done

  PS3="Mode: "
  select choice in "bundled (generic account)" "prepared (fork as-is)"; do
    case "$choice" in
      bundled*) mode="bundled"; break ;;
      prepared*) mode="prepared"; break ;;
    esac
  done

  if [ "$mode" = "bundled" ]; then
    read -r -p "Username [user]: " answer
    username="${answer:-user}"
    read -r -p "Hostname [ojuny]: " answer
    host="${answer:-ojuny}"
    read -r -p "Account description [Primary account]: " answer
    full_name="${answer:-Primary account}"
    read -r -p "Login shell [zsh]: " answer
    shell="${answer:-zsh}"
    read -r -p "Time zone [UTC]: " answer
    timezone="${answer:-UTC}"
    read -r -p "Locale [en_US.UTF-8]: " answer
    locale="${answer:-en_US.UTF-8}"
    read -r -p "Console keymap [us]: " answer
    keymap="${answer:-us}"
  fi

  read -r -p "Swap size, 0 to disable [0]: " answer
  swap_size="${answer:-0}"

  read -r -p "Encrypt the root with LUKS2? [y/N]: " answer
  case "$answer" in
    [yY]*) encryption_enable=1 ;;
    *) encryption_enable=0 ;;
  esac
  if [ "$encryption_enable" -eq 1 ]; then
    read -r -s -p "LUKS passphrase: " encryption_passphrase
    echo
  fi

  read -r -s -p "Password (empty locks the account): " password
  echo
  password_prompted=1

  while true; do
    read -r -p "SSH public key (empty to finish): " key
    [ -z "$key" ] && break
    ssh_keys+=("$key")
  done
  ssh_prompted=1

  PS3="After install: "
  select choice in "reboot" "poweroff"; do
    case "$choice" in
      reboot | poweroff)
        final_action="$choice"
        break
        ;;
    esac
  done

  read -r -p "Output directory [./result-unattended]: " answer
  output_dir="${answer:-$PWD/result-unattended}"
fi

if [ "$offline" -eq 1 ] && [ "$discovery" -eq 1 ]; then
  echo "make-unattended-iso: --offline and --discovery are mutually exclusive" >&2
  exit 2
fi

if [ "$variant_set" -eq 0 ] && [ -t 0 ]; then
  PS3="Unattended ISO variant: "
  select variant in "online" "offline" "discovery"; do
    case "$variant" in
      online) break ;;
      offline)
        offline=1
        break
        ;;
      discovery)
        discovery=1
        break
        ;;
    esac
  done
fi

if [ -z "$flake" ]; then
  if [ -t 0 ]; then
    read -r -p "Template URL or path [github:ojuny-project/ojuny-template]: " flake
  fi
  flake="${flake:-github:ojuny-project/ojuny-template}"
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

flake_ref="$flake"
case "$flake" in
  http://* | https://* | git+* | ssh://* | git@* | github:* | gitlab:* | path:*)
    ;;
  *)
    if [ ! -f "$flake/flake.nix" ] || [ ! -d "$flake/modules" ]; then
      echo "make-unattended-iso: $flake is not an ojuny-template repository" >&2
      exit 1
    fi
    flake_ref="path:$(cd "$flake" && pwd)"
    ;;
esac

case "$mode" in
  prepared | bundled) ;;
  *)
    echo "make-unattended-iso: mode must be prepared or bundled" >&2
    exit 2
    ;;
esac

case "$firmware" in
  auto | efi | bios) ;;
  *)
    echo "make-unattended-iso: firmware must be auto, efi or bios" >&2
    exit 2
    ;;
esac

case "$final_action" in
  reboot | poweroff) ;;
  *)
    echo "make-unattended-iso: final action must be reboot or poweroff" >&2
    exit 2
    ;;
esac

if [ -z "$disk" ]; then
  read -r -p "Target disk (prefer /dev/disk/by-id/...): " disk
fi

case "$disk" in
  auto | /dev/*) ;;
  *)
    echo "make-unattended-iso: disk must be auto or start with /dev/" >&2
    exit 2
    ;;
esac

if [ "$encryption_enable" -eq 1 ] && [ -z "$encryption_passphrase" ]; then
  read -r -s -p "LUKS passphrase: " encryption_passphrase
  echo
fi

if [ "$encryption_enable" -eq 1 ] && [ -z "$encryption_passphrase" ]; then
  echo "make-unattended-iso: encryption passphrase must not be empty" >&2
  exit 2
fi

if [ "$disk" != "auto" ] && [ ! -b "$disk" ]; then
  echo "make-unattended-iso: warning: $disk is not attached to this machine" >&2
fi

if [ "$mode" != "prepared" ]; then
  if [ -z "$username" ]; then
    read -r -p "Username [user]: " username
    username="${username:-user}"
  fi
  if [ -z "$host" ]; then
    read -r -p "Hostname [ojuny]: " host
    host="${host:-ojuny}"
  fi
  if [ -z "$full_name" ]; then
    read -r -p "Description [Primary account]: " full_name
    full_name="${full_name:-Primary account}"
  fi
  if [ -z "$shell" ]; then
    read -r -p "Login shell [zsh]: " shell
    shell="${shell:-zsh}"
  fi
  if [ -z "$timezone" ]; then
    read -r -p "Time zone [Europe/Amsterdam]: " timezone
    timezone="${timezone:-Europe/Amsterdam}"
  fi
  if [ -z "$locale" ]; then
    read -r -p "Locale [en_US.UTF-8]: " locale
    locale="${locale:-en_US.UTF-8}"
  fi
  if [ -z "$keymap" ]; then
    read -r -p "Console keymap [us]: " keymap
    keymap="${keymap:-us}"
  fi
fi

if [ "$password_prompted" -eq 0 ]; then
  read -r -s -p "Password (empty keeps the flake value or locks the account): " password
  echo
  password_prompted=1
fi

hashed_password=""
if [ -n "$password" ]; then
  if ! command -v mkpasswd >/dev/null 2>&1; then
    echo "make-unattended-iso: mkpasswd not found, run inside nix develop" >&2
    exit 1
  fi
  hashed_password="$(mkpasswd -m yescrypt -- "$password" 2>/dev/null || mkpasswd -m sha-512 -- "$password")"
fi

if [ "${#ssh_keys[@]}" -eq 0 ] && [ "$ssh_prompted" -eq 0 ]; then
  while true; do
    read -r -p "SSH public key (empty to finish): " key
    [ -z "$key" ] && break
    ssh_keys+=("$key")
  done
fi

tmp="$work_dir/settings"
mkdir -p "$tmp"

export OJUNY_DISK="$disk"
export OJUNY_FIRMWARE="$firmware"
export OJUNY_MODE="$mode"
export OJUNY_HOST="$host"
export OJUNY_USERNAME="$username"
export OJUNY_FULL_NAME="$full_name"
export OJUNY_HASHED_PASSWORD="$hashed_password"
ssh_keys_text="$(printf '%s\n' "${ssh_keys[@]}")"
export OJUNY_SSH_KEYS="$ssh_keys_text"
export OJUNY_SHELL="$shell"
export OJUNY_TIMEZONE="$timezone"
export OJUNY_LOCALE="$locale"
export OJUNY_KEYMAP="$keymap"
export OJUNY_SWAP_SIZE="$swap_size"
export OJUNY_ENCRYPTION_ENABLE="$encryption_enable"
export OJUNY_ENCRYPTION_PASSPHRASE="$encryption_passphrase"
export OJUNY_CONFIRM_SECONDS="$confirm_seconds"
export OJUNY_FINAL_ACTION="$final_action"
export OJUNY_CLONE_RELATIVE="$clone_relative"
export OJUNY_STATE_VERSION="$state_version"
export OJUNY_SETTINGS_JSON="$tmp/settings.json"

python3 <<'PY'
import json
import os


def optional(name):
    value = os.environ.get(name, "")
    return value if value else None


keys = [line for line in os.environ.get("OJUNY_SSH_KEYS", "").splitlines() if line]
mode = os.environ["OJUNY_MODE"]
hashed = optional("OJUNY_HASHED_PASSWORD")
if mode == "bundled" and hashed is None:
    hashed = "!"

settings = {
    "mode": mode,
    "disk": os.environ["OJUNY_DISK"],
    "firmware": os.environ["OJUNY_FIRMWARE"],
    "host": optional("OJUNY_HOST"),
    "username": optional("OJUNY_USERNAME"),
    "fullName": optional("OJUNY_FULL_NAME"),
    "hashedPassword": hashed,
    "sshKeys": keys,
    "shell": optional("OJUNY_SHELL"),
    "timezone": optional("OJUNY_TIMEZONE"),
    "locale": optional("OJUNY_LOCALE"),
    "keymap": optional("OJUNY_KEYMAP"),
    "swapSize": os.environ["OJUNY_SWAP_SIZE"],
    "encryption": {
        "enable": os.environ["OJUNY_ENCRYPTION_ENABLE"] == "1",
        "passphrase": optional("OJUNY_ENCRYPTION_PASSPHRASE"),
    },
    "cloneRelative": os.environ["OJUNY_CLONE_RELATIVE"],
    "stateVersion": os.environ["OJUNY_STATE_VERSION"],
    "confirmSeconds": int(os.environ["OJUNY_CONFIRM_SECONDS"]),
    "finalAction": os.environ["OJUNY_FINAL_ACTION"],
}

with open(os.environ["OJUNY_SETTINGS_JSON"], "w") as handle:
    json.dump(settings, handle, indent=2)
    handle.write("\n")
PY

cat >"$tmp/flake.nix" <<'EOF'
{
  outputs = _: {
    settings = builtins.fromJSON (builtins.readFile ./settings.json);
  };
}
EOF

if [ "$discovery" -eq 1 ]; then
  iso_output="unattended-iso-discovery"
elif [ "$offline" -eq 1 ]; then
  iso_output="unattended-iso-offline"
else
  iso_output="unattended-iso"
fi

build_args=(
  "path:$REPO_ROOT#$iso_output"
  --override-input ojuny-template "$flake_ref"
  --override-input settings "path:$tmp"
  --no-write-lock-file
  --no-link
  --print-out-paths
)

if [ "$dry_run" -eq 1 ]; then
  echo "settings:"
  cat "$OJUNY_SETTINGS_JSON"
  printf 'nix build'
  printf ' %q' "${build_args[@]}"
  printf '\n'
  exit 0
fi

echo "building ISO from $flake"
out="$(nix build "${build_args[@]}")"

iso="$(find "$out" -type f -name '*.iso' -print -quit)"
if [ -z "$iso" ]; then
  echo "make-unattended-iso: no ISO found in $out" >&2
  exit 1
fi

mkdir -p "$output_dir"
cp "$iso" "$output_dir/"
iso_name="$(basename "$iso")"

size="$(stat -c %s "$output_dir/$iso_name")"

echo
echo "ISO: $output_dir/$iso_name"
echo "size: $size bytes"
if [ "$size" -gt 7400000000 ]; then
  echo "warning: ISO exceeds 7.4 GB; an 8 GB USB may not fit it" >&2
fi
sha256sum "$output_dir/$iso_name"
