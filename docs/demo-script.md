# Glycemic Twin: demo video script (about 24 minutes)

**Team IdeaForge · IIIT Allahabad · Team leader: Mitansh Mathur**

This is a speaking script for the recorded walkthrough. The hackathon asks for at least 20 minutes;
the timings below add up to about 24, so there is room to trim without dropping under 20. Every
number quoted here comes from `data/reports/` (M1, M2, M3) or from the test runs. Do not round them
up or add new claims while recording.

**Before recording**

- Start the local stack with real data: `cd deploy && docker compose up -d`, then open
  https://localhost. You can also use the development servers (`make api` and `npm run dev`).
- Sign in once in a private window to check the account works, then sign out.
- Pick the patients to show, and note their IDs so you don't search on camera:
  - one with several closed meals (Twin phase PERSONALIZED)
  - one early in their data (COLD_START or WARMING), for the time rail and replay
- Keep these files open in tabs:
  - [`IdeaForge_IIIT_ALLAHABAD/Presentation.pdf`](../IdeaForge_IIIT_ALLAHABAD/Presentation.pdf)
  - [`IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf`](../IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf)
  - [`data/reports/m3_evaluation.md`](../data/reports/m3_evaluation.md)
  - the GitHub repository page
- Screen: 1920×1080, browser zoom 100%, notifications off. Light theme reads best on video.
- Never show `.env` files, passwords or terminal history containing credentials.

| # | Section | Time | Show |
|---|---|---|---|
| 1 | Opening and team | 0:00–1:00 | Title slide |
| 2 | The problem | 1:00–3:00 | Slides 3–5 |
| 3 | Why a Digital Twin | 3:00–4:30 | Slide 6 |
| 4 | Real dataset | 4:30–6:30 | Slide 7, data card |
| 5 | Data pipeline and leakage prevention | 6:30–9:30 | Slides 8–10 |
| 6 | Model results, honestly | 9:30–12:00 | Slide 11, M3 report |
| 7 | Digital Twin architecture | 12:00–14:00 | Slide 12, architecture PDF |
| 8 | Live: sign-in and patient list | 14:00–15:00 | App |
| 9 | Live: the Patient Twin | 15:00–18:30 | App |
| 10 | Live: what-if | 18:30–20:30 | App |
| 11 | Live: Twin time rail and historical replay | 20:30–22:00 | App |
| 12 | Security, engineering and quality | 22:00–23:00 | Slides 17–18, GitHub Actions |
| 13 | Limitations, outcome, close | 23:00–24:30 | Slides 19–22 |

---

## 1. Opening and team (0:00–1:00)

> "Hi, I'm Mitansh Mathur, team leader of **IdeaForge** from **IIIT Allahabad**. Our project is
> **Glycemic Twin**: a clinician-facing Digital Twin that estimates, at each meal, the risk that a
> person with prediabetes or type 2 diabetes will go above 180 milligrams per decilitre within the
> next two hours.
>
> Everything you'll see runs on **real, open data**, the CGMacros dataset from PhysioNet. It's a
> **research prototype**. It is not a medical device and it doesn't give medical advice. I'll be
> careful to say exactly what the model can and cannot claim."

## 2. The problem (1:00–3:00)

> "After a meal, glucose rises. For people with prediabetes or type 2 diabetes it often rises above
> 180, the upper end of the usual 70-to-180 target range. Repeated post-meal spikes matter clinically.
>
> The difficulty is that the response is **personal**. The same lunch can stay in range for one
> person and spike for another. It depends on what they ate, their glucose before the meal and its
> trend, their activity, their metabolic baseline, and how their body has responded before.
>
> A continuous glucose monitor records what *already happened*. When a clinician reviews CGM data,
> they see the curves, but not which meals were likely to spike *before* the outcome was known, or
> *why*, or what a different meal would have looked like, or how this person's pattern developed.
>
> Population rules like 'fewer carbs' ignore the individual. A typical ML risk score is one number,
> with no history, no personalization, no uncertainty and no way to trace where it came from."

Point at slide 5 (why current approaches are insufficient) and name the gaps: static, population-level,
unexplained, untraceable.

## 3. Why a Digital Twin (3:00–4:30)

> "Our answer is a **Digital Twin per patient**. A risk score answers one question once. A twin is a
> living per-person model: a *state* built from that person's real data, which updates as new data
> arrives, predicts, explains itself, and can be asked 'what if' questions.
>
> The core function is `build_state(patient, as_of)`. Given a patient and a moment in time, it
> builds the twin from everything observable **up to that moment and nothing after it**. That
> boundary is what makes it honest.
>
> It isn't a 3D avatar. Nothing in our data describes anatomy, so a body model would be decoration.
> Like an engineering twin that mirrors a turbine's *condition*, ours mirrors a person's *glycemic
> state and response behaviour*."

Mention the lifecycle: **COLD_START** (no closed meals yet), **WARMING**, **PERSONALIZED** (the
person's own evidence outweighs the population prior, with at least 3 closed meals).

## 4. Real dataset (4:30–6:30)

> "The data is **CGMacros version 1.0.0** from PhysioNet, published by Gutierrez-Osuna, Kerr,
> Mortazavi and Das, under CC BY-NC-SA 4.0. We cite it, and we don't own or redistribute it.
>
> It's free-living data, about ten days per participant:
> - Dexcom G6 CGM readings every five minutes
> - Fitbit heart rate and activity
> - every logged meal with its carbohydrate, protein, fat and fiber
> - baseline labs like HbA1c and fasting glucose
>
> 44 participants have time series: 14 healthy, 16 prediabetes and 14 type 2 diabetes. The groups
> are derived from baseline HbA1c, because the dataset has no diagnosis field. There are 1,663
> logged meals.
>
> Our primary population is prediabetes plus type 2 diabetes: 30 participants. With the frozen
> definition, that's 923 usable meals, and 481 of them went above 180. 29 of the 30 have at least
> one positive meal."

Optionally open `docs/data-card.md` and show the "Known issues" table. Point out:
- interpolated CGM minute values
- implausible macros
- the "Amount Consumed" field, which is recorded *after* the meal

## 5. Data pipeline and leakage prevention (6:30–9:30)

> "We built this in milestones, and each one leaves an auditable report.
>
> **M1, the data audit.**
> - We checksum the source release and apply versioned cleaning rules.
> - The 1-minute CGM values in the files are mostly interpolated, so we detect the **native** sensor
>   readings and build features only from those.
> - We freeze the label: a meal is positive if Dexcom glucose exceeds 180 at any point in the 120
>   minutes after meal start. The meal must have no other meal inside that window and at least 80
>   percent CGM coverage.
>
> **M2, features and labels.**
> - Every model gets exactly 45 inputs from a frozen contract.
> - Pre-meal glucose: the last reading, slopes, variability, the 3-hour level and range, and the
>   overnight baseline.
> - The meal's macros and calories, meal type and time of day.
> - Recent context, heart rate and activity, and baseline clinical values.
> - Three personal features that summarize how this person's past meals turned out.
>
> For training, we also exclude meals that were already above 180 before eating, and meals with
> broken macro data. That leaves **785 meals, 377 positive**."

Then leakage, the part judges should remember:

> "The biggest risk in this kind of project is **leakage**: accidentally letting the model see the
> answer.
> - Nothing after meal start is used to predict that meal. 'Amount Consumed' is recorded after the
>   meal, so it is never a feature.
> - M2 runs automated checks, and all of them passed:
>   - zero meals read data after their start time
>   - recomputing features from history cut at meal start gives identical values
>   - folds are participant-disjoint
>   - no meal sits inside another meal's window
>   - no single feature is suspiciously predictive
> - The personal features use a population prior fitted **per fold, on training participants
>   only**. A meal's own outcome can never feed its own personal features.
>
> In the twin, tests append wildly different future data and check that the state's hash doesn't
> change."

## 6. Model results, honestly (9:30–12:00)

Open slide 11 or `data/reports/m3_evaluation.md`.

> "Evaluation uses **nested participant-level cross-validation** on five pinned folds. Every number
> here is *out-of-fold*: the meal was predicted by a model whose training, tuning, calibration,
> threshold and personal prior never saw that person. So these are results for **new patients**.
>
> On 785 target-group meals, the active **XGBoost model reaches PR-AUC 0.808** (95% CI 0.736 to
> 0.870) and **AUROC 0.804** (0.759 to 0.845). It's well calibrated, with a slope of 1.00. Prevalence
> is 0.48, so a random model would get a PR-AUC of about 0.48.
>
> The best simple baseline, a rule on pre-meal glucose and carbs, gets PR-AUC 0.701. In a paired
> participant bootstrap, the model improves on it by **0.107 PR-AUC**, with a confidence interval of
> 0.059 to 0.158.
>
> One thing I want to be honest about: **logistic regression did just as well**, PR-AUC 0.807. The
> difference from XGBoost is 0.001, and the confidence interval spans zero. We serve XGBoost, but we
> don't claim it's better.
>
> Combining data types clearly helps: full multimodal beats glucose-only by 0.048 PR-AUC. The
> personal prior adds a little, +0.013, but its interval includes zero, so we report it as
> 'not proven'.
>
> At the threshold chosen inside the training folds, sensitivity is 0.81 and specificity 0.63.
>
> The SHAP drivers make clinical sense: carbohydrate grams, the last pre-meal glucose, protein, the
> person's own rise offset, recent glucose minimum and variability, fiber, HbA1c. These are
> associations, not causes."

## 7. Digital Twin architecture (12:00–14:00)

Show `Architecture_Diagram.pdf`.

> "Here's how it fits together.
> - **Left, offline:** the real data goes through M1, M2 and M3. The output is a model bundle with a
>   SHA-256 checksum.
> - **Centre, the core:** `twin_core`, a pure Python package with no web or database code. Training
>   and serving use the same feature and personalization functions, so there's no train/serve skew.
>   A test rebuilds all 45 inputs through the twin and checks they match the training data exactly.
> - **`build_state`** cuts at `as_of`, closes past outcomes, computes the inputs, predicts with the
>   calibrated bundle, and returns an immutable, content-hashed state. That state carries its
>   provenance: hashes of the inputs and configs, and the exact model identity.
> - **`simulate`** runs what-if scenarios, and **`diff_states`** explains what changed between two
>   moments.
> - **Right, serving:** FastAPI with PostgreSQL and Alembic migrations, and a Next.js clinician app
>   on top.
> - **Bottom, deployment:** Docker Compose with Caddy as the single HTTPS entry point. Only Caddy is
>   public."

## 8. Live: sign-in and patient list (14:00–15:00)

Switch to the browser at the sign-in page.

> "The sign-in page uses a live clinical signal visual. It reacts subtly to the pointer, but it's
> calm, because this is a clinical tool.
>
> Passwords are hashed with Argon2id. Sessions are server-side and protected against CSRF, and
> accounts lock after repeated failures. Google sign-in exists, but only for accounts an admin has
> already created. No account is ever created from Google."

Sign in (type the password off-camera or with the field masked). On the patient list:

> "Each patient shows their glycemic group, data coverage and where their twin is in its lifecycle."

Hover a row to show the response, then open the prepared PERSONALIZED patient.

## 9. Live: the Patient Twin (15:00–18:30)

Take it slowly. This is the main screen.

1. **Risk dial.**
   > "This is the twin's risk for the current meal. It counts up to the calibrated probability and
   > settles against the decision threshold. The uncertainty level is shown next to it."

   Hover or click to open the explanation.
2. **Measured glucose.**
   > "The latest measured glucose, with its trend."

   Click the chevron.
   > "This opens the surrounding CGM context without losing my place. Close it and I'm back where I was."
3. **Glucose chart.** Move the crosshair across it.
   > "Every point is a real CGM reading. The tooltip follows the cursor with time, value and trend.
   > The green band is the 70-to-180 target range."
4. **Meal markers.** Hover or tap one.
   > "The marker highlights, the meal's macros appear, and the 2-hour window after it is emphasized,
   > so you can see the meal and the glucose response together."
5. **Prediction → reality.** Pick a past meal.
   > "For past meals we can compare what the twin predicted *before* the meal with what actually
   > happened. Predicted and measured values use different colours and line styles."
6. **Why this risk.**
   > "These are the model drivers for this meal, the features that pushed the risk up or down."
7. **Personal response.**
   > "What the twin has learned from this person's own closed meals: their personal positive rate
   > and rise offset, and how much weight their own data now gets."
8. **Provenance.**
   > "Every number is traceable: the model version, the feature contract, the data and config
   > hashes, and the exact moment the state was built from."

## 10. Live: what-if (18:30–20:30)

> "Now the question a clinician actually asks: what if this meal were different?"

Reduce carbohydrates by about 30 g:

> "Watch what happens. The baseline stays visible. The lever shows it's calculating while the model
> answers. Then the risk moves to the new value, the probability morphs, and we see the **delta** and
> whether it crosses the threshold, with its uncertainty."

Then try a change that is too large, or outside training support:

> "If a scenario goes outside the range the model was trained on, it refuses to give a number and
> says 'out of support'. It doesn't extrapolate."

State the framing clearly:

> "These scenarios are **bounded and non-causal**. They show what the model estimates, not what
> would happen to the patient. Only the current meal's macros and pre-meal activity can be changed.
> Medication, insulin, diagnosis and treatment levers are refused by design."

## 11. Live: Twin time rail and historical replay (20:30–22:00)

Open the early-data patient.

> "The **time rail** moves the twin's `as_of` through the patient's history. Watch the state evolve:
> risk changes, and closed meals become personal evidence. The lifecycle moves from COLD_START to
> WARMING to PERSONALIZED."

Start **Historical replay**, play a few steps, pause, and step once.

> "At every step the server rebuilds the twin at the new moment, using only information available
> then.
>
> Two honest caveats. This is **historical replay** of recorded data, not live monitoring. And it's
> **not a held-out evaluation**: the serving model was refit on all participants after
> cross-validation. The held-out results are the out-of-fold numbers I showed earlier."

Optionally, resize to phone width or show the reduced-motion setting, to show the layout adapts and
nothing depends on hover.

## 12. Security, engineering and quality (22:00–23:00)

> "On the engineering side:
> - **Security:** production settings are checked at startup (secure cookies, trusted hosts, a
>   complete Google configuration or none). Errors are generic, logs are JSON with secret
>   redaction, and images run as non-root users.
> - **Network:** PostgreSQL and the API are never exposed; only Caddy is.
> - **Repository:** no raw data, processed patient tables, model bundles or secrets are in it.
> - **Tests:** 370 backend tests, including real PostgreSQL migrations; 105 frontend unit tests;
>   and 51 Playwright end-to-end tests with axe accessibility checks, reduced motion and mobile.
> - **CI:** GitHub Actions runs on every pull request and builds both production images for amd64."

Show the green CI run on GitHub.

## 13. Limitations, outcome, close (23:00–24:30)

> "Limitations, plainly:
> - The cohort is small, about 30 target participants over ten days, so confidence intervals are
>   wide.
> - We evaluated on new participants; temporal validation is future work.
> - Everything is association, not causation.
> - The what-if levers are limited to meal macros and pre-meal activity.
> - It is not clinically validated, and it's not a medical device.
>
> What we delivered:
> - an end-to-end, reproducible system from raw open data to a clinician interface
> - a Digital Twin with an honest time boundary, personalization, provenance, what-if and replay
> - a model that beats simple baselines on new patients
> - security and testing taken seriously
>
> Future work: temporal validation, external datasets, clinician usability studies, and a carefully
> scoped patient-facing view.
>
> Thank you. The code is on GitHub under the MIT license, and the CGMacros data remains under its
> original CC BY-NC-SA license. I'm Mitansh Mathur from team IdeaForge, IIIT Allahabad."

---

**After recording**

- Upload the video and set it to **public** or **unlisted**, so anyone with the link can view it.
- Open the link in a private window to confirm it plays without signing in.
- Paste the link into `README.md` (section 17), `IdeaForge_IIIT_ALLAHABAD/LINKS.md` and
  `docs/hackathon-submission-checklist.md`.
- Check that the video length shows **20:00 or more**.
