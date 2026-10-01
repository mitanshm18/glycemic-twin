# IdeaForge_IIIT_ALLAHABAD: hackathon submission

| | |
|---|---|
| **Team name** | IdeaForge |
| **Team leader** | Mitansh Mathur |
| **College** | IIIT Allahabad |
| **Project** | Glycemic Twin: a clinician-facing Digital Twin for post-meal glycemic risk |
| **Public repository** | https://github.com/mitanshm18/glycemic-twin |

## Contents of this folder

| File | What it is |
|---|---|
| [`Presentation.pdf`](Presentation.pdf) | 22-slide presentation (primary, text-searchable) |
| [`Presentation.pptx`](Presentation.pptx) | the same slides in PowerPoint format |
| [`Architecture_Diagram.pdf`](Architecture_Diagram.pdf) | system architecture diagram (primary) |
| [`Architecture_Diagram.pptx`](Architecture_Diagram.pptx) | the same diagram in PowerPoint format |
| [`LINKS.md`](LINKS.md) | repository, demo video and documentation links |
| [`LICENSE_AND_DATA.md`](LICENSE_AND_DATA.md) | code license (MIT) and dataset attribution (CGMacros, CC BY-NC-SA 4.0) |

## The project in one paragraph

Glycemic Twin builds a per-patient Digital Twin from real CGMacros v1.0.0 data (CGM, meals,
wearable and baseline clinical data). At any moment `as_of`, using only what was observable up to
that moment, it estimates the risk that the current meal takes glucose above 180 mg/dL within 120
minutes, explains the estimate, learns from the person's own closed meals (COLD_START → WARMING →
PERSONALIZED), and supports bounded, non-causal what-if scenarios and historical replay. On unseen
participants (nested participant-level cross-validation, 785 target-group meals), the active
XGBoost model reaches PR-AUC 0.808 [0.736, 0.870] and AUROC 0.804 [0.759, 0.845], against 0.701
for the best simple baseline. Logistic regression performs equivalently.

**Research prototype:** not a medical device, not medical advice, not clinically deployed.
Historical replay is not live monitoring.

The full technical README, source code, tests and documentation are in the repository root.
