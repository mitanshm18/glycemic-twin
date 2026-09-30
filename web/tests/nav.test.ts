import { safeNext } from "@/lib/nav";

describe("post-login redirect guard", () => {
  it("keeps in-app destinations", () => {
    expect(safeNext("/patients/7?at=2021-06-05T13:00:00&meal=7-5-13")).toBe("/patients/7?at=2021-06-05T13:00:00&meal=7-5-13");
    expect(safeNext("/model")).toBe("/model");
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/login", "/login?next=/x", "", null, "patients", "/\u0000x"])(
    "rejects %s",
    (v) => {
      expect(safeNext(v)).toBe("/patients");
    },
  );
});
