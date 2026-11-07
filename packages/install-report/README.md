# install-report

Turn an Ojuny install report into a result.

## Usage

```console
$ nix run .#install-report -- /path/to/report --output-dir /path/to/result
```

Input directory:

- `ojuny-install.log`
- `install-report.json`
- `first-boot.log`

Output:

- `result.json`
- `result.md`
- `result.html`

## Log format

The installer writes:

```text
2026-11-07T12:00:00 +0.000s PHASE partitioning and mounting
```

The parser uses the absolute timestamp and the elapsed seconds.

The first-boot log uses simple key-value lines:

```text
kernel_start=2026-11-07T12:51:00Z
display_manager=2026-11-07T12:51:20Z
session_ready=2026-11-07T12:51:30Z
login_ready=2026-11-07T12:51:40Z
```

## Identity

The result records a configuration fingerprint over the ISO, template and
environment fields. It does not require a pinned commit.

## Tests

```console
$ PYTHONPATH=src python3 -m unittest discover -s tests -v
```
