"""Reading the source and proving it is unchanged."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from twin_ml.pipeline.manifest import (
    ChecksumError,
    build_manifest,
    parse_sha256sums,
    sha256_file,
    verify_official,
    verify_or_pin,
)
from twin_ml.pipeline.source import RawSource, SourceError


def test_folder_and_zip_expose_the_same_relative_files(dataset: Path, dataset_zip: Path) -> None:
    folder, zipped = RawSource.open(dataset), RawSource.open(dataset_zip)
    assert folder.kind == "folder" and zipped.kind == "zip"
    assert folder.csv_files() == zipped.csv_files()
    assert list(folder.participant_files()) == [2, 3, 4, 5]
    assert sorted(folder.supplementary_files()) == [
        "bio.csv",
        "gut_health_test.csv",
        "microbes.csv",
    ]
    assert build_manifest(folder)["manifest_sha256"] == build_manifest(zipped)["manifest_sha256"]


def test_pin_then_verify_then_detect_tampering(dataset: Path, tmp_path: Path) -> None:
    lock = tmp_path / "lock.json"
    assert verify_or_pin(build_manifest(RawSource.open(dataset)), lock).status == "pinned"
    assert verify_or_pin(build_manifest(RawSource.open(dataset)), lock).status == "verified"

    copy = tmp_path / "copy"
    shutil.copytree(dataset, copy)
    target = copy / "CGMacros-002/CGMacros-002.csv"
    target.write_text(target.read_text().replace("Breakfast", "Brunch", 1))
    with pytest.raises(ChecksumError, match="CGMacros-002"):
        verify_or_pin(build_manifest(RawSource.open(copy)), lock)


def test_official_checksum_verifies_zip_and_rejects_mismatch(
    dataset_zip: Path, tmp_path: Path, dataset: Path
) -> None:
    good = tmp_path / "SHA256SUMS.txt"
    good.write_text(f"{sha256_file(dataset_zip)} {dataset_zip.name}\nabc DataDictionary.pdf\n")
    assert verify_official(RawSource.open(dataset_zip), good).status == "verified"

    bad = tmp_path / "BAD.txt"
    bad.write_text(f"{'0' * 64} {dataset_zip.name}\n")
    with pytest.raises(ChecksumError):
        verify_official(RawSource.open(dataset_zip), bad)

    assert verify_official(RawSource.open(dataset_zip), None).status == "not_supplied"
    assert verify_official(RawSource.open(dataset), good).status == "not_applicable"


def test_parse_sha256sums_handles_star_and_paths() -> None:
    sums = parse_sha256sums("AAA *CGMacros.zip\nbbb dir/other.csv\n")
    assert sums == {"CGMacros.zip": "aaa", "other.csv": "bbb"}


def test_source_errors(tmp_path: Path) -> None:
    with pytest.raises(SourceError):
        RawSource.open(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SourceError, match="bio.csv"):
        RawSource.open(tmp_path / "empty")


def test_macos_metadata_files_are_ignored(dataset: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(dataset, copy)
    (copy / "__MACOSX").mkdir()
    (copy / "__MACOSX" / "bio.csv").write_text("junk")
    (copy / "._bio.csv").write_text("junk")
    src = RawSource.open(copy)
    assert (
        build_manifest(src)["manifest_sha256"]
        == build_manifest(RawSource.open(dataset))["manifest_sha256"]
    )


def tree_digest(folder: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(folder).as_posix().encode())
            h.update(f.read_bytes())
            h.update(str(f.stat().st_mtime_ns).encode())
    return h.hexdigest()
