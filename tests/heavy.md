# Heavy checks

These helpers are parseable skeletons for the heavy ISO, reproducibility and
release-boundary checks. They are not exposed in `checks` or `hydraJobs` until
the environment is available.

## ISO size

```nix
{ pkgs, iso }:
pkgs.runCommand "iso-size" { nativeBuildInputs = [ pkgs.coreutils ]; } ''
  size=$(stat -c %s ${iso}/iso/*.iso)
  test "$size" -le 8000000000
  touch $out
''
```

## ISO boot smoke

```nix
{ pkgs, iso }:
pkgs.writeShellApplication {
  name = "iso-boot-smoke";
  runtimeInputs = [ pkgs.qemu pkgs.coreutils ];
  text = ''
    timeout 300 qemu-system-x86_64 -m 4096 -cdrom ${iso}/iso/*.iso -boot order=d -display none -serial null
  '';
}
```

## Reproducibility

Build the same ISO twice on separate stores or machines, then compare
`nix hash path` and the file SHA-256. A mismatch is an Ojuny-layer bug first,
most likely in the Calamares extensions, preloaded inputs, generated files or
timestamps.

## Release boundary

`manifest-schema` is implemented in `ojuny-ci-workflows/schemas`. The manifest
generation, `verify-live` and installer toplevel refusal belong to plan 03.
