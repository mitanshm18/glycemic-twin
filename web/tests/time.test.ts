import { DAY, dayStart, fmtClock, fmtDate, fmtDateTime, fmtDay, fmtDuration, fmtRelative, HOUR, MINUTE, parseNaive, toNaiveIso } from "@/lib/time";

describe("naive CGMacros timestamps (ADR-018)", () => {
  it("parse as wall-clock time, independent of the browser time zone", () => {
    const t = parseNaive("2021-06-05T13:20:00");
    expect(fmtClock(t)).toBe("13:20");
    expect(fmtDate(t)).toBe("5 Jun 2021");
    expect(fmtDay(t)).toBe("Sat 5 Jun");
    expect(fmtDateTime(t)).toBe("5 Jun 2021, 13:20");
  });

  it("round-trip through toNaiveIso", () => {
    for (const s of ["2021-06-05T00:00:00", "2021-12-31T23:59:59", "2020-02-29T12:05:00"]) {
      expect(toNaiveIso(parseNaive(s))).toBe(s);
    }
  });

  it("accept a space separator and fractional seconds", () => {
    expect(fmtClock(parseNaive("2021-06-05 07:03"))).toBe("07:03");
    expect(parseNaive("2021-06-05T07:03:00.5") - parseNaive("2021-06-05T07:03:00")).toBe(500);
  });

  it("reject zoned or malformed input instead of guessing", () => {
    expect(() => parseNaive("2021-06-05T13:20:00Z")).toThrow();
    expect(() => parseNaive("2021-06-05T13:20:00+02:00")).toThrow();
    expect(() => parseNaive("yesterday")).toThrow();
  });

  it("dayStart floors to midnight of the same naive day", () => {
    const t = parseNaive("2021-06-05T23:59:00");
    expect(toNaiveIso(dayStart(t))).toBe("2021-06-05T00:00:00");
    expect(dayStart(t) + DAY).toBe(parseNaive("2021-06-06T00:00:00"));
  });
});

describe("durations", () => {
  it("format short and long spans", () => {
    expect(fmtDuration(20_000)).toBe("< 1 min");
    expect(fmtDuration(4 * MINUTE)).toBe("4 min");
    expect(fmtDuration(2 * HOUR + 10 * MINUTE)).toBe("2 h 10 min");
    expect(fmtDuration(3 * HOUR)).toBe("3 h");
    expect(fmtDuration(3 * DAY)).toBe("3 d");
  });

  it("relative time uses real (zoned) system timestamps", () => {
    const now = Date.parse("2026-09-30T10:00:00Z");
    expect(fmtRelative("2026-09-30T09:59:40Z", now)).toBe("just now");
    expect(fmtRelative("2026-09-30T09:00:00Z", now)).toBe("1 h ago");
    expect(fmtRelative("not a date", now)).toBe("—");
  });
});
