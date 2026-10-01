# Notices

## Project source code

Copyright (c) 2026 Mitansh Mathur (Team IdeaForge, IIIT Allahabad). Licensed under the MIT License
(see [LICENSE](LICENSE)).

## CGMacros v1.0.0 (dataset)

This project uses, but does not own or redistribute, the CGMacros dataset:

> Gutierrez-Osuna, R., Kerr, D., Mortazavi, B., & Das, A. (2025). CGMacros: a scientific dataset for
> personalized nutrition and diet monitoring (version 1.0.0). PhysioNet.
> https://doi.org/10.13026/3z8q-x658

Please also cite the CGMacros paper and the standard PhysioNet citation:

> Goldberger, A., Amaral, L., Glass, L., Hausdorff, J., Ivanov, P. C., Mark, R., ... & Stanley, H. E.
> (2000). PhysioBank, PhysioToolkit, and PhysioNet: Components of a new research resource for complex
> physiologic signals. Circulation, 101(23), e215–e220.

- License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0),
  https://creativecommons.org/licenses/by-nc-sa/4.0/
- Source: https://physionet.org/content/cgmacros/1.0.0/
- The raw data is **not** in this repository; download it from PhysioNet (see `data/raw/README.md`).
- The data is de-identified research data (dates shifted by the publishers). This project does not
  re-license it, and it is not used for any commercial purpose.

Files in this repository that are **derived from CGMacros** and therefore remain under
CC BY-NC-SA 4.0 (changes: computed by this project's pipeline from the original files):

- `data/manifests/folds.v1.csv` (participant number, derived glycemic group, cross-validation fold)
- `data/manifests/cgmacros-1.0.0.lock.json` (file checksums of the source release)
- aggregate reports: `data/reports/*`, `audit_report.md`, `audit_results.json`,
  `data/reference/phase0a_audit_results.json`, and the generated block of `docs/data-card.md`
- application screenshots showing de-identified participant data: `docs/submission-src/img/*`,
  one participant's native CGM trace used in the slides (`docs/submission-src/data/cgm-example.js`),
  and
  the slides in `IdeaForge_IIIT_ALLAHABAD/Presentation.*`

Processed patient-level tables and trained model bundles are not published in this repository.

## Third-party software

Dependencies keep their own licenses (see `uv.lock` and `web/package-lock.json`).
