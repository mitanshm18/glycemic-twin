# Glycemic Twin: a clinician-facing Digital Twin for post-meal glycemic risk

[![CI](https://github.com/mitanshm18/glycemic-twin/actions/workflows/ci.yml/badge.svg)](https://github.com/mitanshm18/glycemic-twin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Data: CC BY-NC-SA 4.0](https://img.shields.io/badge/data-CC%20BY--NC--SA%204.0-lightgrey.svg)](NOTICE.md)

> **Research prototype.** Not a medical device, not medical advice, not an autonomous diagnostic
> system, and not clinically deployed. It runs on open, de-identified research data. "Historical
> replay" replays past recorded data; it is not live patient monitoring.

## 1. Team details

| | |
|---|---|
| **Team name** | IdeaForge |
| **Team leader** | Mitansh Mathur |
| **College** | IIIT Allahabad |

## 2. Project title

**Glycemic Twin**: a personal Digital Twin that estimates, at each logged meal, the risk that glucose
will exceed 180 mg/dL within the next two hours, for people with prediabetes and type 2 diabetes,
built on real CGMacros v1.0.0 data.

## 3. Problem statement

After a meal, glucose in people with prediabetes or type 2 diabetes can rise above 180 mg/dL, the
upper limit of the commonly used 70–180 mg/dL target range. How high it goes depends on the person
as much as on the meal: the same lunch can stay in range for one person and spike for another.

Continuous glucose monitors (CGMs) record what *already happened*. Clinicians reviewing CGM data
see the curves, but not:

- which meals are likely to push *this* person above range, before the outcome is known,
- *why* the risk is high (meal composition, current glucose, recent trend, personal history),
- how the estimate would change if the meal were different,
- how a person's response pattern has developed over time.

Population rules ("carbs are bad") ignore individual response. Generic ML scores are usually a
single number with no history, no personalization, no uncertainty and no provenance.

## 4. Healthcare use case

**User:** a clinician (diabetes educator, endocrinologist, primary care) reviewing a patient's
CGM, meal and wearable data, for example before or during a follow-up visit.

**Question it answers:** "Given everything known about this person up to this moment, how likely is
this meal to take them above 180 mg/dL within two hours, why, and what would a different meal look
like to the model?"

**Population:** prediabetes and type 2 diabetes (groups derived from baseline HbA1c, as defined by
the dataset). Healthy participants are evaluated separately and are not the primary population.

**Scope limits:** decision support for review and education. No medication, insulin, diagnosis or
treatment functionality, and no automated actions.

## 5. Solution overview

Glycemic Twin builds a **Digital Twin per patient**: a deterministic, versioned state of that person
at any moment `as_of`, made only from what was observable up to that moment.

- **Risk at each meal.** A calibrated probability that glucose exceeds 180 mg/dL within 120 minutes,
  from an XGBoost model trained with participant-level nested cross-validation.
- **Personal response.** The Twin learns from the person's own closed meal outcomes and moves
  through COLD_START → WARMING → PERSONALIZED as evidence accumulates.
- **Explainability and provenance.** Drivers of each estimate (SHAP-based), uncertainty flags, the
  exact model version, and hashes of the observations, configs and data that produced it.
- **Prediction → reality.** For past meals, the prediction made before the meal is shown next to
  the glucose that actually followed.
- **What-if.** Bounded, non-causal scenarios on the current meal's macronutrients and pre-meal
  activity, with the model's estimate, delta and uncertainty, and refusal outside training support.
- **Historical replay.** Step or play through a patient's recorded days and watch the Twin's state
  evolve, using only information available at each moment.
- **Clinician web app.** An interaction-first Next.js interface over a secure FastAPI + PostgreSQL
  backend.

## 6. Why a Digital Twin

A risk score answers one question once. A Digital Twin is a **living per-person model**: a state
that is built from the person's real data, updates as new data arrives, predicts, explains itself,
and can be queried with scenarios.

| Digital Twin property | How Glycemic Twin implements it |
|---|---|
| Mirrors one individual | one state per patient: clinical baseline, recent glucose and heart rate, meals, personal response |
| Updates over time | `build_state(patient, as_of)` recomputes the state at any moment; the lifecycle moves COLD_START → WARMING → PERSONALIZED |
| Respects time | nothing after `as_of` is visible; a meal outcome counts only once its 2-hour window has closed |
| Predicts | calibrated risk for the current meal |
| Can be queried | bounded what-if scenarios on the current meal |
| Is traceable | every state has a content hash, the model identity and the hashes of its inputs |

It is not a 3D avatar: nothing in the data describes anatomy. Like an engineering twin that mirrors
a turbine's *condition*, this Twin mirrors a person's *glycemic state and response behaviour*.

## 7. Technical stack

| Layer | Technology |
|---|---|
| Data and ML | Python 3.11, pandas, NumPy, PyArrow (Parquet), scikit-learn (logistic regression, calibration), XGBoost, SHAP values, uv workspace with a lock file |
| Digital Twin core | `twin_core`: a pure-Python package with no web or database dependencies, shared by training and serving |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic migrations, PostgreSQL 16, uvicorn |
| Security | Argon2id password hashing, server-side sessions (HttpOnly cookies), CSRF tokens, account lockout, roles, audit log, optional Google OIDC (PKCE) for pre-provisioned accounts |
| Frontend | Next.js 15 (App Router), React 19, TypeScript, TanStack Query, a custom CSS design system, hand-written SVG charts (no chart library) |
| Testing | pytest (370 tests, including property-based tests with Hypothesis), Vitest (105 tests), Playwright E2E with axe accessibility checks (51 tests) |
| Delivery | Docker (non-root images), Docker Compose, Caddy (HTTPS reverse proxy), GitHub Actions CI with amd64 image builds |

No LLMs, chatbots or external AI APIs are used.

## 8. AI/ML model details

All numbers below come from the generated reports in [`data/reports/`](data/reports/)
(`m1_audit.md`, `m2_dataset.md`, `m3_evaluation.md`). None are typed in by hand.

### Dataset

**CGMacros v1.0.0** (PhysioNet): free-living data, about 10 days per participant. It includes:
- Dexcom G6 Pro CGM, plus FreeStyle Libre Pro (not used for the model)
- Fitbit heart rate and activity
- logged meals with macronutrients
- baseline clinical labs

- 45 participants in the clinical file, 44 with time series (14 healthy, 16 prediabetes, 14 T2D).
- 1,663 logged meals.

### Target definition (frozen before training)

A meal is **positive** when Dexcom glucose exceeds **180 mg/dL** at any point in the **120 minutes**
after meal start. The meal must have no other meal within that window and at least 80% CGM coverage.

| Target group (prediabetes + T2D) | Participants | Meals | Positives | With ≥ 1 positive |
|---|---|---|---|---|
| Frozen usable cohort | 30 | 923 | 481 (52.1%) | 29 |
| Training/evaluation set (after exclusions) | 30 | **785** | **377 (48.0%)** | 29 |

Exclusions for training: no native CGM reading in the 15 minutes before the meal, glucose already
above 180 before the meal, and missing, invalid or inconsistent meal macros.

### Feature approach

There are 45 model inputs (the frozen contract `model_features.v1`), all computed from information
available **at or before meal start**:

| Group | Count | Inputs |
|---|---|---|
| Pre-meal glucose | 11 | last native reading and its age, 15/30-min slopes, 60-min variability, 3-hour mean/min/max, 24-hour time in range, overnight baseline and deviation from it |
| Meal | 11 | carbohydrate, protein, fat and fiber in grams, calories, meal type, time of day |
| Context | 3 | carbohydrates in the previous 3 hours, invalid meals in the previous 3 hours, minutes since the last meal |
| Wearable | 8 | heart rate (30 min, resting, difference), METs availability and level, active minutes, activity calories, age of the heart-rate reading |
| Clinical baseline | 9 | HbA1c, fasting glucose, fasting insulin, HOMA-IR, BMI, age, sex, triglycerides, HDL |
| Personal | 3 | shrinkage estimates of the person's own positive rate and glucose-rise offset, plus their weight, from earlier *closed* meals only |

Features use **native CGM readings only**, not the interpolated 1-minute values (ADR-009, ADR-013).

### Leakage prevention

- No post-meal information is used for the current meal. *Amount Consumed* is recorded after the
  meal, so it is never a feature.
- Automated checks run in M2, and all passed:
  - L1: feature names are valid
  - L2: 0 meals read data after their start
  - L3: features recomputed from history cut at meal start are identical
  - L4: folds are participant-disjoint
  - L5: no meal falls inside another usable meal's window
  - L6: no single feature is suspiciously predictive
- Personal priors are fitted per fold, on training participants only (ADR-014).
- In the Twin, the current meal's outcome can never enter the current state, and tests append
  future data to check that the state's hash does not change.

### Evaluation approach

- **Nested participant-level cross-validation** on 5 pinned, participant-disjoint folds (ADR-016).
  Every prediction reported is out-of-fold, for a participant the model never saw. Tuning,
  calibration, threshold choice and the personal prior also never saw that participant.
- Metrics: AUROC, PR-AUC (against the prevalence), Brier score, calibration slope and ECE.
  Participant-bootstrap 95% CIs, with a paired bootstrap for model comparisons.
- Four rule and simple baselines, plus ablations by modality.

### Models and results (target group, pooled out-of-fold, 785 meals)

| Model | AUROC [95% CI] | PR-AUC [95% CI] | Brier | Cal. slope |
|---|---|---|---|---|
| **XGBoost, full + personal (active)** | 0.804 [0.759, 0.845] | 0.808 [0.736, 0.870] | 0.179 | 1.00 |
| Logistic regression, full + personal | 0.814 [0.768, 0.852] | 0.807 [0.744, 0.860] | 0.175 | 0.97 |
| Best baseline (glucose + carbs rule) | 0.740 [0.699, 0.781] | 0.701 [0.616, 0.781] | 0.207 | 0.90 |

Prevalence is 0.480, so a random model's PR-AUC is about 0.48.

- **Model vs best baseline:** +0.107 PR-AUC [0.059, 0.158] and +0.064 AUROC [0.021, 0.107]
  (paired participant bootstrap).
- **XGBoost vs logistic: no meaningful difference.** ΔPR-AUC is +0.001 [−0.034, 0.038]. XGBoost is
  the active model, but it is **not** claimed to be superior.
- **Combining data types helps.** Full multimodal vs glucose-only gives +0.048 PR-AUC
  [0.010, 0.091]. Adding the personal prior gives +0.013 [−0.017, 0.041]; its interval includes 0.
- **At the threshold chosen on inner folds:** sensitivity 0.806, specificity 0.630, PPV 0.668,
  NPV 0.779.
- **Top SHAP drivers:** carbohydrate grams, last pre-meal glucose, protein, personal rise offset,
  3-hour glucose minimum, glucose variability, fiber, HbA1c. SHAP shows association, not cause.

### Limitations of the model

- Only about 30 target-group participants, so confidence intervals are wide. Results are for
  unseen participants (regime A); a temporal evaluation is future work.
- Labels use the frozen 1-minute Dexcom series and features use native readings. The effect of
  interpolation on labels is unmeasured (registered as sensitivity analysis SA-1).
- Everything is association: no output is a causal effect or a recommendation.

## 9. System architecture

Architecture diagram: [`IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf`](IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf)

```
CGMacros v1.0.0 (PhysioNet, not in git)
   │  M1  audit, cleaning, native CGM grid, frozen labels         (ml/, twin_core)
   │  M2  features, leakage checks, participant-disjoint folds
   │  M3  nested CV, calibration, SHAP, model bundles (SHA-256)
   ▼
twin_core  ── build_state(patient, as_of) · simulate() · diff_states()   (pure Python, shared by training and serving)
   ▼
FastAPI  /api/v1  ── auth · patients · twin · predictions · what-if · replay · admin
   ▼                                   ▲
PostgreSQL 16 (observations, model registry, states, sessions, audit)
   ▼
Next.js clinician app  ── patient list · Patient Twin · record · model page

Deployment: Caddy (HTTPS, one origin) → Next.js | FastAPI → PostgreSQL, via Docker Compose
```

## 10. Digital Twin workflow

1. **Cut at `as_of`.** Remove every observation after the moment the Twin is looking from.
2. **Close outcomes.** Only meals whose 120-minute window closed before `as_of` count as history.
3. **Compute inputs** with the same functions used in training (no train/serve skew): 42 meal,
   glucose, wearable and clinical features, plus 3 personal features from the prior stored in the
   model bundle.
4. **Predict** with the calibrated model bundle (SHA-256 checked on load).
5. **Produce a `TwinState`.** It is immutable and content-hashed, and holds:
   - lifecycle phase, risk and threshold, uncertainty flags
   - drivers, personal response and data freshness
   - provenance: input hashes, config hashes, model identity and engine version
6. **Query it:** `simulate()` for what-if, and `diff_states()` to explain what changed between two
   moments.

Lifecycle: **COLD_START** (no closed meals) → **WARMING** → **PERSONALIZED** (personal weight
≥ 0.5 and at least 3 closed meals). The phase only moves forward.

## 11. Frontend / clinician workflow

1. **Sign in** with username and password (or Google, only for accounts an admin has linked). The
   sign-in page has an interactive clinical-signal visual.
2. **Patient list:** each patient's glycemic group, data coverage and Twin phase.
3. **Patient Twin**, the main screen:
   - **Risk dial:** the calibrated risk with its threshold and uncertainty, and an explanation on demand.
   - **Measured glucose:** the current reading with its trend. Opening it shows the surrounding CGM
     context without losing your place.
   - **Glucose timeline:** a crosshair and tooltips over real readings, with meal markers. Hovering
     or tapping a meal links it to its glucose response, and past meals show
     **prediction → reality**.
   - **Why this risk:** the model drivers for this meal.
   - **Personal response:** what the Twin has learned from the person's history.
   - **Twin time rail:** move `as_of` through history and watch the state change.
   - **What-if** and **Historical replay** (below).
   - **Provenance:** the model version and hashes behind every number.
4. **Clinical record** (`/patients/[id]/record`) and the **model page** (`/model`), which shows the
   evaluation, calibration and limitations.

The interface is calm at rest and responds to interaction. It works with a keyboard and a screen
reader, supports reduced motion, and works on desktop, tablet and phone. Light, dark and system
themes are available.

## 12. Historical replay

Play, pause or step through a patient's recorded days. At each step the server rebuilds the Twin at
the new `as_of`, and the clinician sees risk, phase, meals and outcomes evolve.

- It is **historical replay of recorded data**, not live monitoring.
- At each step the Twin only uses information up to that moment.
- It is **not a held-out evaluation**. The serving model was refit on all participants after
  cross-validation; the held-out results are the out-of-fold numbers in section 8.

## 13. What-if scenarios

The clinician changes the current meal's carbohydrate, protein, fat or fiber, or pre-meal activity.
The interface then shows:
- the baseline next to the scenario
- the predicted risk moving to its new value
- the delta, and whether it crosses the threshold
- the uncertainty

Scenarios are:

- **Bounded:** each change has a maximum, and every changed input must stay within the training
  data's 1st–99th percentile. Otherwise the answer is "out of support", with no number.
- **Non-causal:** the result is what the model estimates, not what would happen to the person.
- **Never medical:** medication, insulin, diagnosis and treatment levers are refused.

## 14. Security and privacy

- Passwords: Argon2id, minimum 12 characters, lockout after 5 failures, no user enumeration.
- Sessions: server-side, 256-bit tokens stored hashed, HttpOnly + SameSite cookies (Secure in
  production), and a CSRF token on every state-changing request.
- Roles: clinician and admin. Accounts are created only by an admin, never from Google sign-in.
- Audit log: sign-ins, denials, model activation, user creation. It never stores passwords or tokens.
- Production rules are enforced at startup: secure cookies, trusted hosts, a complete Google
  configuration (or none), and documentation endpoints turned off.
- Errors and logs: generic error responses, request IDs, and JSON logs with secret redaction. No
  bodies, cookies or query strings are logged.
- Deployment: only the HTTPS proxy is public. PostgreSQL and the API are on an internal network,
  and the images run as non-root users.
- Data: de-identified research data only. Raw data, processed patient-level tables, model bundles
  and secrets are **not** in this repository.

Details: [`docs/security.md`](docs/security.md).

## 15. Dataset attribution and license

This project uses the **CGMacros v1.0.0** dataset. We do not own it, do not redistribute it, and do
not re-license it.

> Gutierrez-Osuna, R., Kerr, D., Mortazavi, B., & Das, A. (2025). *CGMacros: a scientific dataset for
> personalized nutrition and diet monitoring* (version 1.0.0). PhysioNet.
> https://doi.org/10.13026/3z8q-x658

- License: **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0)**.
- Source: https://physionet.org/content/cgmacros/1.0.0/ (also cite PhysioNet: Goldberger et al.,
  *Circulation* 2000).
- Derived files in this repository (the pinned fold manifest and aggregate reports) remain under
  CC BY-NC-SA 4.0. See [`NOTICE.md`](NOTICE.md) and [`docs/data-card.md`](docs/data-card.md).

## 16. Open-source license

- **Project source code: [MIT License](LICENSE)**, © 2026 Mitansh Mathur (Team IdeaForge,
  IIIT Allahabad).
- **CGMacros data and files derived from it: CC BY-NC-SA 4.0**, as published by its authors. The
  MIT license does not apply to them.
- Third-party dependencies keep their own licenses.

## 17. Demo video

**Video link:** _to be added by the team after recording_ (minimum 20 minutes).
Script: [`docs/demo-script.md`](docs/demo-script.md).

## 18. Architecture diagram

- PDF: [`IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf`](IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf)
- PowerPoint: [`IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pptx`](IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pptx)

## 19. Presentation

- PDF: [`IdeaForge_IIIT_ALLAHABAD/Presentation.pdf`](IdeaForge_IIIT_ALLAHABAD/Presentation.pdf)
- PowerPoint: [`IdeaForge_IIIT_ALLAHABAD/Presentation.pptx`](IdeaForge_IIIT_ALLAHABAD/Presentation.pptx)

## 20. Known limitations

- **Small cohort:** 30 target-group participants, about 10 days each, so confidence intervals are wide.
- **Evaluation regime:** the evaluation covers new participants only; temporal validation is future work.
- **Labels:** interpolation in the label basis is unmeasured (sensitivity analysis SA-1).
- **Association only:** what-if results and SHAP drivers are associations, not causal effects or
  recommendations.
- **What-if scope:** only current-meal macronutrients and pre-meal activity; no post-meal activity,
  medication or insulin.
- **Glycemic groups** are derived from baseline HbA1c; the dataset has no diagnosis field.
- **Replay:** historical replay only, with a serving model refit on all participants (not held-out).
- **Deployment:** the system runs locally with Docker Compose and has no public deployment yet. It
  has not been assessed for identifiable patient data. There is no per-IP rate limiting, no web
  content security policy and no MFA yet.
- **Regulatory:** not a medical device, not validated clinically, not for diagnosis or treatment.

## 21. How to run locally

Requirements: [uv](https://docs.astral.sh/uv/), Docker, Node 22, and the CGMacros download from
PhysioNet (for the real data).

```bash
# 1. Python dependencies and the tests (synthetic fixtures only; no data needed)
make setup
make lint typecheck test

# 2. Real-data pipeline (CGMacros downloaded to data/raw/, see data/raw/README.md)
make m1 SOURCE=/path/to/CGMacros_dateshifted365.zip SUMS=/path/to/SHA256SUMS.txt
make m2                       # features, labels, folds, leakage checks
make m3                       # nested CV, calibration, SHAP, model bundles

# 3. Backend
cp .env.example .env          # choose a local database password; TWIN_COOKIE_SECURE=false for http
make db-up                    # PostgreSQL 16 in Docker
make m5                       # migrate, ingest, support profile, register + activate the M3 model
make create-admin USER=you    # prompts for a password
make api                      # http://127.0.0.1:8000/api/v1/docs

# 4. Frontend
cd web && npm ci && npm run dev    # http://127.0.0.1:3000
```

**Whole stack in Docker** (Caddy + Next.js + FastAPI + PostgreSQL, https://localhost):

```bash
deploy/package-data.sh                       # processed artifacts + model bundles -> deploy/data (+ SHA256SUMS)
cd deploy && cp .env.example .env            # TWIN_PUBLIC_HOST=localhost, database password
docker compose up -d --build
docker compose exec api twin-api create-user you --role clinician
```

See [`docs/deployment.md`](docs/deployment.md).

**Checks:**
- **CI** (GitHub Actions, every pull request and push to `main`) runs the backend checks against
  PostgreSQL (lint, format, mypy, pytest; it fails if any test is skipped), the frontend checks on
  Node 22 (lint, typecheck, Vitest, build), and amd64 builds of both production images.
- **E2E:** `cd web && E2E_BASE_URL=... E2E_USER=... E2E_PASSWORD=... npm run e2e` runs locally
  against the real data.

## 22. Repository structure

```
packages/twin_core/       shared rules: configs, cleaning, native CGM grid, frozen labels, features,
                          personalization, and the Digital Twin engine (twin/)
ml/                       offline pipeline: M1 audit/cleaning, M2 features/labels/folds, M3 training/evaluation
api/                      FastAPI app, PostgreSQL schema + Alembic migrations, ingestion, model registry, auth
web/                      Next.js clinician app (src/), unit tests (tests/), Playwright E2E (e2e/)
deploy/                   Docker Compose stack, Caddyfile, data packaging script
data/configs/             frozen v1 configs: cleaning, labels, features, model features, training, twin
data/manifests/           pinned fold assignment and source checksums (derived from CGMacros)
data/reports/             generated M1/M2/M3 reports (aggregate results)
data/raw/, data/processed/  local only: never committed
docs/                     data card, decision records (ADRs), security, deployment, learning notes,
                          demo script, submission checklist
IdeaForge_IIIT_ALLAHABAD/ hackathon submission folder: presentation, architecture diagram, links
.github/workflows/        CI
```

Engineering history: M1 data audit → M2 features and leakage controls → M3 model training and
evaluation → M4 Digital Twin engine → M5 backend → M6 clinician app → M6.5 interaction design →
M7 delivery (portable artifacts, replay, production hardening, Docker, CI).
