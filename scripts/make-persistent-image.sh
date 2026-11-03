#!/usr/bin/env bash
set -euo pipefail

output_dir="${OJUNY_OUTPUT_DIR:-$PWD}"
qcow2=0

usage() {
  cat <<'EOF'
Usage: make-persistent-image [options]

Build the base Ojuny persistent image. The image uses a tmpfs root, a read-only
nix store in an overlay and a persistent /home. The output is a raw .img that
can be written with Etcher or Rufus in DD mode.

Options:
  --output DIR          Write the image here (default: current directory)
  --qcow2               Also write a qcow2 copy
  --build-memory MiB    Passed to the disko image builder
  -h, --help            Show this help
EOF
}

build_args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      output_dir="${2:-}"
      shift 2
      ;;
    --qcow2)
      qcow2=1
      shift
      ;;
    --build-memory)
      build_args+=("--build-memory" "${2:-}")
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "make-persistent-image: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$output_dir"

echo "building the persistent image"
"$OJUNY_DISKO_IMAGE_SCRIPT" "${build_args[@]}"

raw=""
for candidate in ./*.raw; do
  [ -f "$candidate" ] || continue
  if [ -z "$raw" ] || [ "$candidate" -nt "$raw" ]; then
    raw="$candidate"
  fi
done

if [ -z "$raw" ]; then
  echo "make-persistent-image: the disko image builder produced no .raw file" >&2
  exit 1
fi

image="$output_dir/ojuny-persistent.img"
mv "$raw" "$image"

if [ "$qcow2" -eq 1 ]; then
  qemu-img convert -f raw -O qcow2 "$image" "$output_dir/ojuny-persistent.qcow2"
fi

echo
echo "image: $image"
echo "size: $(stat -c %s "$image") bytes"
sha256sum "$image"
if [ "$qcow2" -eq 1 ]; then
  sha256sum "$output_dir/ojuny-persistent.qcow2"
fi
