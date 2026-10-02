#!/usr/bin/env python3
"""Scan publishable files and reachable Git blobs without printing secret values."""

import json
import subprocess
import tempfile
from pathlib import Path

from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments])


def scan(filename: str, label: str) -> list[dict[str, str | int]]:
    secrets = SecretsCollection()
    secrets.scan_file(filename)
    return [
        {"file": label, "type": secret.type, "line": secret.line_number} for _, secret in secrets
    ]


def main() -> int:
    files = set(git("ls-files", "-co", "--exclude-standard", "-z").decode().split("\0")) - {""}
    revisions = git("rev-list", "--all").decode().splitlines()
    blobs: dict[str, str] = {}
    findings = []
    with default_settings():
        for filename in sorted(files):
            if Path(filename).is_file():
                findings.extend(scan(filename, filename))
        for revision in revisions:
            for entry in git("ls-tree", "-rz", revision).decode().split("\0"):
                if not entry:
                    continue
                metadata, filename = entry.split("\t", 1)
                _, kind, identifier = metadata.split()
                if kind == "blob":
                    blobs[identifier] = filename
        for identifier, filename in blobs.items():
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as temporary:
                temporary.write(git("cat-file", "blob", identifier))
                temporary.flush()
                findings.extend(scan(temporary.name, f"history:{filename}:{identifier[:12]}"))
    print(json.dumps({"files": len(files), "history_blobs": len(blobs), "findings": findings}))
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
