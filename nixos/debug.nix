# TEMPORARY: live-ISO SSH and troubleshooting probe.
# Remove this module and its imports from the three ISO files before release.
{ pkgs, ... }:
{
  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "prohibit-password";
  };

  users.users.nixos.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA4aHtgEXDU+Hoy3jBzEx42C1stuRo2Rv2jLX4Vc6M9Z ojuny-test-temporary"
  ];

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA4aHtgEXDU+Hoy3jBzEx42C1stuRo2Rv2jLX4Vc6M9Z ojuny-test-temporary"
  ];

  networking.firewall.allowedTCPPorts = [ 22 ];

  # Put the storage tools on the live user's PATH. Calamares has its own
  # environment; these are for manual inspection and repair over SSH.
  environment.systemPackages = with pkgs; [
    # Filesystems and storage
    btrfs-progs
    cryptsetup
    dosfstools
    efibootmgr
    efivar
    e2fsprogs
    f2fs-tools
    gptfdisk
    nvme-cli
    parted
    smartmontools
    testdisk
    xfsprogs

    # Processes, sessions and logs
    file
    htop
    jq
    lsof
    pciutils
    ripgrep
    strace
    tmux
    usbutils
  ];
}
