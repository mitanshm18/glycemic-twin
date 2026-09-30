# ADR-018: Backend and database contract v1 (PostgreSQL 16 + FastAPI)

- Status: accepted (M5)
- Date: 2026-09-29
- Code: `api/` (package `twin_api`); migration `api/migrations/versions/0001_initial_schema.py`
- Related: ADR-015 (model contract), ADR-016 (training), ADR-017 (twin state contract)

## Decision

1. **The database stores observations and the engine's outputs, never its logic.** The API reads a
   patient's rows into a `PatientRecord` (`DbRecordSource`) and calls `twin_core.twin.build_state`
   and `simulate`. It adds validation, persistence and access control only. twin_core stays free of
   web and database imports (tested in M4).
2. **Schema (16 tables, one Alembic revision).**
   - identity: `users` (Argon2id PHC hash, role enum, lockout counters), `sessions` (SHA-256 of the
     session and CSRF tokens only).
   - observations, copied from M1 without re-derivation: `patients`, `clinical_observations` (one
     bio.csv field per row with `observed`/`derived` provenance and the derivation text),
     `cgm_readings` (all minute rows with `dexcom_is_native`), `wearable_minutes` (NULL = unknown),
     `meals` (Amount Consumed kept as observed but never a model input; photos not loaded),
     `meal_labels` (frozen labels.v1 outcome, its version and config hash).
   - model registry: `model_versions` (type, feature set, ordered columns, contract version and hash,
     features/labels hashes, training-data hash, threshold, params, prior, artifact path and SHA-256,
     active flag with at most one active row), `support_profiles`.
   - outputs: `twin_states` (the exact twin-state/1 document, unique by its content hash),
     `predictions` (one per state), `what_if_runs` (accepted, out-of-support and rejected scenarios).
   - operations: `replay_sessions`, `audit_log`, `ingestion_runs`.
3. **Constraints encode the science, not just types**: a label exists iff the meal is frozen-usable;
   eligible implies usable; coverage in [0, 1]; native CGM rows have a value; macros are
   non-negative; probabilities in [0, 1] and present iff scored; an out-of-support scenario has no
   estimate; a derived clinical field names its derivation; a stored state's document carries the same
   `state_id` as its row; one active model.
4. **Time.** Observation times are `timestamp without time zone` (CGMacros local clock, date-shifted);
   system times are `timestamptz`. The API rejects time-zone-aware `as_of` values.
5. **JSONB only for versioned documents owned elsewhere** (twin-state/1, twin-scenario/1, the
   support profile, the model's ordered columns/params/prior) and free-form audit/ingestion detail.
   Everything queried or constrained is a column.
6. **Ingestion** reads only the processed M1 Parquet tables and the M1/M2 manifests. It is
   deterministic (sorted rows, content hash over all tables), idempotent (same content = no-op) and
   refuses to overwrite different data unless `--replace`. Every row carries its `ingestion_run_id`.
7. **Model registry.** A bundle is registered only after twin_ml's contract check and the M4
   `TwinRuntime` compatibility check. Serving re-verifies the artifact SHA-256 and identity, and
   attaches the support profile whose dataset hash equals the bundle's; anything else is refused
   (HTTP 409 `MODEL_INCOMPATIBLE`). What-if is disabled (503) without a matching support profile.
8. **Security.** Argon2id (t=3, p=4, m=64 MiB); opaque 256-bit session tokens in HttpOnly,
   SameSite=Strict, Secure cookies (Secure off only via `TWIN_COOKIE_SECURE=false` for local http);
   server-side sessions (logout and expiry immediate); per-session CSRF token required on every
   POST; roles `clinician` and `admin`; account lockout after 5 failures for 15 minutes; identical
   responses for unknown users and wrong passwords; audit log written in its own transaction so
   denials survive failed requests. Secrets only in `.env` (gitignored).
9. **Errors.** Every failure returns `{"error": {"code", "message", "details"}}` with codes
   PATIENT_NOT_FOUND, NOT_FOUND, INVALID_TIMESTAMP, DATA_OUT_OF_RANGE, NO_CURRENT_MEAL,
   MODEL_UNAVAILABLE, MODEL_INCOMPATIBLE, WHAT_IF_UNSUPPORTED, VALIDATION_ERROR, UNAUTHENTICATED,
   FORBIDDEN, CSRF_FAILED, CONFLICT, INTERNAL_ERROR. No stack traces, SQL or submitted values leak.

## Alternatives considered

- **Recompute features in SQL / store M2 features.** Would duplicate twin_core and invite
  train/serve skew. Rejected: the database holds raw cleaned observations; features are computed by
  the same Python functions as in training.
- **JWT bearer tokens.** Cannot be revoked server-side without extra state and are easy to leak to
  JavaScript. Rejected for an HttpOnly session cookie backed by the `sessions` table.
- **Time-zone-aware observation timestamps.** CGMacros gives no zone; inventing UTC would be false.
- **One JSONB blob per patient.** Unconstrained and unqueryable. Rejected.

## Consequences

- M6 (frontend) consumes `/api/v1` with a session cookie and the CSRF header; the twin-state and
  scenario schemas it renders are exactly ADR-017's.
- A new twin-state schema version or a new table means a new Alembic revision and ADR.
