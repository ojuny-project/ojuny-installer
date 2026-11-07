# Acceptance and VM test skeletons

These files are parseable skeletons. They are not exposed in `checks` or
`hydraJobs` until the heavy test environment is available.

- `acceptance.nix` defines the graphical session test and a five-run stability
  set. It imports `template.modules.nixos.host-imports` and uses
  `virtio-vga-gl` and OCR.
- `install-vm.nix` defines the unattended install run. It takes an ISO path and
  creates a qcow2 disk.

## Wiring

Add to the installer flake when KVM and ISO artifacts are available:

```nix
tests.acceptance = import ./tests/acceptance.nix {
  inherit pkgs;
  template = inputs.ojuny-template;
};

tests.install-vm = import ./tests/install-vm.nix {
  inherit pkgs;
  iso = fullUnattended.config.system.build.isoImage;
};
```

The full flow list and pass criteria are in
`ojuny-ci-workflows/docs/acceptance-playbook.md`.
