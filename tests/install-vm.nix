{
  pkgs,
  iso,
  memory ? 4096,
  cpus ? 2,
}:

pkgs.writeShellApplication {
  name = "acceptance-install";
  runtimeInputs = [
    pkgs.qemu
    pkgs.coreutils
  ];
  text = ''
    work=$(mktemp -d)
    qemu-img create -f qcow2 "$work/disk.qcow2" 20G
    timeout 3600 qemu-system-x86_64 \
      -m ${toString memory} \
      -smp ${toString cpus} \
      -drive "file=$work/disk.qcow2,if=virtio,format=qcow2" \
      -cdrom ${iso} \
      -boot order=d \
      -nic none \
      -no-reboot \
      -display none \
      -serial null
    test -s "$work/disk.qcow2"
  '';
}
