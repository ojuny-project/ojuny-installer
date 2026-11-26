{
  config,
  inputs,
  lib,
  pkgs,
  target,
  ...
}:

let
  hostSystem = pkgs.stdenv.hostPlatform.system;
  template = inputs.ojuny-template;
  desktop = template.inputs.ojuny-desktop;
  shell = desktop.inputs.dux-shell;

  generated = ./preload-paths.txt;

  generatedPaths =
    if builtins.pathExists generated then
      builtins.filter (path: path != "") (lib.splitString "\n" (builtins.readFile generated))
    else
      [ ];

  withContext =
    path:
    builtins.appendContext path {
      "${path}" = {
        path = true;
      };
    };

  requestedOutputs = [
    "out"
    "bin"
    "dev"
    "lib"
    "man"
    "info"
    "devdoc"
    "getent"
    "static"
  ];

  outputsOf =
    package:
    map (name: lib.getOutput name package) (
      builtins.filter (name: builtins.hasAttr name package) requestedOutputs
    );

  packages = with target.pkgs; [
    stdenv
    stdenvNoCC
    bash
    coreutils
    glibc
    gcc
    binutils
    systemd
    curl
    jq
    gtk3
    krb5
    cups
    ffmpeg
    shellcheck
    libressl
    texinfo
    libcap
    libcap_ng
    kmod
    cpio
    gzip
    xz
    zstd
    gnutar
    patchelf
    perl
    python3
    makeWrapper
    pkg-config
    meson
    ninja
    cmake
    linux-firmware
    dieHook
    ghc
    hscolour
    haskellPackages.hscolour
    haskellPackages.hostname
    hostname
    removeReferencesTo
  ];

  # Source-built items that a default base install reuses. Versions come from
  # the installer's ojuny-template input and its lock; add new items here only.
  sourceBuilt = [
    template.packages.${hostSystem}.dux
    template.packages.${hostSystem}.mango
    template.packages.${hostSystem}.dms-greeter
    template.packages.${hostSystem}.nix-settings-gui
    template.packages.${hostSystem}.nix-regedit
    template.packages.${hostSystem}.nix-shell-gui
    template.packages.${hostSystem}.nix-cleaner
    template.packages.${hostSystem}.ojuny-welcome
    template.packages.${hostSystem}.ojuny-cli
    template.packages.${hostSystem}.ojuny-patches-cli
    template.packages.${hostSystem}.ojuny-manual
    desktop.packages.${hostSystem}.ojuny-WinMenu
    desktop.inputs.dux-files.packages.${hostSystem}.default
    desktop.inputs.dux-calendar.packages.${hostSystem}.default
    desktop.inputs.dux-gop.packages.${hostSystem}.default
    desktop.inputs.dux-search.packages.${hostSystem}.default
    desktop.inputs.ojuny-login-splash.packages.${hostSystem}.default
    shell.inputs.dux-qt-base.packages.${hostSystem}.default
    target.pkgs.nix-output-monitor
  ];
in
{
  options.ojuny.preloadPaths = lib.mkOption {
    type = lib.types.listOf lib.types.path;
    default = [ ];
    description = "Store paths preloaded into the offline ISO for install-time builds.";
  };

  options.ojuny.prebuildPaths = lib.mkOption {
    type = lib.types.listOf lib.types.path;
    default = [ ];
    description = "Ojuny package store paths preloaded into every ISO so installs copy them instead of building from source.";
  };

  config = {
    ojuny.preloadPaths = lib.unique (
      (if generatedPaths != [ ] then map withContext generatedPaths else [ ])
      ++ lib.concatMap outputsOf packages
      ++ [ target.pkgs.haskellPackages.hostname.src ]
    );

    ojuny.prebuildPaths = lib.unique (lib.concatMap outputsOf sourceBuilt);

    environment.etc."ojuny/prebuild-paths".text = lib.concatStringsSep "\n" (
      map toString config.ojuny.prebuildPaths
    );
  };
}
