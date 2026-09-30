# ADR-014: Personal features use population priors fitted inside each training fold

- Status: accepted (M2)
- Date: 2026-09-29

## Decision

The M2 dataset stores only raw, past-only personal counts (`n_closed_meals`, `n_closed_positive`) and
the outcome columns a later step needs (`label`, `frozen_usable`, `rise_native_mgdl`, carbs, fiber,
pre-meal glucose). The personal estimates (shrunk positive rate, shrunk rise offset, personalization
weight) are computed in M3, inside each cross-validation fold:

1. `fit_population_prior(training participants only)` estimates the beta-binomial prior (α, β), the
   population rise model, and the shrinkage constant k.
2. `personal_features(person, prior)` computes, for each meal, estimates from that person's closed
   past meals only.

Folds are assigned per participant, stratified by glycemic group (5 folds, seed 20261001), and pinned
in `data/manifests/folds.v1.csv` before any training.

## Context

Personalization needs population values: a new person starts at the population rate. If those values
were estimated from all 44 participants, a test participant's own outcomes would help set the prior
used to predict them, which is a subtle leak across folds.

## Alternatives

- **Compute personal features once in M2 with a global prior.** Simple, but it leaks test participants'
  outcomes into the prior.
- **Use raw personal rates without shrinkage.** No prior needed, but a person with 2 meals would get a
  rate of 0% or 100%, which is noisy and overconfident.
- **Fit priors per fold (chosen).** Correct, and cheap: fitting takes milliseconds.

## Consequences

- M3 must call the prior fit inside the fold loop; a test asserts that it never sees test-fold
  participants.
- Within a training fold, a training meal's own label contributes (very slightly) to the prior that
  also shapes its personal feature. That affects only how the model is fitted, never the test
  evaluation, and is standard practice.
- A new person at serving time starts in cold start: p_personal equals the population rate and the
  weight is 0.
