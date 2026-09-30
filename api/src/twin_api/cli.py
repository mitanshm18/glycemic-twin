"""Command line for the backend. Every command reads TWIN_DATABASE_URL (see .env.example).

twin-api migrate                         alembic upgrade head
twin-api ingest [--replace]              load data/processed/m1 + m2 manifests into PostgreSQL
twin-api support-profile                 build the training-support profile from the real M2 dataset
twin-api register-m3 [--activate NAME]   register the M3 bundles (M4 compatibility checks), activate one
twin-api register-model PATH [--activate]
twin-api create-user USERNAME --role clinician|admin   (password from TWIN_NEW_USER_PASSWORD or prompt)
twin-api link-google USERNAME EMAIL      allow that Google account to sign in as USERNAME (M6)
twin-api unlink-google USERNAME          remove USERNAME's Google sign-in
twin-api serve [--host 127.0.0.1] [--port 8000] [--reload]
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from twin_core.twin import ModelContractError, TwinConfigs


def _settings():  # type: ignore[no-untyped-def]
    from twin_api.settings import get_settings

    return get_settings()


def _engine():  # type: ignore[no-untyped-def]
    from twin_api.db import make_engine

    return make_engine(_settings().database_url.get_secret_value())


def cmd_migrate(args: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    # ConfigParser treats "%" as interpolation: escape it so passwords containing "%" work
    cfg.set_main_option(
        "sqlalchemy.url", _settings().database_url.get_secret_value().replace("%", "%%")
    )
    command.upgrade(cfg, args.revision)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from twin_api.ingest import IngestError, ingest_tables, load_processed, record_failure

    s = _settings()
    engine = _engine()
    configs = TwinConfigs.load(s.config_dir)
    try:
        tables, m1, m2 = load_processed(s.repo_root)
        res = ingest_tables(
            engine,
            tables,
            source_dir=str(s.repo_root / "data/processed"),
            source_label=s.source_label,
            m1_manifest=m1,
            m2_manifest=m2,
            features_sha256=configs.hashes["features"],
            labels_version=configs.labels.version,
            replace=args.replace,
        )
    except IngestError as err:
        record_failure(engine, str(s.repo_root / "data/processed"), s.source_label, str(err))
        print(f"ingestion failed: {err}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "run_id": res.run_id,
                "status": res.status,
                "content_sha256": res.content_sha256,
                **res.counts,
            },
            indent=2,
        )
    )
    return 0


def cmd_support(args: argparse.Namespace) -> int:
    import pandas as pd
    from twin_ml.pipeline.run import content_sha256

    from twin_api.db import make_sessionmaker, session_scope
    from twin_api.registry import store_support_profile

    s = _settings()
    configs = TwinConfigs.load(s.config_dir)
    path = s.repo_root / "data/processed/m2/dataset.parquet"
    dataset = pd.read_parquet(path)
    sha = content_sha256(dataset)
    with session_scope(make_sessionmaker(_engine())) as db:
        row = store_support_profile(
            db, dataset, sha, configs, s.repo_root / "data/processed/m5/support_profile.v1.json"
        )
        print(
            json.dumps(
                {
                    "support_profile_id": row.id,
                    "dataset_content_sha256": sha,
                    "features": len(row.profile["features"]),
                    "rows": row.rows,
                    "quantiles": [row.quantile_lo, row.quantile_hi],
                    "profile_sha256": row.profile_sha256,
                },
                indent=2,
            )
        )
    return 0


def _register(paths: list[Path], activate_name: str | None) -> int:
    from twin_api.db import make_sessionmaker, session_scope
    from twin_api.registry import activate, register_bundle

    s = _settings()
    configs = TwinConfigs.load(s.config_dir)
    with session_scope(make_sessionmaker(_engine())) as db:
        rows = []
        for p in paths:
            try:
                rows.append(register_bundle(db, p, configs, registered_by="cli"))
            except ModelContractError as err:
                print(f"REFUSED {p}: {err}", file=sys.stderr)
                return 1
        for r in rows:
            if activate_name and (
                r.model_type.value == activate_name or r.model_version == activate_name
            ):
                activate(db, r.id, configs, s.artifact_search)
        for r in rows:
            print(
                json.dumps(
                    {
                        "id": r.id,
                        "model_version": r.model_version,
                        "active": r.is_active,
                        "support_profile_id": r.support_profile_id,
                        "artifact_sha256": r.artifact_sha256,
                    }
                )
            )
    return 0


def cmd_register_m3(args: argparse.Namespace) -> int:
    s = _settings()
    folder = s.models_dir or s.repo_root / "data/processed/m3/models"
    paths = sorted(folder.glob("*__full_personal.joblib"))
    if not paths:
        print(f"no bundles in {folder}; run `make m3` first", file=sys.stderr)
        return 1
    return _register(paths, args.activate)


def cmd_register(args: argparse.Namespace) -> int:
    path = Path(args.path)
    return _register_activate(path) if args.activate else _register([path], None)


def _register_activate(path: Path) -> int:
    from twin_api.db import make_sessionmaker, session_scope
    from twin_api.registry import activate, register_bundle

    s = _settings()
    configs = TwinConfigs.load(s.config_dir)
    with session_scope(make_sessionmaker(_engine())) as db:
        try:
            row = register_bundle(db, path, configs, registered_by="cli")
        except ModelContractError as err:
            print(f"REFUSED {path}: {err}", file=sys.stderr)
            return 1
        activate(db, row.id, configs, s.artifact_search)
        print(json.dumps({"id": row.id, "model_version": row.model_version, "active": True}))
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from twin_api.auth import create_user
    from twin_api.db import make_sessionmaker, session_scope

    password = os.environ.get("TWIN_NEW_USER_PASSWORD") or getpass.getpass(
        "password (>= 12 chars): "
    )
    with session_scope(make_sessionmaker(_engine())) as db:
        user = create_user(db, args.username, password, args.role)
        print(json.dumps({"id": user.id, "username": user.username, "role": user.role.value}))
    return 0


def cmd_link_google(args: argparse.Namespace) -> int:
    from twin_api.auth import link_identity
    from twin_api.db import make_sessionmaker, session_scope
    from twin_api.errors import ApiError

    try:
        with session_scope(make_sessionmaker(_engine())) as db:
            ident = link_identity(db, args.username, "google", args.email, created_by="cli")
            out = {"username": args.username, "provider": "google", "email": ident.email}
    except (ApiError, ValueError) as err:
        print(f"link-google failed: {err}", file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


def cmd_unlink_google(args: argparse.Namespace) -> int:
    from twin_api.auth import unlink_identities
    from twin_api.db import make_sessionmaker, session_scope
    from twin_api.errors import ApiError

    try:
        with session_scope(make_sessionmaker(_engine())) as db:
            n = unlink_identities(db, args.username, "google")
    except ApiError as err:
        print(f"unlink-google failed: {err}", file=sys.stderr)
        return 1
    print(json.dumps({"username": args.username, "provider": "google", "removed": n}))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from twin_api.logs import configure_logging

    s = _settings()  # validates the configuration (production rules) before binding a port
    if args.reload and s.production:
        print("--reload is for development only; refusing in production", file=sys.stderr)
        return 2
    configure_logging(s.log_level, s.log_style)

    uvicorn.run(
        "twin_api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,  # keep the format installed above (uvicorn lines become JSON too)
        access_log=False,  # RequestLog writes one line per request, without query strings
        # client address and scheme from X-Forwarded-* only when the reverse proxy sent them
        proxy_headers=True,
        forwarded_allow_ips=s.forwarded_allow_ips,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="twin-api")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate")
    m.add_argument("--revision", default="head")
    i = sub.add_parser("ingest")
    i.add_argument("--replace", action="store_true")
    sub.add_parser("support-profile")
    r3 = sub.add_parser("register-m3")
    r3.add_argument("--activate", default=None, help="model type (xgboost|logistic) to activate")
    r = sub.add_parser("register-model")
    r.add_argument("path")
    r.add_argument("--activate", action="store_true")
    u = sub.add_parser("create-user")
    u.add_argument("username")
    u.add_argument("--role", choices=["clinician", "admin"], required=True)
    lg = sub.add_parser("link-google")
    lg.add_argument("username")
    lg.add_argument("email")
    ug = sub.add_parser("unlink-google")
    ug.add_argument("username")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)
    handlers = {
        "migrate": cmd_migrate,
        "ingest": cmd_ingest,
        "support-profile": cmd_support,
        "register-m3": cmd_register_m3,
        "register-model": cmd_register,
        "create-user": cmd_create_user,
        "link-google": cmd_link_google,
        "unlink-google": cmd_unlink_google,
        "serve": cmd_serve,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
