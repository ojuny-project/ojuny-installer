{
  lib,
  pkgs,
  inputs,
  modulesPath,
  ...
}:

let
  extensions = pkgs.callPackage ../packages/ojuny-calamares-extensions {
    templatePath = inputs.ojuny-template.outPath;
    prepareRepo = (inputs.ojuny-template.packages.${pkgs.system} or { }).prepare-repo or null;
    regenerateHardware =
      (inputs.ojuny-template.packages.${pkgs.system} or { }).regenerate-hardware or null;
    mkpasswd = pkgs.mkpasswd;
  };

  calamaresPkg = pkgs.calamares.overrideAttrs (previous: {
    patches =
      lib.filter (patch: !(lib.hasInfix "dont-allow-manual-luks" (toString patch))) (
        previous.patches or [ ]
      )
      ++ [ ../packages/calamares-compact-locale.patch ];
  });

  calamares = pkgs.callPackage ../packages/calamares-ojuny.nix {
    calamares = calamaresPkg;
    inherit extensions;
  };
in
{
  imports = [
    (modulesPath + "/installer/cd-dvd/installation-cd-graphical-base.nix")
    ./live-media-eject.nix

    inputs.ojuny-template.modules.nixos.system-graphics
    inputs.ojuny-template.modules.nixos.desktop-mango
    inputs.ojuny-template.modules.nixos.desktop-mangosettings
    inputs.ojuny-template.modules.nixos.desktop-mangomaster
    inputs.ojuny-template.modules.nixos.desktop-mangodwindle
    inputs.ojuny-template.modules.nixos.desktop-mangoworkspaces
    inputs.ojuny-template.modules.nixos.desktop-scroller
    inputs.ojuny-template.modules.nixos.desktop-display
    inputs.ojuny-template.modules.nixos.desktop-style-theme
    inputs.ojuny-template.modules.nixos.desktop-style-typography
    inputs.ojuny-template.modules.nixos.desktop-style-compositor
    inputs.ojuny-template.modules.nixos.desktop-style-shell
    inputs.ojuny-template.modules.nixos.desktop-bar
    inputs.ojuny-template.modules.nixos.desktop-dock
    inputs.ojuny-template.modules.nixos.desktop-dashboard
    inputs.ojuny-template.modules.nixos.desktop-notifications
    inputs.ojuny-template.modules.nixos.desktop-clipboard
    inputs.ojuny-template.modules.nixos.desktop-menu
    inputs.ojuny-template.modules.nixos.desktop-plugins
    inputs.ojuny-template.modules.nixos.desktop-binds
    inputs.ojuny-template.modules.nixos.desktop-autostart
    inputs.ojuny-template.modules.nixos.desktop-input
    inputs.ojuny-template.modules.nixos.desktop-login
    inputs.ojuny-template.modules.nixos.desktop-controlcenter
    inputs.ojuny-template.modules.nixos.desktop-gestures
    inputs.ojuny-template.modules.nixos.desktop-launcher
  ];

  nixpkgs.overlays = [
    (final: prev: {
      khal = prev.khal.overrideAttrs (old: {
        postInstall = (old.postInstall or "") + ''
          mkdir -p $man
        '';
      });

      tesseract = prev.tesseract.override {
        enableLanguages = [ "eng" ];
      };
    })
  ];

  system.nixos.distroName = "Ojuny";
  system.nixos.distroId = "ojuny";

  ojuny.gpu = lib.mkForce "none";

  isoImage.edition = lib.mkForce "installer";
  isoImage.volumeID = lib.mkForce "OJUNY_INSTALLER";
  image.baseName = lib.mkForce "ojuny-installer";

  desktop.ojuny.mango.execOnce = lib.mkForce [
    "dms run"
    "wl-clip-persist --clipboard both"
    "wl-paste --type text --watch cliphist store"
    "wl-paste --type image --watch cliphist store"
    "ydotoold"
    "${pkgs.dbus}/bin/dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE NIXOS_OZONE_WL XCURSOR_THEME XCURSOR_SIZE"
    "systemctl --user reset-failed"
    "systemctl --user start mango-session.target"
  ];

  desktop.ojuny.mango.rules.window_rule = [
    {
      app_id = "calamares";
      is_floating = 1;
      width = 0.8;
      height = 0.8;
    }
    {
      title = "Calamares";
      is_floating = 1;
      width = 0.8;
      height = 0.8;
    }
  ];

  desktop.ojuny.mango.binds.common = {
    focusDown = {
      modifier = [
        "CTRL"
        "ALT"
      ];
      keys = [ "delete" ];
      dispatcher = "spawn_shell";
      args = "ghostty";
      description = "ctrl+alt+delete ghostty bind";
      group = "debug";
    };
  };

  services.displayManager.defaultSession = "ojuny";
  services.displayManager.autoLogin = {
    enable = true;
    user = "nixos";
  };

  services.speechd.enable = lib.mkForce false;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  security.polkit.enablePkexecWrapper = true;
  programs.partition-manager.enable = true;
  i18n.supportedLocales = [ "all" ];

  environment.systemPackages = [
    calamares
    (pkgs.makeDesktopItem {
      name = "ojuny-install";
      desktopName = "Install Ojuny";
      exec = "${calamares}/bin/ojuny-install";
      icon = "system-software-install";
      categories = [ "System" ];
      terminal = false;
    })
    inputs.ojuny-template.packages.${pkgs.system}.nix-settings-gui
    inputs.ojuny-template.packages.${pkgs.system}.nix-regedit
    inputs.ojuny-template.packages.${pkgs.system}.nix-shell-gui
    inputs.ojuny-template.packages.${pkgs.system}.simple-nix-update-gui
    inputs.ojuny-template.packages.${pkgs.system}.simple-nix-update-gui-daemon
    inputs.ojuny-template.packages.${pkgs.system}.ojuny-cli
    inputs.ojuny-template.packages.${pkgs.system}.ojuny-patches-cli
    inputs.ojuny-template.packages.${pkgs.system}.mango
    inputs.ojuny-template.packages.${pkgs.system}.dux
    inputs.ojuny-template.packages.${pkgs.system}.dms-greeter
    pkgs.cryptsetup
    pkgs.glibcLocales
    pkgs.mkpasswd
    pkgs.nixos-facter
    pkgs.zsh
  ];

  services.upower.enable = true;

  systemd.user.services.ojuny-install = {
    description = "Ojuny Calamares installer";
    wantedBy = [ "mango-session.target" ];
    after = [ "graphical-session.target" ];
    environment.QT_QPA_PLATFORM = "wayland;xcb";
    serviceConfig = {
      ExecStart = "${calamares}/bin/ojuny-install";
      Restart = "on-failure";
      RestartSec = 2;
    };
  };
}
