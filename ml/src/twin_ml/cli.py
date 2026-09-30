"""Command line.

twin-ml m1 --source <zip|folder> [--official-sums SHA256SUMS.txt]   data foundation (read-only source)
twin-ml m2                                                          features + labels + leakage checks
twin-ml m3                                                          nested CV, calibration, OOF, SHAP, bundles
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _m1(args: argparse.Namespace) -> int:
    from twin_ml.pipeline.run import run_m1

    result = run_m1(args.source, args.root, args.official_sums)
    audit = result.audit
    o = audit["outcomes"]
    print(f"participants with time series: {audit['participants']['timeseries_files']}")
    print(
        f"meal rows: {audit['meals']['meal_rows']}; frozen usable: {o['frozen_usable']}; "
        f"positives: {o['frozen_positives']}"
    )
    for key in ("target_frozen", "target_eligible"):
        t = o[key]
        print(
            f"{key}: {t['usable_meals']} meals, {t['positives']} positives "
            f"({t['positive_rate']}), {t['participants_with_positive']}/{t['participants']} "
            f"with a positive -> viability {'PASS' if t['viability_pass'] else 'FAIL'}"
        )
    for issue in audit["issues"]:
        print(f"[{issue['level']}] {issue['issue']}")
    print(
        "wrote data/reports/m1_audit.md, data/reports/m1_audit.json, data/processed/m1/, "
        "and refreshed docs/data-card.md"
    )
    return 1 if any(i["level"] == "blocking" for i in audit["issues"]) else 0


def _m2(args: argparse.Namespace) -> int:
    from twin_ml.dataset.run import load_m1_tables, run_m2, summary_lines

    result = run_m2(load_m1_tables(args.root), args.root)
    for line in summary_lines(result.report):
        print(line)
    print(
        "wrote data/processed/m2/dataset.parquet, data/reports/m2_dataset.md, "
        "data/manifests/folds.v1.csv"
    )
    return 1 if result.report["issues"] else 0


def _m3(args: argparse.Namespace) -> int:
    from twin_ml.training.run import load_m2_dataset, run_m3

    result = run_m3(load_m2_dataset(args.root), args.root)
    r = result.report
    c = r["counts"]
    print(f"data: {r['dataset_label']}")
    print(
        f"eligible target meals: {c['eligible_target_meals']} ({c['eligible_target_positives']} "
        f"positive, {c['target_participants']} participants); healthy meals: "
        f"{c['eligible_healthy_meals']}"
    )
    for rid, run in r["runs"].items():
        p = run["target"].get("pooled", {})
        print(
            f"{rid:40s} target PR-AUC {p.get('pr_auc')!s:.5} AUROC {p.get('auroc')!s:.5} "
            f"Brier {p.get('brier')!s:.5}"
        )
    for cmp in r["comparisons"]:
        if cmp["ran"]:
            d = cmp["pr_auc"]
            print(
                f"{cmp['comparison']}: dPR-AUC {d['difference']:.3f} [{d['lo']:.3f}, {d['hi']:.3f}]"
            )
    print(
        "wrote data/reports/m3_evaluation.md, data/processed/m3/oof_predictions.parquet, "
        "data/processed/m3/shap_oof.parquet, data/processed/m3/models/"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="twin-ml")
    sub = parser.add_subparsers(dest="command", required=True)
    m1 = sub.add_parser("m1", help="verify, clean and audit CGMacros (read-only on the source)")
    m1.add_argument("--source", type=Path, required=True, help="CGMacros ZIP or extracted folder")
    m1.add_argument("--official-sums", type=Path, default=None, help="PhysioNet SHA256SUMS.txt")
    m1.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    m2 = sub.add_parser("m2", help="build features, labels, folds; run leakage checks")
    m2.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    m3 = sub.add_parser("m3", help="train and evaluate models with nested participant-level CV")
    m3.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)
    return {"m1": _m1, "m2": _m2, "m3": _m3}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
