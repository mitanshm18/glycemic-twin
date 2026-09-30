import { ApiError, NetworkError } from "@/lib/api/client";
import { errorCopy } from "@/lib/errors";

describe("error copy", () => {
  it("is specific to the API error code", () => {
    const c = errorCopy(new ApiError(404, "PATIENT_NOT_FOUND", "x"), "this patient");
    expect(c.title).toBe("Patient not found");
    expect(c.code).toBe("PATIENT_NOT_FOUND");
    expect(errorCopy(new ApiError(503, "MODEL_UNAVAILABLE", "x"), "the twin").retryable).toBe(true);
  });

  it("distinguishes an unreachable backend", () => {
    const c = errorCopy(new NetworkError(), "the patient list");
    expect(c.retryable).toBe(true);
    expect(c.title.toLowerCase()).not.toContain("something went wrong");
  });

  it("never falls back to a vague message", () => {
    for (const e of [new ApiError(500, "WHO_KNOWS", "boom"), new Error("x"), "x"]) {
      expect(errorCopy(e, "the model").title.toLowerCase()).not.toContain("something went wrong");
    }
  });
});
