{
  config,
  lib,
  pkgs,
  inputs,
  modulesPath,
  settings,
  ...
}:

{
  imports = [
    (modulesPath + "/installer/cd-dvd/installation-cd-minimal.nix")
    (modulesPath + "/profiles/qemu-guest.nix")
    ./live-media-eject.nix
    ./unattended-common.nix
  ];

  isoImage.edition = "unattended";
  image.baseName = lib.mkForce "ojuny-unattended";
  isoImage.makeBiosBootable = true;

  systemd.services.ojuny-unattended-install = {
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
  };
}
