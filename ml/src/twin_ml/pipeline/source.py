"""Read-only access to the CGMacros source, whether it is the official ZIP or an extracted folder.

Paths are normalized relative to the dataset root (the directory that contains bio.csv), so a folder
and the ZIP it came from produce identical relative paths, and one manifest can verify either.
The source is opened for reading only; nothing in the pipeline writes to it.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pandas as pd

PARTICIPANT_FILE = re.compile(r"^CGMacros-0*(\d+)\.csv$", re.IGNORECASE)
SUPPLEMENTARY = ("bio.csv", "microbes.csv", "gut_health_test.csv")


class SourceError(RuntimeError):
    """The source is missing, unreadable, or not shaped like CGMacros."""


def _skip(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return any(p.startswith("._") or p == "__MACOSX" for p in parts)


@dataclass
class RawSource:
    path: Path
    kind: str  # "zip" | "folder"
    root_prefix: str  # members under this prefix; "" for the archive/folder root
    members: dict[str, str] = field(default_factory=dict)  # relative path -> member/file path

    @classmethod
    def open(cls, path: Path) -> RawSource:
        path = path.expanduser().resolve()
        if not path.exists():
            raise SourceError(f"source not found: {path}")
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/") and not _skip(n)]
            kind = "zip"
        elif path.is_dir():
            names = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
            names = [n for n in names if not _skip(n)]
            kind = "folder"
        else:
            raise SourceError(f"source must be the CGMacros ZIP or its extracted folder: {path}")

        bios = [n for n in names if PurePosixPath(n).name.lower() == "bio.csv"]
        if len(bios) != 1:
            raise SourceError(f"expected exactly one bio.csv in the source, found {len(bios)}")
        prefix = str(PurePosixPath(bios[0]).parent)
        prefix = "" if prefix == "." else prefix + "/"
        members = {n[len(prefix) :]: n for n in sorted(names) if n.startswith(prefix)}
        return cls(path=path, kind=kind, root_prefix=prefix, members=members)

    # -- listing ---------------------------------------------------------------------------------
    def participant_files(self) -> dict[int, str]:
        """Participant ID -> relative path, from file names like CGMacros-012.csv."""
        out: dict[int, str] = {}
        for rel in self.members:
            m = PARTICIPANT_FILE.match(PurePosixPath(rel).name)
            if m:
                pid = int(m.group(1))
                if pid in out:
                    raise SourceError(f"participant {pid} appears twice: {out[pid]} and {rel}")
                out[pid] = rel
        if not out:
            raise SourceError("no CGMacros-XXX.csv participant files found")
        return dict(sorted(out.items()))

    def supplementary_files(self) -> dict[str, str]:
        found = {
            PurePosixPath(rel).name.lower(): rel
            for rel in self.members
            if PurePosixPath(rel).name.lower() in SUPPLEMENTARY and "/" not in rel
        }
        return dict(sorted(found.items()))

    def csv_files(self) -> list[str]:
        return [rel for rel in self.members if rel.lower().endswith(".csv")]

    def other_file_count(self) -> int:
        return sum(1 for rel in self.members if not rel.lower().endswith(".csv"))

    # -- reading ---------------------------------------------------------------------------------
    def read_bytes(self, rel: str) -> bytes:
        member = self.members[rel]
        if self.kind == "zip":
            with zipfile.ZipFile(self.path) as zf:
                return zf.read(member)
        return (self.path / member).read_bytes()

    def read_csv(self, rel: str) -> pd.DataFrame:
        return pd.read_csv(io.BytesIO(self.read_bytes(rel)), low_memory=False)
