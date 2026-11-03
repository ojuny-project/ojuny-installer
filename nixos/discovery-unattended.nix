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
    inputs.nix-cache-discovery.nixosModules.default
  ];

  services.nix-cache-discovery = {
    enable = true;
    exclusive = true;
    port = 5055;
    discovery.auto = true;
    discovery.interval = 60;
    discovery.timeout = 2000;
    proxy.wait = 240;
  };

  nix.settings = {
    connect-timeout = 30;
    download-attempts = 10;
    stalled-download-timeout = 600;
  };

  environment.etc."ojuny/discovery".text = "";

  documentation.enable = lib.mkForce false;
  documentation.man.enable = lib.mkForce false;
  documentation.doc.enable = lib.mkForce false;
  documentation.nixos.enable = lib.mkForce false;

  isoImage.edition = "unattended-discovery";
  isoImage.volumeID = "OJUNY_UNATTENDED_DISCOVERY";
  image.baseName = lib.mkForce "ojuny-unattended-discovery";
  isoImage.makeBiosBootable = true;

  systemd.services.ojuny-unattended-install = {
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
  };
}
