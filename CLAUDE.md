# Glycemic Twin — Project Instructions

## 1. PROJECT OVERVIEW

Glycemic Twin is a clinician-facing healthcare Digital Twin prototype focused on post-meal glycemic risk for people with prediabetes and Type 2 diabetes.

The system uses real CGMacros v1.0.0 data from PhysioNet, combining:
- CGM glucose
- logged meals/macros
- wearable activity/heart-rate data
- baseline clinical observations

The core product is a dynamic Digital Twin of an individual patient.

The Twin:
- combines static clinical information with historical/dynamic observations
- updates its state at a specified moment (`as_of`)
- predicts post-meal glycemic risk
- exposes model drivers/provenance
- supports bounded, non-causal what-if scenarios

This is a research prototype, not medical advice and not an autonomous diagnostic system.

---

## 2. CURRENT PROJECT STATUS

Completed:

- M1 — data audit / cleaning
- M2 — feature engineering, labels, leakage controls
- M3 — real ML training and evaluation
- M4 — Digital Twin engine and what-if system
- M5 — FastAPI + PostgreSQL + authentication + real ingestion
- M6 — clinician-facing Next.js frontend
- M6 auth refinement — session refresh fix, Google OAuth infrastructure, frontend auth polish
- M6 motion refinement — initial animations and transitions

Current phase:

- M6.5 — INTERACTIVE CLINICAL UX / MOTION PASS

M7 HAS NOT STARTED.

Do not start deployment/integration/submission work unless explicitly instructed.

---

## 3. CORE ARCHITECTURE

The project is a monorepo containing:

- Next.js frontend
- FastAPI backend
- PostgreSQL database
- pure-Python `twin_core`
- ML/training code
- data/audit artifacts
- infrastructure/docs/tests

Important architecture principle:

`twin_core` must remain independent of the web layer and database layer.

The Digital Twin state is generated through deterministic/versioned logic such as:

`build_state(patient, as_of)`

Training and serving must share the same core feature/state logic where applicable to minimize train/serve skew.

---

## 4. ML / DATA PRINCIPLES

Use real data only.

Never invent:
- patient observations
- glucose readings
- meals
- diagnoses
- medications
- clinical events
- model outputs

The main target is:

A meal is positive when glucose exceeds 180 mg/dL at any point within 120 minutes after meal start.

Primary target population:
- prediabetes
- Type 2 diabetes

Frozen target cohort:
- 923 usable meals
- 481 positive meals
- 29/30 participants with at least one positive meal

M1 eligibility for model training excludes:
- already-high pre-meal glucose
- unusable meal macros

Resulting eligible target training set:
- 785 meals
- 377 positives
- 29/30 participants with at least one positive

The main active model is currently XGBoost full-personal, but Logistic and XGBoost performed similarly in M3. Never claim XGBoost is materially superior unless new evidence demonstrates that.

Participant-disjoint evaluation/folds are important and must not be weakened.

Leakage prevention is a core project requirement.

Do not use post-meal information to predict the current meal outcome.

Amount Consumed is not a model feature because it introduces post-meal leakage.

Native CGM readings are used for model features.

Frozen labels were produced using the frozen 1-minute series for reproducibility.

---

## 5. DIGITAL TWIN PRINCIPLES

The Digital Twin is the centerpiece of the product.

Lifecycle includes:
- COLD_START
- WARMING
- PERSONALIZED

Personalization depends on closed meal history and learned personal response.

The current meal outcome must never leak into the current Twin state.

The Twin must respect the `as_of` boundary:
nothing after `as_of` is visible to the Twin.

What-if scenarios are:
- bounded
- non-causal
- model-based estimates
- explicitly uncertain

Supported what-if levers currently include relevant meal/macronutrient inputs and pre-meal activity where supported by the available data.

Do not introduce medication/insulin/treatment what-if functionality.

Do not present model output as medical advice or diagnosis.

Every important prediction/scenario should retain appropriate provenance, model/version information, uncertainty and context.

---

## 6. BACKEND / DATABASE / AUTH

Backend:
- FastAPI
- SQLAlchemy
- PostgreSQL
- Alembic migrations

Authentication currently supports:
- email/password
- session cookies
- CSRF protection
- clinician/admin roles
- lockout after repeated failed attempts
- audit logging

Google OIDC infrastructure exists but requires real Google credentials/configuration to activate it.

Google accounts must map to explicitly provisioned existing clinician accounts.

Never auto-create arbitrary clinician accounts from Google sign-in.

Do not expose Google access/ID tokens to the frontend.

Do not weaken existing authentication/security merely for visual polish.

---

## 7. FRONTEND

Frontend:
- Next.js App Router
- TypeScript
- custom clinical design system / CSS
- real FastAPI API
- no direct PostgreSQL access from browser

Important routes include:
- `/login`
- `/patients`
- `/patients/[id]`
- `/record`
- `/model`

The Patient Twin page is the signature screen.

Current application is intentionally clinician-facing.

It is NOT a backend-owner UI.

The frontend must continue using real backend/API data and must not substitute fake hardcoded patient data.

---

# 8. M6.5 — INTERACTION-FIRST DESIGN PHILOSOPHY

This is the CURRENT task.

The current UI is already:
- clean
- professional
- technically strong

but still feels too passive/static.

The goal is NOT simply:

"add more animations"

The goal is:

"turn the interface into a deeply interactive, premium clinical experience."

Core principle:

## CALM BY DEFAULT. ALIVE ON INTERACTION.

At rest:
- calm
- precise
- professional
- clinical
- trustworthy

When a user interacts:
- the interface responds
- data becomes explorable
- state transitions are visible
- interactions feel satisfying
- movement communicates meaning

The desired feeling is:

PREMIUM HEALTHCARE PRODUCT
+
INTERACTIVE CLINICAL INSTRUMENT

NOT:
- gaming UI
- flashy AI demo
- generic SaaS dashboard
- excessive animation
- random decoration

---

## 9. DESIGN REFERENCE / INTERACTION INSPIRATION

The user specifically referenced the GeekHaven IIITA website as an example of an interactive website experience.

Do NOT copy its visual style.

The important reference is its interaction philosophy:
- the site feels like something to explore
- motion contributes to storytelling
- user actions visibly affect the experience
- the interface has personality
- the experience is more than a collection of static sections

Apply that philosophy to healthcare.

Our interface should communicate the Digital Twin concept through interaction itself.

---

## 10. SIGN-IN PAGE

Do NOT use a literal doctor photograph.

The user wants an interactive, welcoming clinical opening experience.

The left side should feel alive rather than empty/static.

Possible visual language:
- elegant ECG/glucose waveform
- subtle clinical signal
- line-based medical geometry
- patient-data signal motif
- restrained stethoscope-inspired geometry

It must look like a product identity element, not clip-art.

Possible opening sequence:
1. background/grid establishes subtly
2. headline reveals/typing sequence
3. supporting text enters with stagger
4. clinical signal/waveform draws in
5. subtle signal movement/pulse
6. provenance/information panel enters
7. login panel settles naturally

Target roughly 1–1.5 seconds for initial composition.

Do not make it slow.

Pointer interaction can subtly affect the clinical visual:
- waveform response to pointer proximity
- small signal movement
- meaningful point hover
- subtle depth/parallax
- restrained click interaction

Do not make the whole page chase the cursor.

---

## 11. PATIENT TWIN — INTERACTION PRIORITY

The Patient Twin is the most important interface.

Major interactive areas:

### Risk gauge / probability

Current example:
12%

Desired behavior:
- number animates from 0 to current value
- gauge arc follows the value
- threshold state settles in
- subtle hover response
- contextual explanation can appear when explored

Do not use exaggerated bouncing.

### Measured glucose

Example:
97 mg/dL

The arrow/chevron beside the reading should be a meaningful interaction.

On hover:
- subtle directional movement
- reading area responds

On click:
- reveal richer surrounding CGM context
- preserve current page state
- allow graceful return

Never make it look like a dead decorative arrow.

### Glucose chart

This is a high-priority interaction.

Desired:
- smooth chart draw on entry
- interactive crosshair
- smooth tooltip following cursor
- readable time/value/trend
- meal markers
- hoverable meal context
- visual relationship between meal and glucose response

For example:
hover a meal marker:
- marker emphasizes
- meal details appear
- related chart area becomes easier to interpret

Never fabricate chart values.

Use real data.

### What-if

This should be one of the signature product moments.

When an input changes, do not simply replace a number.

Show:
baseline
→ changed input
→ prediction transition
→ trajectory morph
→ delta
→ uncertainty

The user should visually understand that changing the scenario changes the model output.

Keep existing non-causal/non-medical framing.

### Twin evolution

Moving through time/history should feel like the Twin itself is evolving:
- values transition
- timeline position moves
- relevant context changes
- model state changes coherently

---

## 12. MICRO-INTERACTIONS

Use meaningful micro-interactions for:
- buttons
- tabs
- arrows
- patient rows
- filters
- status pills
- expand/collapse controls
- tooltips
- navigation
- copyable values

Typical micro interaction duration:
~100–250ms

Use natural easing.

Avoid:
- giant hover scale
- excessive bounce
- generic card float effects everywhere
- animations with no semantic purpose

---

## 13. PAGE / STATE TRANSITIONS

Existing page transitions can remain.

They should be:
- fast
- coherent
- intentional

Avoid 2–3 second cinematic transitions that slow down clinical workflows.

When model/Twin state changes:
prefer smooth transition/morphing over abrupt replacement where practical.

The product should feel like state is evolving rather than components simply rerendering.

---

## 14. RESPONSIVE + ACCESSIBILITY

Everything must work on:
- desktop
- tablet
- phone

Do not depend exclusively on hover.

Touch interactions must remain understandable.

Maintain:
- keyboard navigation
- visible focus
- semantic HTML
- contrast
- screen-reader accessibility
- reduced-motion support

When `prefers-reduced-motion` is enabled:
- remove decorative animation
- retain necessary functional state changes
- do not hide information behind motion

---

## 15. PERFORMANCE

Prefer:
- CSS
- SVG
- lightweight React animation logic
- existing animation infrastructure

Avoid unnecessary:
- WebGL
- heavy canvas systems
- particle systems
- expensive effects

The interface must remain responsive.

---

## 16. NON-NEGOTIABLES

Never:
- invent healthcare data
- alter model labels casually
- weaken leakage prevention
- break the Digital Twin engine
- bypass security controls
- expose secrets
- silently change backend contracts
- replace real data with fake demo data
- introduce an LLM chatbot
- introduce external AI APIs
- add mobile apps
- add Apple Watch integration
- add Android Health Connect
- start M7

Do not rewrite working architecture unnecessarily.

Inspect the existing implementation before modifying it.

---

## 17. TESTING REQUIREMENTS

After changes, run appropriate:
- frontend lint
- TypeScript typecheck
- frontend tests
- backend tests if backend code changed
- E2E tests
- reduced-motion checks
- responsive checks

Verify:
- no console errors
- no horizontal overflow
- login still works
- session refresh still works
- Patient Twin still loads
- real data still renders
- what-if still works
- existing APIs remain compatible

---

## 18. DEVELOPMENT STYLE

Before changing code:
1. inspect the relevant existing implementation
2. understand the current architecture
3. make the smallest coherent change
4. preserve existing functionality
5. test after implementation

Do not work around permissions/security restrictions.

Do not fabricate success.

Report blockers clearly.

At the end of a task, report:
- what changed
- why
- files changed
- tests run
- failures/blockers
- remaining work

---

## 19. CURRENT PRIORITY

Current priority is:

M6.5 — INTERACTION-FIRST CLINICAL UX

The goal is NOT to increase animation quantity.

The goal is to make the product feel:

"Everything responds beautifully."

NOT:

"Everything is moving."

M7 is explicitly postponed until this interaction pass is complete.

## 20. LONG-TERM PURPOSE

This project has two connected purposes:

1. HACKATHON:
Build and submit a complete, credible Glycemic Digital Twin prototype for the current hackathon. The hackathon version should remain focused and defensible rather than becoming an unfinished collection of extra features.

2. PLACEMENT / RESUME:
This is intended to become the user's flagship long-term engineering project for internships and placements.

The goal is not merely to have a visually impressive demo. The user must eventually understand and be able to explain:
- data pipeline
- preprocessing
- leakage prevention
- feature engineering
- ML evaluation
- model selection
- Digital Twin architecture
- backend/API
- PostgreSQL/database design
- authentication/security
- frontend architecture
- deployment/DevOps
- testing
- system design decisions

After the hackathon, the project may evolve into a larger patient-to-clinician healthcare platform, but that expansion is POST-HACKATHON and must not distract from completing the current submission.

When making engineering decisions, favor:
- real functionality
- explainability
- maintainability
- interview-defensible architecture
- strong engineering fundamentals

Avoid adding technology merely to make the resume longer.