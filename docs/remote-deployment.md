# Remote deployment

Two paths are supported:

- `deploy-rs` for a target that already runs NixOS or Ojuny.
- `nixos-anywhere` for a target that does not run NixOS yet.

Both scripts are flake apps. They do not depend on a checkout at a fixed path.

## Remote setup with deploy-rs

```sh
nix run github:ojuny-project/ojuny-template#remote-setup -- \
  --flake github:your-name/your-fork \
  --target root@192.0.2.10
```

The target must run NixOS or Ojuny with SSH enabled. The template exports a
`deploy.nodes.<host>` entry for each `nixosConfigurations.<host>`. The script
uses the first host when `--host` is not given.

Options:

- `--flake URL|PATH`: template or fork. A URL is cloned into a temporary
  directory.
- `--host NAME`: `nixosConfigurations` name.
- `--target USER@HOST`: SSH target.
- `--ssh-user USER`: SSH user override.
- `--remote-build`: build on the target.
- `--dry-run`: print the command.

`deploy-rs` uses magic rollback by default. The installed system keeps
`deploy-rs`, `disko` and `nixos-anywhere` available so it can deploy other
machines later.

## Remote install with nixos-anywhere

Prepare a repository and install in one step:

```sh
nix run github:ojuny-project/ojuny-template#remote-install -- \
  --target root@192.0.2.20 \
  --disk /dev/disk/by-id/... \
  --template github:ojuny-project/ojuny-template \
  --ssh-key ~/.ssh/id_ed25519.pub
```

Pass `--password` or `--ssh-key` so the installed account is not locked.
`--password` is prompted when omitted on a terminal.

The script runs `prepare-remote-repository` in a temporary directory, then
`nixos-anywhere`. The prepared repository gets:

- The discovered `system-hardware` module, or `modules/00-hardware.nix`, with generic storage modules, the disko
  layout, the bootloader and `ojuny.network.deploy-rs.enable = true`.
- The generated user module from `prepare-repo`.

`ojuny.network.deploy-rs.enable` lives in the networking module. It installs
deploy-rs, disko and nixos-anywhere and opens SSH. It is off by default. The
generated hardware page enables it only for machines that are prepared for
remote deployment.

Prepare a repository without installing:

```sh
nix run github:ojuny-project/ojuny-template#prepare-remote-repository -- \
  --root ./ojuny-deploy \
  --hostname ojuny \
  --disk /dev/disk/by-id/... \
  --firmware efi
```

Install from a prepared repository:

```sh
nix run github:ojuny-project/ojuny-template#remote-install -- \
  --flake ./ojuny-deploy \
  --target root@192.0.2.20
```

Options:

- `--build-on local|remote`: default is `remote`.
- `--prepare`: prepare an existing `--flake` in place.
- `--dry-run`: print the command.

`nixos-anywhere` uses kexec for a machine that is not running NixOS. The target
must be reachable over SSH and must have enough memory for the kexec image.

## Verification

No QEMU runs are part of this repository. Verify both paths on real hardware:

1. Confirm SSH access to the target.
2. Run `--dry-run` first and inspect the command.
3. Run the deployment and check the new generation with
   `nixos-rebuild list-generations` on the target.
4. Check that `ojuny.network.deploy-rs.enable` leaves SSH running and the
   Ojuny desktop units active.
