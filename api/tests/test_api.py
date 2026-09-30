"""API: health, authentication, authorization, patient data, twin, prediction, what-if, replay,
errors and response schemas (disposable PostgreSQL; SYNTHETIC data)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from api_support import PASSWORDS
from sqlalchemy import text
from twin_core.twin import ScenarioResult, TwinState

API = "/api/v1"


def err(r: Any) -> str:
    body = r.json()
    assert set(body) == {"error"} and {"code", "message"} <= set(body["error"]), body
    return str(body["error"]["code"])


def eligible_meal(m1: Any) -> pd.Series:
    t = m1["tables"]
    ok = (
        t["meal_outcomes"]
        .query("eligible")
        .merge(t["meals"][["meal_id", "started_at"]], on="meal_id")
    )
    return ok.iloc[0]


# ------------------------------------------------------------------------------------ health


def test_health_and_readiness(client: Any) -> None:
    assert client.get(f"{API}/health").json() == {"status": "ok"}
    r = client.get(f"{API}/ready")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ready"] and body["migrations_at_head"] and body["model_compatible"]
    assert body["support_profile"] and body["active_model"].startswith("logistic__full_personal")


# ------------------------------------------------------------------------------------ auth


def test_login_sets_a_secure_session_cookie_and_logout_revokes_it(client: Any) -> None:
    r = client.post(
        f"{API}/auth/login", json={"username": "clinician", "password": PASSWORDS["clinician"]}
    )
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    # Lax (M6, ADR-019): sent on top-level navigations so a reload never loses the session; CSRF is
    # enforced by the X-CSRF-Token header on every state-changing request, not by SameSite.
    assert "httponly" in cookie and "samesite=lax" in cookie and "twin_session=" in cookie
    assert "path=/" in cookie and "max-age=" in cookie
    assert r.json()["user"]["role"] == "clinician" and len(r.json()["csrf_token"]) > 30
    assert client.get(f"{API}/auth/me").json()["username"] == "clinician"
    csrf = r.json()["csrf_token"]
    assert client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert err(client.get(f"{API}/auth/me")) == "UNAUTHENTICATED"


def test_bad_credentials_look_identical_and_are_audited(client: Any, engine: Any) -> None:
    a = client.post(
        f"{API}/auth/login", json={"username": "clinician", "password": "wrong-password"}
    )
    b = client.post(f"{API}/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    with engine.connect() as c:
        denied = c.scalar(
            text("select count(*) from audit_log where action = 'login' and outcome = 'denied'")
        )
    assert denied >= 2


def test_repeated_failures_lock_the_account(client: Any, admin: Any, engine: Any) -> None:
    c, h = admin
    assert (
        c.post(
            f"{API}/admin/users",
            headers=h,
            json={"username": "locky", "password": "locky-password-789", "role": "clinician"},
        ).status_code
        == 201
    )
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"username": "locky", "password": "nope-nope-nope"})
    r = client.post(
        f"{API}/auth/login", json={"username": "locky", "password": "locky-password-789"}
    )
    assert r.status_code == 401  # locked even with the right password
    with engine.connect() as conn:
        assert conn.scalar(text("select locked_until > now() from users where username = 'locky'"))


def test_passwords_are_stored_as_argon2id(engine: Any, loaded: Any) -> None:
    with engine.connect() as c:
        hashes = [h for (h,) in c.execute(text("select password_hash from users"))]
    assert hashes and all(h.startswith("$argon2id$v=19$m=65536,t=3,p=4$") for h in hashes)
    assert not any(pw in h for h in hashes for pw in PASSWORDS.values())


def test_everything_but_health_requires_a_session(client: Any) -> None:
    for path in ("/patients", "/patients/2", "/patients/2/twin", "/admin/models", "/auth/me"):
        r = client.get(API + path)
        assert r.status_code == 401 and err(r) == "UNAUTHENTICATED", path


def test_state_changing_requests_need_the_csrf_token(clinician: Any) -> None:
    c, _ = clinician
    r = c.post(f"{API}/patients/2/predictions", json={})
    assert r.status_code == 403 and err(r) == "CSRF_FAILED"
    r = c.post(f"{API}/patients/2/predictions", json={}, headers={"X-CSRF-Token": "forged"})
    assert err(r) == "CSRF_FAILED"


def test_clinicians_cannot_use_admin_endpoints(clinician: Any, admin: Any, engine: Any) -> None:
    c, h = clinician
    for method, path in (
        ("get", "/admin/models"),
        ("get", "/admin/audit"),
        ("get", "/admin/ingestion-runs"),
        ("post", "/admin/models/1/activate"),
    ):
        r = getattr(c, method)(API + path, headers=h)
        assert r.status_code == 403 and err(r) == "FORBIDDEN", path
    a, ha = admin
    assert a.get(f"{API}/admin/models", headers=ha).status_code == 200
    audit = a.get(f"{API}/admin/audit", headers=ha).json()
    assert any(e["action"] == "authorize" and e["outcome"] == "denied" for e in audit)


# ------------------------------------------------------------------------------------ patients


def test_patient_list_and_detail(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    people = sorted(set(int(p) for p in m1["tables"]["cgm"]["participant_id"]))
    lst = c.get(f"{API}/patients").json()
    assert [p["id"] for p in lst] == people
    d = c.get(f"{API}/patients/{people[0]}").json()
    assert d["cgm_readings"] == int((m1["tables"]["cgm"]["participant_id"] == people[0]).sum())
    assert d["external_ref"] == f"CGMacros-{people[0]:03d}"
    r = c.get(f"{API}/patients/9999")
    assert r.status_code == 404 and err(r) == "PATIENT_NOT_FOUND"


def test_clinical_record_keeps_observed_and_derived_provenance(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    pid = int(m1["tables"]["cgm"]["participant_id"].iloc[0])
    rows = c.get(f"{API}/patients/{pid}/clinical").json()
    by = {r["field"]: r for r in rows}
    assert by["hba1c_pct"]["provenance"] == "observed" and by["hba1c_pct"]["value_num"] is not None
    assert by["glycemic_group"]["provenance"] == "derived" and by["glycemic_group"]["derivation"]


def test_time_series_windows_are_validated(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    pid = int(m1["tables"]["cgm"]["participant_id"].iloc[0])
    pts = c.get(f"{API}/patients/{pid}/cgm", params={"native_only": True}).json()
    assert pts and all(p["dexcom_is_native"] for p in pts)
    assert c.get(f"{API}/patients/{pid}/wearable").status_code == 200
    r = c.get(
        f"{API}/patients/{pid}/cgm",
        params={"start": "2021-01-01T00:00:00", "end": "2021-02-01T00:00:00"},
    )
    assert r.status_code == 422 and err(r) == "INVALID_TIMESTAMP"
    r = c.get(f"{API}/patients/{pid}/cgm", params={"end": "2021-06-02T00:00:00+02:00"})
    assert err(r) == "INVALID_TIMESTAMP"
    r = c.get(f"{API}/patients/{pid}/cgm", params={"start": "not-a-date"})
    assert r.status_code == 422 and err(r) == "VALIDATION_ERROR"


def test_meals_and_outcomes(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    pid = int(m1["tables"]["meals"]["participant_id"].iloc[0])
    meals = c.get(f"{API}/patients/{pid}/meals").json()
    outs = c.get(f"{API}/patients/{pid}/meal-outcomes").json()
    assert len(meals) == len(outs) > 0
    assert all((o["label"] is not None) == o["frozen_usable"] for o in outs)
    assert all("amount_consumed" not in k for m in meals for k in m)


# ------------------------------------------------------------------------------------ twin


def test_twin_state_is_the_adr017_schema_and_persisted_once(
    clinician: Any, m1: Any, engine: Any
) -> None:
    c, _ = clinician
    meal = eligible_meal(m1)
    pid = int(meal["participant_id"])
    as_of = (pd.Timestamp(meal["started_at"]) + pd.Timedelta(minutes=10)).isoformat()
    a = c.get(f"{API}/patients/{pid}/twin", params={"as_of": as_of})
    b = c.get(f"{API}/patients/{pid}/twin", params={"as_of": as_of})
    assert a.status_code == 200, a.text
    state = TwinState.model_validate(a.json())
    assert a.json() == b.json() and state.schema_version == "twin-state/1"
    with engine.connect() as conn:
        n = conn.scalar(
            text("select count(*) from twin_states where state_id = :s"), {"s": state.state_id}
        )
        doc = conn.scalar(
            text("select state from twin_states where state_id = :s"), {"s": state.state_id}
        )
    assert n == 1 and doc == a.json()
    assert c.get(f"{API}/twin-states/{state.state_id}").json() == a.json()
    assert state.provenance.model is not None and state.provenance.model.n_columns == 45
    assert state.risk.status == "scored" and len(state.risk.model_inputs or {}) == 45


def test_twin_as_of_errors(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    pid = int(m1["tables"]["cgm"]["participant_id"].iloc[0])
    r = c.get(f"{API}/patients/{pid}/twin", params={"as_of": "1999-01-01T00:00:00"})
    assert r.status_code == 422 and err(r) == "DATA_OUT_OF_RANGE"
    r = c.get(f"{API}/patients/{pid}/twin", params={"as_of": "2021-06-01T12:00:00Z"})
    assert r.status_code == 422 and err(r) == "INVALID_TIMESTAMP"
    r = c.get(f"{API}/patients/{pid}/twin", params={"meal_id": "does-not-exist"})
    assert r.status_code == 404
    assert c.get(f"{API}/twin-states/{'0' * 64}").status_code == 404


def test_prediction_returns_calibrated_risk_with_provenance(
    clinician: Any, m1: Any, engine: Any
) -> None:
    c, h = clinician
    meal = eligible_meal(m1)
    pid = int(meal["participant_id"])
    body = {"as_of": pd.Timestamp(meal["started_at"]).isoformat(), "meal_id": meal["meal_id"]}
    r = c.post(f"{API}/patients/{pid}/predictions", json=body, headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "scored" and 0 <= p["probability"] <= 1 and p["threshold"] is not None
    assert p["above_threshold"] == (p["probability"] >= p["threshold"])
    assert len(p["model_inputs"]) == 45 and p["model"]["model_version"].startswith(
        "logistic__full_personal"
    )
    assert p["provenance"]["current_meal_id"] == meal["meal_id"] and p["uncertainty"]["level"]
    assert "not medical advice" in p["disclaimer"]
    again = c.post(f"{API}/patients/{pid}/predictions", json=body, headers=h).json()
    assert again["prediction_id"] == p["prediction_id"] and again["state_id"] == p["state_id"]


def test_prediction_without_a_current_meal_is_a_clear_error(clinician: Any, m1: Any) -> None:
    c, h = clinician
    meals = m1["tables"]["meals"]
    pid = int(meals["participant_id"].iloc[0])
    first = pd.Timestamp(meals[meals["participant_id"] == pid]["started_at"].min())
    r = c.post(
        f"{API}/patients/{pid}/predictions",
        headers=h,
        json={"as_of": (first - pd.Timedelta(hours=3)).isoformat()},
    )
    assert r.status_code in (409, 422) and err(r) in ("NO_CURRENT_MEAL", "DATA_OUT_OF_RANGE")


def test_what_if_ok_rejected_and_out_of_support(
    clinician: Any, m1: Any, engine: Any, bundle: Any
) -> None:
    c, h = clinician
    meal = eligible_meal(m1)
    pid = int(meal["participant_id"])
    base = {"as_of": pd.Timestamp(meal["started_at"]).isoformat(), "meal_id": meal["meal_id"]}
    ok = c.post(
        f"{API}/patients/{pid}/what-if", headers=h, json={**base, "changes": {"carbs_g": -5}}
    )
    assert ok.status_code == 200, ok.text
    res = ScenarioResult.model_validate(ok.json())
    assert res.status in ("ok", "out_of_support") and "non-causal" in res.kind
    for bad, code in (
        ({"insulin_units": 2}, "WHAT_IF_UNSUPPORTED"),
        ({"carbs_g": 500}, "WHAT_IF_UNSUPPORTED"),
        ({"sugar": 5}, "WHAT_IF_UNSUPPORTED"),
    ):
        r = c.post(f"{API}/patients/{pid}/what-if", headers=h, json={**base, "changes": bad})
        assert r.status_code == 422 and err(r) == code, bad
    r = c.post(
        f"{API}/patients/{pid}/what-if", headers=h, json={**base, "changes": {"carbs_g": "5"}}
    )
    assert r.status_code == 422 and err(r) == "VALIDATION_ERROR"
    with engine.connect() as conn:
        rejected = conn.scalar(text("select count(*) from what_if_runs where status = 'rejected'"))
        stored = conn.scalar(
            text("select result from what_if_runs where scenario_id = :s"), {"s": res.scenario_id}
        )
    assert rejected >= 3 and stored == ok.json()
    # the support bound for carbs, from the stored profile:
    with engine.connect() as conn:
        carbs_hi = conn.scalar(
            text("select (profile->'features'->'carbs_g'->>'hi')::float from support_profiles")
        )
    carbs = float(m1["tables"]["meals"].set_index("meal_id").loc[meal["meal_id"], "carbs_g"])
    if carbs + 100 > carbs_hi:
        r = c.post(
            f"{API}/patients/{pid}/what-if", headers=h, json={**base, "changes": {"carbs_g": 100}}
        )
        assert r.status_code == 200 and r.json()["status"] == "out_of_support"
        assert r.json()["scenario_probability"] is None and r.json()["risk_delta"] is None


def test_replay_steps_through_time(clinician: Any, m1: Any) -> None:
    c, h = clinician
    meal = eligible_meal(m1)
    pid = int(meal["participant_id"])
    t0 = pd.Timestamp(meal["started_at"])
    r = c.post(
        f"{API}/replays",
        headers=h,
        json={
            "patient_id": pid,
            "start_at": t0.isoformat(),
            "end_at": (t0 + pd.Timedelta(minutes=30)).isoformat(),
            "step_minutes": 15,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    steps = [c.post(f"{API}/replays/{rid}/step", headers=h).json() for _ in range(4)]
    as_ofs = [s["state"]["as_of"] for s in steps]
    assert as_ofs[:3] == [(t0 + pd.Timedelta(minutes=m)).isoformat() for m in (0, 15, 30)]
    assert [s["finished"] for s in steps] == [False, False, True, True]
    assert steps[0]["replay"]["last_state_id"] == steps[0]["state"]["state_id"]


def test_openapi_documents_the_exact_twin_schemas(client: Any) -> None:
    spec = client.get(f"{API}/openapi.json").json()
    paths = spec["paths"]
    for p in (
        "/api/v1/patients/{pid}/twin",
        "/api/v1/patients/{pid}/predictions",
        "/api/v1/patients/{pid}/what-if",
        "/api/v1/auth/login",
        "/api/v1/ready",
    ):
        assert p in paths, p
    ref = paths["/api/v1/patients/{pid}/twin"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert ref["$ref"].endswith("/TwinState")
    assert "ScenarioResult" in spec["components"]["schemas"]


def test_unknown_routes_use_the_error_shape(client: Any) -> None:
    r = client.get(f"{API}/nope")
    assert r.status_code == 404 and err(r) == "NOT_FOUND"


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "a", "password": "x"},
        {"username": "ok_user"},
        {"username": "ok_user", "password": "p", "extra": 1},
    ],
)
def test_login_validation(client: Any, payload: dict[str, Any]) -> None:
    r = client.post(f"{API}/auth/login", json=payload)
    assert r.status_code == 422 and err(r) == "VALIDATION_ERROR"
