"""Model registry and training-support profiles.

A bundle is registered only if it loads through twin_ml's contract check AND passes the M4
``TwinRuntime`` compatibility check (feature set, ordered 45 columns, contract version and hash,
features.v1 and labels.v1 hashes, prior present). Serving loads the single active version, verifies
the artifact file's SHA-256 against the registry, and builds the runtime with the support profile
whose dataset hash matches the bundle's training data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from twin_core.twin import (
    ModelContractError,
    SupportProfile,
    TwinConfigs,
    TwinRuntime,
    build_support_profile,
)
from twin_core.twin.model import identity

from twin_api.models import ModelType, ModelVersion, SupportProfileRow


class RegistryError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_checked_bundle(path: Path, configs: TwinConfigs) -> Any:
    """twin_ml contract check, then the M4 twin compatibility check. Raises ModelContractError."""
    from twin_ml.dataset.leakage import LeakageError
    from twin_ml.training.bundle import load_bundle

    try:
        bundle = load_bundle(
            path, configs.contract, configs.hashes["model_contract"], configs.features
        )
    except (LeakageError, TypeError) as err:
        raise ModelContractError(str(err)) from err
    TwinRuntime(configs, bundle)  # raises ModelContractError on any mismatch
    return bundle


def register_bundle(
    session: Session, path: Path, configs: TwinConfigs, registered_by: str | None = None
) -> ModelVersion:
    path = path.resolve()
    bundle = load_checked_bundle(path, configs)
    ident = identity(bundle)
    sha = file_sha256(path)
    existing = session.scalar(
        select(ModelVersion).where(ModelVersion.model_version == ident.model_version)
    )
    if existing is not None:
        if existing.artifact_sha256 != sha:
            raise RegistryError(f"{ident.model_version} is registered with a different artifact")
        return existing
    if ident.dataset_content_sha256 is None:
        raise ModelContractError("bundle does not record its training dataset hash")
    row = ModelVersion(
        model_version=ident.model_version,
        model_type=ModelType(ident.model_name),
        feature_set=ident.feature_set,
        n_columns=ident.n_columns,
        columns=list(bundle.columns),
        contract_version=ident.contract_version,
        contract_sha256=ident.contract_sha256,
        features_sha256=ident.features_sha256,
        labels_sha256=ident.labels_sha256,
        training_config_sha256=ident.training_config_sha256,
        dataset_content_sha256=ident.dataset_content_sha256,
        dataset_label=ident.dataset_label,
        threshold=ident.threshold,
        params=ident.params,
        prior=asdict(bundle.prior) if bundle.prior is not None else None,
        artifact_path=str(path),
        artifact_sha256=sha,
        bundle_created_utc=ident.created_utc,
        registered_by=registered_by,
    )
    sp = session.scalar(
        select(SupportProfileRow)
        .where(SupportProfileRow.dataset_content_sha256 == ident.dataset_content_sha256)
        .order_by(SupportProfileRow.id.desc())
    )
    row.support_profile_id = sp.id if sp else None
    session.add(row)
    session.flush()
    return row


def activate(
    session: Session,
    model_version_id: int,
    configs: TwinConfigs,
    search: ArtifactSearch | None = None,
) -> ModelVersion:
    row = session.get(ModelVersion, model_version_id)
    if row is None:
        raise RegistryError(f"model version {model_version_id} does not exist")
    runtime_for(row, configs, session, search)  # refuse to activate anything that cannot be served
    session.execute(update(ModelVersion).where(ModelVersion.is_active).values(is_active=False))
    session.flush()
    row.is_active = True
    session.flush()
    return row


def store_support_profile(
    session: Session,
    dataset: pd.DataFrame,
    dataset_sha256: str,
    configs: TwinConfigs,
    artifact_path: Path | None = None,
) -> SupportProfileRow:
    q = configs.twin.what_if.support_quantiles
    profile = build_support_profile(
        dataset, configs.contract.columns(configs.features), q, dataset_sha256
    )
    doc = profile.model_dump(mode="json")
    sha = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        profile.save(artifact_path)
    row = session.scalar(select(SupportProfileRow).where(SupportProfileRow.profile_sha256 == sha))
    if row is None:
        row = SupportProfileRow(
            profile_sha256=sha,
            dataset_content_sha256=dataset_sha256,
            quantile_lo=q[0],
            quantile_hi=q[1],
            rows=profile.rows,
            profile=doc,
            artifact_path=None if artifact_path is None else str(artifact_path),
        )
        session.add(row)
        session.flush()
    session.execute(
        update(ModelVersion)
        .where(ModelVersion.dataset_content_sha256 == dataset_sha256)
        .values(support_profile_id=row.id)
    )
    session.flush()
    return row


DEFAULT_MODELS_DIR = Path("data/processed/m3/models")


@dataclass(frozen=True)
class ArtifactSearch:
    """Where serving looks for a registered model file (the registry stores where it was built).

    The stored ``artifact_path`` is the path on the machine that registered the bundle, so it is
    only a hint on any other machine (a container, a server). Serving looks, in order, in:
    ``models_dir`` if one is configured (TWIN_MODELS_DIR), the stored path (resolved against
    ``repo_root`` when relative), and ``repo_root/data/processed/m3/models``, each by the stored
    file name. Whichever file is found must still match the registered SHA-256 and identity.
    """

    repo_root: Path
    models_dir: Path | None = None

    def candidates(self, stored: str) -> list[Path]:
        p = Path(stored)
        found: list[Path] = []
        if self.models_dir is not None:
            found.append(self.models_dir / p.name)
        found.append(p if p.is_absolute() else self.repo_root / p)
        found.append(self.repo_root / DEFAULT_MODELS_DIR / p.name)
        return list(dict.fromkeys(found))  # keep order, drop duplicates


def locate_artifact(stored: str, search: ArtifactSearch | None) -> Path:
    """The model file to load for a registry entry. Integrity is checked by the caller (SHA-256)."""
    tried = search.candidates(stored) if search is not None else [Path(stored)]
    for path in tried:
        if path.is_file():
            return path
    where = ", ".join(str(p.parent) for p in tried)
    raise ModelContractError(f"model artifact missing: {Path(stored).name} (looked in {where})")


def runtime_for(
    row: ModelVersion, configs: TwinConfigs, session: Session, search: ArtifactSearch | None = None
) -> TwinRuntime:
    path = locate_artifact(row.artifact_path, search)
    if file_sha256(path) != row.artifact_sha256:
        raise ModelContractError("model artifact changed since it was registered")
    bundle = load_checked_bundle(path, configs)
    if identity(bundle).model_version != row.model_version:
        raise ModelContractError("artifact identity differs from the registry entry")
    support = None
    if row.support_profile_id is not None:
        sp = session.get(SupportProfileRow, row.support_profile_id)
        assert sp is not None
        support = SupportProfile.model_validate(sp.profile)
    return TwinRuntime(configs, bundle, support)


def active_version(session: Session) -> ModelVersion | None:
    return session.scalar(select(ModelVersion).where(ModelVersion.is_active))
