#!/usr/bin/env python3
"""Discover Ojuny files by the flake module they declare.

The contract is documented in ``docs/12-flake-module-contract.md``.  A file is
identified by its module name, not by a numbered directory or a user
directory. When no module exists, callers use a path under
``$REPO_ROOT/modules``.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "result", "target", "node_modules", "__pycache__"}
SKIP_PREFIXES = ("result", ".")
NIX_SUFFIX = ".nix"

MODULES = {
    "configuration": "system-configuration",
    "users": "users",
    "imports": "host-imports",
    "hardware": "system-hardware",
    "bootloader": "system-bootloader",
    "quirks": "system-hardware-quirks",
    "facter_page": "system-facter",
}

FALLBACKS = {
    "configuration": "modules/00-configuration.nix",
    "users": "modules/00-user.nix",
    "imports": "modules/00-imports.nix",
    "hardware": "modules/00-hardware.nix",
    "quirks": "modules/backend/00-hardware-quirks.nix",
    "facter": "modules/facter.json",
}


def nix_files(root):
    root = Path(root)
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            name
            for name in dirs
            if name not in SKIP_DIRS
            and not name.startswith(SKIP_PREFIXES)
        ]
        for name in files:
            if name.endswith(NIX_SUFFIX):
                yield Path(current) / name


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _module_re(name, kind="nixos"):
    return re.compile(
        r"(?<![\w.])(?:flake\s*\.\s*)?modules\s*\.\s*"
        + re.escape(kind)
        + r"\s*\.\s*\"?"
        + re.escape(name)
        + r"\"?\s*="
    )


def _host_re(host=None):
    name = r"\"?([A-Za-z0-9._-]+)\"?" if host is None else r"\"?" + re.escape(host) + r"\"?"
    return re.compile(
        r"(?<![\w.])(?:flake\s*\.\s*)?nixosConfigurations\s*\.\s*" + name + r"\s*="
    )


def find_modules(root, name, kind="nixos"):
    pattern = _module_re(name, kind)
    found = []
    for path in nix_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        if "flake" not in text:
            continue
        if pattern.search(text):
            found.append(path)
    return sorted(found)


def find_hosts(root):
    found = {}
    pattern = _host_re()
    for path in nix_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        if "flake" not in text:
            continue
        for match in pattern.finditer(text):
            found.setdefault(match.group(1), []).append(path)
    return {host: sorted(paths) for host, paths in sorted(found.items())}


def find_host(root, host):
    return find_hosts(root).get(host, [])


def preferred_host(root):
    hosts = find_hosts(root)
    names = [name for name in hosts if name != "fixture"]
    return names[0] if names else next(iter(hosts), "")


def find_facter(root):
    root = Path(root)
    found = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            name
            for name in dirs
            if name not in SKIP_DIRS
            and not name.startswith(SKIP_PREFIXES)
        ]
        if "facter.json" in files:
            found.append(Path(current) / "facter.json")
    return sorted(
        found,
        key=lambda path: (
            0 if path == root / "modules" / "facter.json" else 1,
            len(path.parts),
            str(path),
        ),
    )


def find_file(root, name):
    root = Path(root)
    found = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            value
            for value in dirs
            if value not in SKIP_DIRS
            and not value.startswith(SKIP_PREFIXES)
        ]
        if name in files:
            found.append(Path(current) / name)
    return sorted(found)


def fallback(root, key):
    return Path(root) / FALLBACKS[key]


def select(candidates, label, interactive=True, choice=None):
    if choice:
        choice_path = Path(choice)
        for candidate in candidates:
            if Path(candidate) == choice_path or str(candidate) == str(choice):
                return Path(candidate)
        raise SystemExit(
            "{}: --select {} is not one of: {}".format(
                label, choice, ", ".join(str(value) for value in candidates)
            )
        )
    if not candidates:
        return None
    if len(candidates) == 1:
        return Path(candidates[0])
    if interactive and sys.stdin.isatty():
        print("Multiple files declare {}:".format(label), file=sys.stderr)
        for index, candidate in enumerate(candidates, 1):
            print("  {}. {}".format(index, candidate), file=sys.stderr)
        while True:
            answer = input("Choose 1-{}: ".format(len(candidates))).strip()
            if answer.isdigit() and 1 <= int(answer) <= len(candidates):
                return Path(candidates[int(answer) - 1])
    return Path(sorted(candidates)[0])


def _insert_import(text, module_name):
    reference = "self.modules.nixos.{}".format(module_name)
    if reference in text:
        return text
    pattern = re.compile(r"(?m)^(\s*)imports\s*=\s*\[")
    match = pattern.search(text)
    if not match:
        return text
    indent = match.group(1) + "  "
    insert = "\n{}{}".format(indent, reference)
    end = match.end()
    return text[:end] + insert + text[end:]


def ensure_imports(
    root,
    names,
    interactive=True,
    choice=None,
    fallback_rel=None,
):
    candidates = find_modules(root, MODULES["imports"])
    fallback_rel = fallback_rel or FALLBACKS["imports"]
    path = select(candidates, "the host imports module", interactive, choice)
    if path is None:
        path = Path(root) / fallback_rel
        if not path.exists():
            body = (
                "{ self, ... }:\n\n"
                "{\n"
                "  flake.modules.nixos.host-imports = {\n"
                "    imports = [ ];"
                "\n  };\n"
                "}\n"
            )
            write_text(path, body)
    text = read_text(path)
    for name in names:
        text = _insert_import(text, name)
    write_text(path, text)
    return path


def _replace_once(text, pattern, replacement, label, required=False):
    result, count = re.subn(pattern, replacement, text, count=1)
    if count != 1 and required:
        raise RuntimeError("could not set {}".format(label))
    return result


def _assign(text, option, value, required=False):
    pattern = re.escape(option) + r'\s*=\s*"[^"]*";'
    replacement = "{} = {};".format(option, json.dumps(value))
    result, count = re.subn(pattern, replacement, text, count=1)
    if count == 1:
        return result
    if not required:
        return text
    line = "{} = {};".format(option, json.dumps(value))
    match = re.search(r"(?m)^(\s*)config\s*=\s*\{|(?<![\w.])config\s*=\s*\{", text)
    if match:
        indent = (match.group(1) or "") + "  "
        return text[: match.end()] + "\n{}{}".format(indent, line) + text[match.end() :]
    match = re.search(r"(?m)^(\s*)\}\s*;?\s*$", text)
    if match:
        indent = match.group(1) + "  "
        return text[: match.start()] + "{}{}\n".format(indent, line) + text[match.start() :]
    return text


def ensure_configuration(root, values, interactive=True, choice=None, fallback_rel=None):
    candidates = find_modules(root, MODULES["configuration"])
    fallback_rel = fallback_rel or FALLBACKS["configuration"]
    path = select(candidates, "the system configuration module", interactive, choice)
    if path is None:
        path = Path(root) / fallback_rel
        repo_path = values.get("repo_path")
        repo_line = (
            "        ojuny.repoPath = {};\n".format(json.dumps(repo_path))
            if repo_path
            else ""
        )
        body = (
            "{{ self, ... }}:\n\n"
            "{{\n"
            "  flake.modules.nixos.system-configuration =\n"
            "    {{ ... }}:\n"
            "    {{\n"
            "      config = {{\n"
            "        networking.hostName = {hostname};\n"
            "        system.stateVersion = {state_version};\n"
            "{repo_line}"
            "      }};\n"
            "    }};\n"
            "}}\n"
        ).format(
            hostname=json.dumps(values["hostname"]),
            state_version=json.dumps(values["state_version"]),
            repo_line=repo_line,
        )
        write_text(path, body)
    text = read_text(path)
    text = _assign(text, "networking.hostName", values["hostname"], required=True)
    text = _assign(text, "system.stateVersion", values["state_version"], required=True)
    for key, option in (
        ("timezone", "time.timeZone"),
        ("locale", "i18n.defaultLocale"),
        ("keymap", "console.keyMap"),
    ):
        if values.get(key):
            text = _assign(text, option, values[key])
    if values.get("repo_path"):
        text = _assign(text, "ojuny.repoPath", values["repo_path"], required=True)
    write_text(path, text)
    return path


def ensure_users(root, content, interactive=True, choice=None, fallback_rel=None):
    candidates = find_modules(root, MODULES["users"])
    fallback_rel = fallback_rel or FALLBACKS["users"]
    path = select(candidates, "the users module", interactive, choice)
    if path is None:
        path = Path(root) / fallback_rel
    write_text(path, content)
    return path


def ensure_hardware(root, content, interactive=True, choice=None, fallback_rel=None):
    candidates = find_modules(root, MODULES["hardware"])
    label = "the system hardware module"
    if not candidates:
        candidates = find_modules(root, MODULES["bootloader"])
        label = "the system bootloader module"
    fallback_rel = fallback_rel or FALLBACKS["hardware"]
    path = select(candidates, label, interactive, choice)
    if path is None:
        path = Path(root) / fallback_rel
    write_text(path, content)
    return path


def ensure_quirks(root, content, interactive=True, choice=None, fallback_rel=None):
    candidates = find_modules(root, MODULES["quirks"])
    fallback_rel = fallback_rel or FALLBACKS["quirks"]
    path = select(candidates, "the hardware quirks module", interactive, choice)
    if path is None:
        if not content:
            return None
        path = Path(root) / fallback_rel
    if not content:
        return path if path.exists() else None
    write_text(path, content)
    return path


def ensure_facter(root, content, interactive=True, choice=None, fallback_rel=None):
    candidates = find_facter(root)
    fallback_rel = fallback_rel or FALLBACKS["facter"]
    path = select(candidates, "the facter report", interactive, choice)
    if path is None:
        path = Path(root) / fallback_rel
    write_text(path, content)
    return path


def find_multiboot(root):
    found = []
    for path in nix_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        if re.search(r"ojuny\.multiboot\.enable\s*=", text):
            found.append(path)
    return sorted(found)


def ensure_multiboot(root, interactive=True, choice=None):
    path = select(find_multiboot(root), "the multiboot module", interactive, choice)
    if path is None:
        return False
    text = read_text(path)
    if re.search(r"ojuny\.multiboot\.enable\s*=\s*true;", text):
        return True
    updated, count = re.subn(
        r"ojuny\.multiboot\.enable\s*=\s*false;",
        "ojuny.multiboot.enable = true;",
        text,
        count=1,
    )
    if count != 1:
        return False
    write_text(path, updated)
    return True


def _host_block(hostname, clone_path):
    return """  flake.nixosConfigurations.{hostname} = inputs.nixpkgs.lib.nixosSystem {{
    system = "x86_64-linux";
    modules = [
      self.modules.nixos.host-imports
      ({{ lib, ... }}: {{
        services.simple-nix-update-gui.flakeUri = lib.mkDefault {flake_uri};
        services.simple-nix-update-gui.clonePath = lib.mkDefault {clone_path};
      }})
    ];
  }};""".format(
        hostname=hostname,
        flake_uri=json.dumps("path:" + clone_path),
        clone_path=json.dumps(clone_path),
    )


def ensure_host(root, hostname, clone_path, interactive=True, choice=None, fallback_rel=None):
    fallback_rel = fallback_rel or "modules/00-host.nix"
    existing = select(
        find_host(root, hostname), "the {} host module".format(hostname), interactive, choice
    )
    if existing is not None:
        text = read_text(existing)
        text = _replace_once(
            text,
            r'services\.simple-nix-update-gui\.flakeUri\s*=\s*lib\.mkDefault\s*"[^"]*";',
            'services.simple-nix-update-gui.flakeUri = lib.mkDefault {};'.format(
                json.dumps("path:" + clone_path)
            ),
            "update GUI flake URI",
        )
        text = _replace_once(
            text,
            r'services\.simple-nix-update-gui\.clonePath\s*=\s*lib\.mkDefault\s*"[^"]*";',
            'services.simple-nix-update-gui.clonePath = lib.mkDefault {};'.format(
                json.dumps(clone_path)
            ),
            "update GUI clone path",
        )
        if "self.modules.nixos.host-imports" not in text:
            match = re.search(r"(?m)^(\s*)modules\s*=\s*\[", text)
            if match:
                indent = match.group(1) + "  "
                text = (
                    text[: match.end()]
                    + "\n{}self.modules.nixos.host-imports".format(indent)
                    + text[match.end() :]
                )
        write_text(existing, text)
        return existing

    block = _host_block(hostname, clone_path)
    path = Path(root) / fallback_rel
    if not path.exists():
        write_text(path, "{{ self, inputs, ... }}: {{\n\n{}\n\n}}\n".format(block))
        return path

    text = read_text(path)
    if "flake.nixosConfigurations.{} =".format(hostname) in text:
        return path
    marker = text.rstrip().rfind("}")
    if marker == -1:
        write_text(path, "{{ self, inputs, ... }}: {{\n\n{}\n\n}}\n".format(block))
        return path
    write_text(path, text[:marker] + "\n" + block + "\n" + text[marker:])
    return path


def _arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="flake repository root")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--select", default=None, help="explicit file choice")
    sub = parser.add_subparsers(dest="command", required=True)

    path = sub.add_parser("path")
    path.add_argument(
        "--module", required=True, choices=sorted(list(MODULES) + ["host", "facter"])
    )
    path.add_argument("--host", default=None)
    path.add_argument("--fallback", default=None)

    sub.add_parser("facter")
    sub.add_parser("imports")
    sub.add_parser("multiboot")
    sub.add_parser("hosts")
    sub.add_parser("current-host")

    ensure_imports_parser = sub.add_parser("ensure-imports")
    ensure_imports_parser.add_argument("--name", action="append", required=True)
    ensure_imports_parser.add_argument("--fallback", default=None)

    configuration = sub.add_parser("ensure-configuration")
    configuration.add_argument("--hostname", required=True)
    configuration.add_argument("--state-version", required=True)
    configuration.add_argument("--timezone", default=None)
    configuration.add_argument("--locale", default=None)
    configuration.add_argument("--keymap", default=None)
    configuration.add_argument("--repo-path", default=None)
    configuration.add_argument("--fallback", default=None)

    host = sub.add_parser("host")
    host.add_argument("--hostname", required=True)
    host.add_argument("--clone-path", default="repos/nix-flake")

    return parser


def main():
    args = _arg_parser().parse_args()
    root = Path(args.root)
    interactive = not args.non_interactive

    if args.command == "path":
        if args.module == "facter":
            candidates = find_facter(root)
            fallback_rel = args.fallback or FALLBACKS["facter"]
        elif args.module == "host":
            hosts = find_hosts(root)
            candidates = (
                hosts.get(args.host, [])
                if args.host
                else sorted({path for paths in hosts.values() for path in paths})
            )
            fallback_rel = args.fallback or "modules/00-host.nix"
        else:
            candidates = find_modules(root, MODULES[args.module])
            fallback_rel = args.fallback or FALLBACKS.get(args.module)
        selected = select(candidates, args.module, interactive, args.select)
        if selected is None and fallback_rel:
            selected = root / fallback_rel
        if selected is None:
            return 1
        print(selected)
        return 0

    if args.command == "facter":
        selected = select(find_facter(root), "the facter report", interactive, args.select)
        print(selected or root / FALLBACKS["facter"])
        return 0

    if args.command == "imports":
        selected = select(
            find_modules(root, MODULES["imports"]), "the host imports module", interactive, args.select
        )
        print(selected or root / FALLBACKS["imports"])
        return 0

    if args.command == "multiboot":
        selected = select(find_multiboot(root), "the multiboot module", interactive, args.select)
        if selected is None:
            return 1
        print(selected)
        return 0

    if args.command == "hosts":
        print(
            json.dumps(
                {
                    host: [str(path) for path in paths]
                    for host, paths in find_hosts(root).items()
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "current-host":
        print(preferred_host(root))
        return 0

    if args.command == "ensure-imports":
        selected = ensure_imports(
            root,
            args.name,
            interactive,
            args.select,
            args.fallback,
        )
        print(selected)
        return 0

    if args.command == "ensure-configuration":
        selected = ensure_configuration(
            root,
            {
                "hostname": args.hostname,
                "state_version": args.state_version,
                "timezone": args.timezone,
                "locale": args.locale,
                "keymap": args.keymap,
                "repo_path": args.repo_path,
            },
            interactive,
            args.select,
            args.fallback,
        )
        ensure_imports(root, ["system-configuration"], interactive)
        print(selected)
        return 0

    if args.command == "host":
        selected = ensure_host(
            root,
            args.hostname,
            args.clone_path,
            interactive,
            args.select,
        )
        print(selected)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
