{
  config,
  lib,
  target,
  ...
}:

let
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

  isPackage = value: builtins.isAttrs value && (value.type or "") == "derivation";

  ojunyNamePrefixes = [
    "dank"
    "dux"
    "ojuny"
    "mango"
    "dms"
    "quickshell"
    "nix-settings-gui"
    "nix-shell-gui"
    "simple-nix-update-gui"
    "nix-regedit"
    "nix-cleaner"
    "nix-cache-discovery"
    "nom-cache-discovery"
    "nix-output-monitor"
    "raven"
  ];

  homeUsers = (target.config.home-manager or { }).users or { };

  ojunyPackages =
    builtins.filter
      (
        package:
        isPackage package && lib.any (prefix: lib.hasPrefix prefix (package.name or "")) ojunyNamePrefixes
      )
      (
        target.config.environment.systemPackages
        ++ lib.concatMap (user: user.home.packages) (lib.attrValues homeUsers)
      );
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

    ojuny.prebuildPaths = lib.unique (lib.concatMap outputsOf ojunyPackages);

    environment.etc."ojuny/prebuild-paths".text = lib.concatStringsSep "\n" (
      map toString config.ojuny.prebuildPaths
    );
  };
}
