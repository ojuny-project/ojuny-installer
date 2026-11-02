#!/usr/bin/env python3
"""Print the stable build-time frontier for two NixOS configurations.

The two derivations are expected to be the same system evaluated with different
install-time values (user, hostname, locale, keymap, file systems, ...). Every
derivation that differs between them is treated as generated per install. The
outputs of their inputs that are identical in both configurations must be
present in the ISO, because the generated derivations are built on the target.
"""

import sys


def split_top_level(text):
    parts = []
    depth = 0
    quoted = False
    escaped = False
    current = []
    for char in text:
        if quoted:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
            current.append(char)
        elif char in "([":
            depth += 1
            current.append(char)
        elif char in ")]":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def unquote(value):
    value = value.strip()
    if not value.startswith('"'):
        return value
    out = []
    escaped = False
    for char in value[1:]:
        if escaped:
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            break
        else:
            out.append(char)
    return "".join(out)


def tuple_fields(text):
    return [unquote(part) for part in split_top_level(text)]


def parse_derivation(path):
    with open(path) as handle:
        text = handle.read()
    body = text[text.index("(") + 1 : text.rindex(")")]
    args = split_top_level(body)
    outputs = {}
    for entry in split_top_level(args[0][1:-1]):
        fields = tuple_fields(entry[1:-1])
        if fields:
            outputs[fields[0]] = fields[1]
    inputs = []
    for entry in split_top_level(args[1][1:-1]):
        fields = tuple_fields(entry[1:-1])
        if len(fields) >= 2:
            names = [unquote(name) for name in split_top_level(fields[1][1:-1])]
            inputs.append((fields[0], names))
    srcs = [unquote(entry) for entry in split_top_level(args[2][1:-1])]
    return outputs, inputs, srcs


def closure(root):
    seen = set()
    queue = [root]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        _, inputs, _ = parse_derivation(path)
        queue.extend(dep for dep, _ in inputs)
    return seen


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: offline-preload-paths.py TOP_A TOP_B")
    first = closure(sys.argv[1])
    second = closure(sys.argv[2])
    changed = first ^ second
    frontier = set()
    for drv in changed:
        _, inputs, srcs = parse_derivation(drv)
        frontier.update(srcs)
        for dep, names in inputs:
            if dep in changed:
                continue
            outputs, _, _ = parse_derivation(dep)
            for name in names:
                path = outputs.get(name)
                if path:
                    frontier.add(path)
    for path in sorted(frontier):
        print(path)


if __name__ == "__main__":
    main()
