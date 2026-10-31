# Attended install tests

Status: test scripts and the checklist are written, no QEMU attend run has been
completed. Date: 2026-10-31.

This file records results for the three attended Calamares ISOs: main
(`nixos/iso.nix`), discovery (`nixos/discovery-iso.nix`) and offline
(`nixos/full-iso.nix`). Unattended results belong in
`docs/unattended-install.md`; that file is owned by plan 26.

## What the attended flow covers

The Calamares sequence is: welcome, template, locale, keyboard, users, git
origin, partition, summary, install, finished.

- The template page owns bundled versus prepared, template URL, token, branch
  and the host detection explanation.
- The git origin page owns git init, origin URL, token, the credential-helper
  note, the commit author and the no-origin choice.
- The summary page only recaps the account, hostname, bootloader, disk and the
  selected template and repository by name. It does not edit them.
- A prepared clone or git setup failure stops the install with a blocking error.
  The error asks the user to close and reopen the installer from the `Install
  Ojuny` entry, return to the template or origin page, correct the details and
  retry. It is not a warning that lets the install finish.
- `~/.git-credentials` is written only for an HTTPS repository URL with a
  token, with mode `0600`. SSH clones get no helper. See
  `ojuny-docs/canon/09-security.md` for the deferred secrets boundary.

## Status

No attended run has been completed in this pass. QEMU was not run. Every row is
pending.

| Case | ISO | Status | Notes |
| --- | --- | --- | --- |
| Bundled template, no origin | main | Pending | Not run |
| Bundled template, no origin | discovery | Pending | Not run |
| Bundled template, no origin | offline | Pending | Not run |
| Prepared template from a local git repository | main | Pending | Not run |
| Prepared template over HTTPS with a token | main | Pending | Not run |
| Prepared template over SSH | main | Pending | Not run |
| Git origin over HTTPS with a token | main | Pending | Not run |
| Git origin over SSH | main | Pending | Not run |
| No origin | main | Pending | Not run |

## Test scripts

Both scripts are written and are not run in this pass.

- `scripts/test-prepared-install.sh` boots the attended ISO, clones a prepared
  template, and checks the installed disk.
- `scripts/test-git-presetup-install.sh` boots the attended ISO, uses the
  bundled template, and checks the initial commit and the optional origin.

Both scripts accept an existing disk with `--check-only` and otherwise start
QEMU. They use a UEFI VM, an ESP plus ext4 root, and a qcow2 target disk. The
operator completes the Calamares pages and powers off. The script then connects
the disk with `qemu-nbd`, mounts the root partition read-only and runs the
assertions.

Prepared-mode assertions:

- `/home/<user>/repos/nix-flake` exists and is a git repository.
- `git remote get-url origin` matches the template URL.
- The hardware regeneration commit exists on top of the cloned history.
- `~/.git-credentials` exists with mode `0600` only for an HTTPS URL with a
  token. It does not exist for a local or SSH repository.

Git pre-setup assertions:

- `/home/<user>/repos/nix-flake` exists and is a git repository.
- `git log -1 --format=%an <%ae>` is `Ojuny Installer <installer@ojuny.local>`.
- With an origin, `git remote get-url origin` matches the entered URL.
- With no origin, the repository has no remotes.
- `~/.git-credentials` exists with mode `0600` only for an HTTPS origin with a
  token.

## Failure cases to exercise by hand

- Prepared mode with a bad URL stops before `nixos-install` and shows the clone
  error.
- Prepared mode with a bad branch stops at the clone and names the branch.
- A prepared repository without `modules/07-system/00-host.nix` stops with the
  host detection error.
- Prepared mode with a bad HTTPS token stops at the clone.
- A git origin failure after install stops and names the git setup step.
- Non-fatal optional edits still warn and continue; they are not treated as
  install failures.

## Hand-off rows for plan 26

Plan 26 owns `notes/Ojuny Deployment Methods.md` and the offline and remote
statements. These rows are prepared for that table and are not edited into it
here.

| item | done | tested |
| --- | --- | --- |
| main ISO - prepared template | yes (theoretically) | no |
| discovery ISO - prepared template | yes (theoretically) | no |
| offline ISO - prepared template (not truly offline) | yes (theoretically) | no |
| main ISO - git origin (HTTPS token) | yes (theoretically) | no |
| main ISO - git origin (SSH) | yes (theoretically) | no |
| main ISO - no origin | yes | no |
