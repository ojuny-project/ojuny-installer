{
  lib,
  target,
  ...
}:

let
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
    hostname
    removeReferencesTo
  ];
in
{
  options.ojuny.preloadPaths = lib.mkOption {
    type = lib.types.listOf lib.types.path;
    default = [ ];
    description = "Store paths preloaded into the offline ISO for install-time builds.";
  };

  config.ojuny.preloadPaths = lib.unique (lib.concatMap outputsOf packages);
}
