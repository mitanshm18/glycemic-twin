"""Checksums: prove the pipeline read exactly the files we think it read.

Two independent checks:
1. Official: if the source is PhysioNet's ZIP and SHA256SUMS.txt is supplied, the ZIP's SHA-256 must
   match PhysioNet's published value. This is the only check against the publisher.
2. Pinned: a manifest of every CSV (relative path, size, SHA-256). The first run writes
   data/manifests/cgmacros-1.0.0.lock.json; every later run must match it exactly. Because paths are
   relative to the dataset root, a lock made from the ZIP also verifies an extracted folder.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from twin_ml.pipeline.source import RawSource


class ChecksumError(RuntimeError):
    """A checksum did not match. The run stops; nothing downstream is trusted."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(source: RawSource) -> dict[str, object]:
    files = []
    for rel in source.csv_files():
        data = source.read_bytes(rel)
        files.append({"path": rel, "bytes": len(data), "sha256": sha256_bytes(data)})
    body = {
        "dataset": "CGMacros",
        "dataset_version": "1.0.0",
        "csv_files": files,
        "non_csv_file_count": source.other_file_count(),
    }
    body["manifest_sha256"] = sha256_bytes(json.dumps(body, sort_keys=True).encode())
    return body


def parse_sha256sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            out[parts[-1].lstrip("*").split("/")[-1]] = parts[0].lower()
    return out


@dataclass(frozen=True)
class OfficialCheck:
    status: str  # "verified" | "not_applicable" | "not_supplied"
    detail: str


def verify_official(source: RawSource, sums_path: Path | None) -> OfficialCheck:
    if source.kind != "zip":
        return OfficialCheck(
            "not_applicable",
            "source is an extracted folder; PhysioNet publishes checksums for the ZIP only",
        )
    if sums_path is None:
        return OfficialCheck(
            "not_supplied", "pass --official-sums SHA256SUMS.txt to verify the ZIP"
        )
    expected = parse_sha256sums(sums_path.read_text()).get(source.path.name)
    if expected is None:
        raise ChecksumError(f"{source.path.name} is not listed in {sums_path}")
    actual = sha256_file(source.path)
    if actual != expected:
        raise ChecksumError(f"{source.path.name}: SHA-256 {actual} != official {expected}")
    return OfficialCheck("verified", f"{source.path.name} matches PhysioNet SHA256SUMS ({actual})")


@dataclass(frozen=True)
class LockCheck:
    status: str  # "verified" | "pinned"
    lock_path: str


def verify_or_pin(manifest: dict[str, object], lock_path: Path) -> LockCheck:
    if lock_path.exists():
        pinned = json.loads(lock_path.read_text())
        if pinned["manifest_sha256"] != manifest["manifest_sha256"]:
            old = {f["path"]: f["sha256"] for f in pinned["csv_files"]}
            new = {f["path"]: f["sha256"] for f in manifest["csv_files"]}  # type: ignore[attr-defined]
            changed = sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))
            raise ChecksumError(
                f"source differs from pinned manifest {lock_path}: {len(changed)} file(s) differ, "
                f"e.g. {changed[:5]}. If the new source is intended, delete the lock deliberately."
            )
        return LockCheck("verified", str(lock_path))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return LockCheck("pinned", str(lock_path))
