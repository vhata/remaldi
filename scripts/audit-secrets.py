#!/usr/bin/env python3
"""Scan publishable files and reachable Git blobs without printing secret values.

Blobs are immutable, so a blob that scanned clean is recorded in a cache in
the Git directory and skipped on later runs. The cache is keyed by the
detect-secrets version and settings, and by file name as well as blob, since
detect-secrets filters by name. Blobs with findings are never cached.
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from detect_secrets.__version__ import VERSION
from detect_secrets.core.secrets_collection import SecretsCollection
from detect_secrets.settings import default_settings, get_settings

Finding = dict[str, str | int]


def git(*arguments: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", *arguments], input=stdin, capture_output=True, check=True).stdout


def scan(filename: str, label: str) -> list[Finding]:
    secrets = SecretsCollection()
    secrets.scan_file(filename)
    return [
        {"file": label, "type": secret.type, "line": secret.line_number} for _, secret in secrets
    ]


def cache_path() -> Path:
    settings = json.dumps(get_settings().json(), sort_keys=True)
    key = hashlib.sha256(f"{VERSION}\n{settings}".encode()).hexdigest()
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    return common / "remaldi-secret-audit" / f"{key[:16]}.txt"


def working_files() -> dict[str, str]:
    """Map each tracked or unignored file in the working tree to its blob ID."""
    listed = git("ls-files", "-co", "--exclude-standard", "-z").decode().split("\0")
    files = sorted({name for name in listed if name and Path(name).is_file()})
    if not files:
        return {}
    identifiers = git("hash-object", "--stdin-paths", stdin="\n".join(files).encode()).decode()
    return dict(zip(files, identifiers.split(), strict=True))


def history_blobs() -> dict[str, str]:
    """Map each blob reachable from any ref to a path it appears under."""
    objects = git("rev-list", "--all", "--objects")
    described = git(
        "cat-file", "--batch-check=%(objecttype) %(objectname) %(rest)", stdin=objects
    ).decode()
    blobs: dict[str, str] = {}
    for line in described.splitlines():
        kind, _, rest = line.partition(" ")
        identifier, _, path = rest.partition(" ")
        if kind == "blob" and path:
            blobs.setdefault(identifier, path)
    return blobs


def entry(identifier: str, path: str) -> str:
    return f"{identifier} {Path(path).name}"


def blob_contents(identifiers: list[str]) -> dict[str, bytes]:
    output = git("cat-file", "--batch", stdin="".join(f"{i}\n" for i in identifiers).encode())
    contents: dict[str, bytes] = {}
    offset = 0
    for identifier in identifiers:
        header_end = output.index(b"\n", offset)
        size = int(output[offset:header_end].split()[2])
        start = header_end + 1
        contents[identifier] = output[start : start + size]
        offset = start + size + 1
    return contents


def main() -> int:
    findings: list[Finding] = []
    with default_settings():
        cache = cache_path()
        clean = set(cache.read_text().splitlines()) if cache.exists() else set()
        scanned_clean: set[str] = set()
        scanned = 0

        files = working_files()
        for filename, identifier in files.items():
            if entry(identifier, filename) in clean:
                continue
            found = scan(filename, filename)
            scanned += 1
            findings.extend(found)
            if not found:
                scanned_clean.add(entry(identifier, filename))

        blobs = history_blobs()
        pending = [
            identifier
            for identifier, path in blobs.items()
            if entry(identifier, path) not in clean | scanned_clean
        ]
        with tempfile.TemporaryDirectory() as directory:
            for identifier, content in blob_contents(pending).items():
                path = blobs[identifier]
                # Keep the file name, which detect-secrets filters on.
                temporary = Path(directory) / Path(path).name
                temporary.write_bytes(content)
                found = scan(str(temporary), f"history:{path}:{identifier[:12]}")
                temporary.unlink()
                scanned += 1
                findings.extend(found)
                if not found:
                    scanned_clean.add(entry(identifier, path))

        if scanned_clean:
            cache.parent.mkdir(exist_ok=True)
            partial = cache.with_suffix(".tmp")
            partial.write_text("".join(f"{line}\n" for line in sorted(clean | scanned_clean)))
            partial.replace(cache)

    print(
        json.dumps(
            {
                "files": len(files),
                "history_blobs": len(blobs),
                "scanned": scanned,
                "findings": findings,
            }
        )
    )
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
