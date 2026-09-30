#!/usr/bin/env bash
# Collect exactly the processed artifacts the stack needs into one folder, readable by the
# containers, with a checksum list. Run from the repository root after `make m1 m2 m3`:
#   deploy/package-data.sh [OUT_DIR]        (default: deploy/data)
# Copy OUT_DIR to the server and point TWIN_DATA_DIR at it. Nothing here is modified or retrained.
set -euo pipefail
SRC=data/processed
OUT=${1:-deploy/data}
FILES=(
  m1/run_manifest.json m1/cgm.parquet m1/wearable.parquet m1/meals.parquet m1/meal_outcomes.parquet
  m1/clinical_long.parquet m1/clinical_wide.parquet
  m2/run_manifest.json m2/dataset.parquet
  m3/models/xgboost__full_personal.joblib m3/models/xgboost__full_personal.json
  m3/models/logistic__full_personal.joblib m3/models/logistic__full_personal.json
)
for f in "${FILES[@]}"; do
  [ -f "$SRC/$f" ] || { echo "missing $SRC/$f (run the M1-M3 pipeline first)" >&2; exit 1; }
done
rm -rf "$OUT"
for f in "${FILES[@]}"; do
  mkdir -p "$OUT/$(dirname "$f")"
  cp "$SRC/$f" "$OUT/$f"
done
mkdir -p "$OUT/m5"  # the init job writes the training-support profile here (a volume in compose)
chmod -R a+rX "$OUT"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS)
echo "packaged $(find "$OUT" -type f | wc -l | tr -d ' ') files into $OUT ($(du -sh "$OUT" | cut -f1))"
