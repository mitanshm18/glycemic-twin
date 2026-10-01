# Hackathon submission checklist

**Team IdeaForge · IIIT Allahabad · Team leader: Mitansh Mathur · Project: Glycemic Twin**

Status key: ✅ done and verified · ⏳ needs Mitansh (manual) · 🔁 done once the submission branch is
merged into `main`

The repository links below point at `main`. They resolve after the `submission` branch is merged.

## Requirements → where each is satisfied

| # | Requirement | Satisfied by | Status |
|---|---|---|---|
| 1 | Public GitHub repository | https://github.com/mitanshm18/glycemic-twin (visibility: public, confirmed through the GitHub API) | ✅ |
| 2 | Team details (team name, leader) | [README §1](../README.md#1-team-details), [`IdeaForge_IIIT_ALLAHABAD/README.md`](../IdeaForge_IIIT_ALLAHABAD/README.md), slides 1–2 | 🔁 |
| 3 | College | same as above: IIIT Allahabad | 🔁 |
| 4 | Project title | [README §2](../README.md#2-project-title), slide 1 | 🔁 |
| 5 | Problem statement | [README §3](../README.md#3-problem-statement), slides 3 and 5 | 🔁 |
| 6 | Healthcare use case | [README §4](../README.md#4-healthcare-use-case), slide 4 | 🔁 |
| 7 | Technical stack | [README §7](../README.md#7-technical-stack), slide 18, architecture diagram | 🔁 |
| 8 | AI/ML model and framework details | [README §8](../README.md#8-aiml-model-details) (dataset, target, features, leakage, evaluation, models, results, limitations); slides 7–11; generated source [`data/reports/m3_evaluation.md`](../data/reports/m3_evaluation.md) | 🔁 |
| 9 | Demo video, at least 20 minutes | script: [`docs/demo-script.md`](demo-script.md) (about 24 min). **The video itself is not recorded yet.** Add its link to README §17 and [`IdeaForge_IIIT_ALLAHABAD/LINKS.md`](../IdeaForge_IIIT_ALLAHABAD/LINKS.md). | ⏳ |
| 10 | Open-source license details | [`LICENSE`](../LICENSE) (MIT, code), [`NOTICE.md`](../NOTICE.md) (CGMacros CC BY-NC-SA 4.0 attribution), [README §15–16](../README.md#15-dataset-attribution-and-license), [`IdeaForge_IIIT_ALLAHABAD/LICENSE_AND_DATA.md`](../IdeaForge_IIIT_ALLAHABAD/LICENSE_AND_DATA.md) | 🔁 |
| 11 | Architecture diagram (PDF/PPT) | [`IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf`](../IdeaForge_IIIT_ALLAHABAD/Architecture_Diagram.pdf) and `.pptx` | 🔁 |
| 12 | Presentation (PDF/PPT) | [`IdeaForge_IIIT_ALLAHABAD/Presentation.pdf`](../IdeaForge_IIIT_ALLAHABAD/Presentation.pdf) (22 slides) and `.pptx` | 🔁 |
| 13 | Folder name `IdeaForge_IIIT_ALLAHABAD` | [`IdeaForge_IIIT_ALLAHABAD/`](../IdeaForge_IIIT_ALLAHABAD/) at the repository root (about 8 MB: no data, models or secrets) | 🔁 |
| 14 | Public accessibility of files and links | The repository is public; every file is in it. **Check the video link opens in a private window without signing in.** | 🔁 / ⏳ (video) |
| 15 | Submission platform fields | team leader name: **Mitansh Mathur**; phone: **(Mitansh enters)**; email: **(Mitansh enters)**; public repository: **https://github.com/mitanshm18/glycemic-twin** | ⏳ |

## Verification done for the submission state

| Check | Result |
|---|---|
| Backend: ruff, ruff format, mypy | passed |
| Backend: pytest with PostgreSQL (incl. migrations and schema) | **370 passed, 0 skipped** |
| Frontend on Node 22: lint, typecheck, Vitest, production build | passed; **105/105** tests |
| GitHub Actions CI on `main` (backend, frontend, linux/amd64 API and web images) | green |
| Full stack (Caddy, Next.js, FastAPI, PostgreSQL, real data, active M3 model) | `/api/v1/ready`: ready, migrations at head, model compatible |
| Brand-new database: migrate → ingest → support profile → register and activate model | succeeded |
| Playwright E2E against the real stack (desktop light, desktop dark, mobile) | **51/51 passed** |
| Repository audit (secrets, `.env`, credentials, raw/processed data, model bundles, `.claude`, local Playwright configs, `.m6-transfer`) | none tracked; real local passwords found 0 times in all history |

## Before pressing submit (Mitansh)

1. Merge the `submission` branch into `main`, so the README, LICENSE and the folder are on the
   default branch.
2. Record the demo video (at least 20 minutes) following [`docs/demo-script.md`](demo-script.md),
   and upload it as public or unlisted.
3. Paste the video link into README §17 and `IdeaForge_IIIT_ALLAHABAD/LINKS.md`, then commit.
4. Open the repository, the presentation PDF, the architecture PDF and the video link in a private
   browser window to confirm they're publicly accessible.
5. On the submission platform, enter your name, phone, email and the repository link.
