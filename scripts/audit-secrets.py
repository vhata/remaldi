#!/usr/bin/env python3
"""Scan publishable files and reachable Git blobs without printing secret values.

Blobs are immutable, so a blob that scanned clean is recorded in a cache in
the Git directory and skipped on later runs. The cache is keyed by the
detect-secrets version and settings, and by full path as well as blob, since
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
    key = hashlib.sha256(f"path-context-v2\n{VERSION}\n{settings}".encode()).hexdigest()
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


def history_blobs() -> dict[str, set[str]]:
    """Map reachable blobs to every path used in historical tree snapshots."""
    trees = set(git("log", "--all", "--format=%T").decode().splitlines())
    # Include refs pointing directly to trees (including annotated tags),
    # which git log omits. Blob-only refs have no filename context.
    tips = git("rev-parse", "--all").decode().splitlines()
    described = git(
        "cat-file",
        "--batch-check=%(objecttype) %(objectname)",
        stdin="".join(f"{tip}^{{tree}}\n" for tip in tips).encode(),
    ).decode()
    for line in described.splitlines():
        kind, _, identifier = line.partition(" ")
        if kind == "tree":
            trees.add(identifier)
    blobs: dict[str, set[str]] = {}
    for tree in sorted(trees):
        for record in git("ls-tree", "-rz", "--full-tree", tree).split(b"\0"):
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            _, kind, identifier = metadata.decode().split()
            if kind == "blob":
                blobs.setdefault(identifier, set()).add(path.decode())
    return blobs


def entry(identifier: str, path: str) -> str:
    # JSON keeps newline-containing paths within one cache line.
    return json.dumps([identifier, path])


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
            for identifier, paths in blobs.items()
            if any(entry(identifier, path) not in clean | scanned_clean for path in paths)
        ]
        for identifier, content in blob_contents(pending).items():
            for path in sorted(blobs[identifier]):
                if entry(identifier, path) in clean | scanned_clean:
                    continue
                # Isolate paths that were files in one snapshot and
                # directories in another.
                with tempfile.TemporaryDirectory() as directory:
                    # Keep the complete path, which detect-secrets filters on.
                    temporary = Path(directory) / path
                    temporary.parent.mkdir(parents=True, exist_ok=True)
                    temporary.write_bytes(content)
                    found = scan(str(temporary), f"history:{path}:{identifier[:12]}")
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
