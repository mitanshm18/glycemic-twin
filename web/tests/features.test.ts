import { FEATURES, featureInfo, fmtFeature } from "@/lib/features";
import { tidyNumbers } from "@/lib/format";

// The frozen 45-column model contract (data/configs/model_features.v1.yaml, full_personal).
const CONTRACT = [
  "g_last", "g_age_min", "slope_15", "slope_30", "sd_60", "mean_180", "min_180", "max_180", "tir_24h",
  "g_overnight_baseline", "g_vs_baseline", "carbs_g", "protein_g", "fat_g", "fiber_g", "calories_kcal",
  "meal_breakfast", "meal_lunch", "meal_dinner", "meal_snack", "hour_sin", "hour_cos", "carbs_prev_3h",
  "invalid_meal_prev_3h", "mins_since_meal", "hr_30", "hr_resting", "hr_delta", "mets_available", "mets_60",
  "active_min_3h", "activity_kcal_60", "hr_age_min", "hba1c_pct", "fasting_glucose_mgdl",
  "fasting_insulin_uu_ml", "homa_ir", "bmi", "age_years", "sex_female", "triglycerides_mgdl", "hdl_mgdl",
  "p_personal", "rise_offset_mgdl", "personal_weight",
];

describe("feature dictionary", () => {
  it("describes every contract input in plain language", () => {
    expect(CONTRACT).toHaveLength(45);
    for (const c of CONTRACT) {
      expect(FEATURES[c], c).toBeDefined();
      expect(featureInfo(c).what.length).toBeGreaterThan(10);
    }
  });

  it("shows missing inputs as missing, never as zero", () => {
    expect(fmtFeature("carbs_g", null)).toBe("missing");
    expect(fmtFeature("carbs_g", Number.NaN)).toBe("missing");
    expect(fmtFeature("carbs_g", 92)).toContain("92");
  });

  it("falls back for unknown names", () => {
    expect(featureInfo("brand_new_column").label.length).toBeGreaterThan(0);
  });
});

describe("diff sentences", () => {
  it("round engine floats for reading without touching other text", () => {
    expect(tidyNumbers("risk scored:0.6757997958427439 -> scored:0.6502422616045337")).toBe("risk scored:0.676 -> scored:0.650");
    expect(tidyNumbers("latest glucose 110.0 -> 111.0 mg/dL")).toBe("latest glucose 110.0 -> 111.0 mg/dL");
    expect(tidyNumbers("offset 24.43812 mg/dL")).toBe("offset 24.4 mg/dL");
  });
});
