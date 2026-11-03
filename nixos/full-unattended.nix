{
  config,
  lib,
  pkgs,
  inputs,
  modulesPath,
  settings,
  target,
  targetLatest,
  ...
}:

{
  imports = [
    (modulesPath + "/installer/cd-dvd/installation-cd-minimal.nix")
    (modulesPath + "/profiles/qemu-guest.nix")
    ./full-system.nix
    ./offline.nix
    ./live-media-eject.nix
    ./unattended-common.nix
  ];

  isoImage.edition = "unattended-offline";
  isoImage.volumeID = "OJUNY_UNATTENDED";
  image.baseName = lib.mkForce "ojuny-unattended-offline";
  isoImage.makeBiosBootable = true;

  ojuny.gpu = lib.mkForce "none";
  programs.dms-greeter.enable = lib.mkForce false;
  ojuny.plymouth.enable = lib.mkForce false;

  systemd.services.ojuny-unattended-install = {
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
  };

  environment.etc."ojuny/target-toplevels".text = lib.concatMapStrings (path: path + "\n") (
    [
      target.config.system.build.toplevel
      targetLatest.config.system.build.toplevel
      target.pkgs.stdenv
      target.pkgs.microcode-intel
      target.pkgs.microcode-amd
      target.pkgs.base16-schemes
    ]
    ++ config.ojuny.preloadPaths
  );

  isoImage.storeContents = lib.mkAfter [
    target.config.system.build.toplevel
    targetLatest.config.system.build.toplevel
    target.pkgs.stdenv
    target.pkgs.microcode-intel
    target.pkgs.microcode-amd
    target.pkgs.base16-schemes
    pkgs.grub2
    pkgs.grub2_efi
    pkgs.efibootmgr
    pkgs.fish
    pkgs.glibcLocales
  ];
}
