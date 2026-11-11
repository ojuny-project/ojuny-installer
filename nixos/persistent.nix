{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  disko = inputs.disko.packages.${pkgs.stdenv.hostPlatform.system}.disko;
in
{
  imports = [
    ./full-system.nix
    inputs.disko.nixosModules.disko
    inputs.impermanence.nixosModules.impermanence
  ];

  boot.initrd.availableKernelModules = [
    "ahci"
    "dm_mod"
    "hid_generic"
    "nvme"
    "sd_mod"
    "sr_mod"
    "usb_storage"
    "usbhid"
    "xhci_pci"
  ];

  system.nixos.distroName = "Ojuny";

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  ojuny.gpu = lib.mkForce "none";
  ojuny.plymouth.enable = lib.mkForce false;
  ojuny.patches = lib.mkForce true;

  networking.hostName = lib.mkForce "ojuny";
  system.stateVersion = lib.mkForce "26.11";

  services.displayManager.autoLogin = {
    enable = true;
    user = "user";
  };

  disko.devices.disk.main = {
    device = "/dev/vda";
    type = "disk";
    imageSize = "32G";
    imageName = "ojuny-persistent";
    content = {
      type = "gpt";
      partitions = {
        boot = {
          size = "1M";
          type = "EF02";
          priority = 1;
        };
        ESP = {
          size = "4G";
          type = "EF00";
          priority = 2;
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [
              "-n"
              "ojuny-boot"
            ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          size = "100%";
          priority = 4;
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [
              "-L"
              "ojuny-persist"
            ];
            mountpoint = "/";
          };
        };
      };
    };
  };

  fileSystems."/" = lib.mkForce {
    device = "tmpfs";
    fsType = "tmpfs";
    options = [
      "mode=755"
      "size=4G"
    ];
  };

  fileSystems."/persist" = lib.mkForce {
    device = "/dev/disk/by-label/ojuny-persist";
    fsType = "ext4";
    neededForBoot = true;
  };

  fileSystems."/nix/.rw-store" = lib.mkForce {
    device = "tmpfs";
    fsType = "tmpfs";
    neededForBoot = true;
    options = [ "mode=0755" ];
  };

  fileSystems."/nix/store" = lib.mkForce {
    overlay = {
      lowerdir = [ "/persist/nix/store" ];
      upperdir = "/nix/.rw-store/store";
      workdir = "/nix/.rw-store/work";
    };
    neededForBoot = true;
    depends = [
      "/persist"
      "/nix/.rw-store"
    ];
  };

  environment.persistence."/persist" = {
    hideMounts = true;
    directories = [
      "/home"
      "/var/lib/nixos"
    ];
  };

  boot.loader.systemd-boot.enable = lib.mkForce false;
  boot.loader.grub.enable = lib.mkForce true;
  boot.loader.grub.efiSupport = lib.mkForce true;
  boot.loader.grub.efiInstallAsRemovable = lib.mkForce true;
  boot.loader.grub.devices = lib.mkForce [ "/dev/vda" ];
  boot.loader.efi.canTouchEfiVariables = lib.mkForce false;

  environment.systemPackages = [
    disko
    pkgs.git
  ];
}
