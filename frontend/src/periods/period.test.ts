/** The period lives in the URL (R6, R2.AC5). */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_PERIOD,
  InvalidPeriod,
  asOf,
  isIsoDate,
  periodAsOf,
  periodAsRange,
  periodFromSearch,
  periodKey,
  periodToQuery,
  periodToSearch,
  range,
} from "./period";

const search = (query: string) => new URLSearchParams(query);

describe("reading a period from the address", () => {
  it("takes a named period", () => {
    // R6.AC1
    expect(periodFromSearch(search("period=q2"))).toEqual({ kind: "named", named: "q2" });
  });

  it("takes an explicit range", () => {
    // R6.AC2
    expect(periodFromSearch(search("start=2026-01-01&end=2026-03-31"))).toEqual({
      kind: "range",
      start: "2026-01-01",
      end: "2026-03-31",
    });
  });

  it("takes a single date", () => {
    // R6.AC5
    expect(periodFromSearch(search("on=2026-12-31"))).toEqual({ kind: "on", on: "2026-12-31" });
  });

  it("falls back rather than failing on nonsense", () => {
    expect(periodFromSearch(search(""))).toEqual(DEFAULT_PERIOD);
    expect(periodFromSearch(search("period=last-fortnight"))).toEqual(DEFAULT_PERIOD);
    expect(periodFromSearch(search("start=2026-01-01"))).toEqual(DEFAULT_PERIOD);
    expect(periodFromSearch(search("start=2026-13-01&end=2026-14-01"))).toEqual(DEFAULT_PERIOD);
  });

  it("ignores a backwards range in the address", () => {
    // R6.AC3 — a shared link with a bad range shows the default, not an error page.
    expect(periodFromSearch(search("start=2026-12-31&end=2026-01-01"))).toEqual(DEFAULT_PERIOD);
  });

  it("prefers a single date over a range when both are present", () => {
    expect(periodFromSearch(search("on=2026-06-30&start=2026-01-01&end=2026-03-31"))).toEqual({
      kind: "on",
      on: "2026-06-30",
    });
  });
});

describe("writing a period into the address", () => {
  it("round-trips every kind", () => {
    // R2.AC5 — a bookmarked report comes back the same.
    for (const period of [
      { kind: "named", named: "q3" } as const,
      { kind: "range", start: "2026-02-01", end: "2026-02-28" } as const,
      { kind: "on", on: "2026-09-19" } as const,
    ]) {
      expect(periodFromSearch(periodToSearch(period))).toEqual(period);
    }
  });

  it("leaves other parameters alone", () => {
    const next = periodToSearch({ kind: "named", named: "q1" }, search("partner=abc"));
    expect(next.get("partner")).toBe("abc");
    expect(next.get("period")).toBe("q1");
  });

  it("never leaves two periods in the address at once", () => {
    const next = periodToSearch(
      { kind: "named", named: "q1" },
      search("start=2026-01-01&end=2026-03-31&on=2026-06-30"),
    );
    expect(next.get("start")).toBeNull();
    expect(next.get("end")).toBeNull();
    expect(next.get("on")).toBeNull();
    expect(next.get("period")).toBe("q1");
  });

  it("uses the API's own parameter names", () => {
    expect(periodToQuery({ kind: "range", start: "2026-01-01", end: "2026-12-31" })).toEqual({
      start: "2026-01-01",
      end: "2026-12-31",
    });
    expect(periodToQuery({ kind: "named", named: "q4" })).toEqual({ period: "q4" });
  });
});

describe("refusing a period that makes no sense", () => {
  it("refuses an end before a start", () => {
    // R6.AC3
    expect(() => range("2026-12-31", "2026-01-01")).toThrowError(InvalidPeriod);
    try {
      range("2026-12-31", "2026-01-01");
    } catch (error) {
      expect((error as InvalidPeriod).reason).toBe("end-before-start");
    }
  });

  it("allows a single day", () => {
    expect(range("2026-03-01", "2026-03-01").kind).toBe("range");
  });

  it("refuses a date the calendar does not have", () => {
    expect(() => range("2026-02-31", "2026-03-01")).toThrowError(InvalidPeriod);
    expect(() => asOf("2026-13-01")).toThrowError(InvalidPeriod);
    expect(isIsoDate("2026-02-29")).toBe(false);
    expect(isIsoDate("2028-02-29")).toBe(true);
  });
});

describe("carrying the period between reports", () => {
  it("turns a range into its end date for an as-at report", () => {
    // R6.AC4
    expect(periodAsOf({ kind: "range", start: "2026-01-01", end: "2026-03-31" }, "2026-09-19")).toEqual(
      { kind: "on", on: "2026-03-31" },
    );
  });

  it("uses today for a named period", () => {
    expect(periodAsOf({ kind: "named", named: "q1" }, "2026-09-19")).toEqual({
      kind: "on",
      on: "2026-09-19",
    });
  });

  it("turns an as-at date back into a range report's default", () => {
    expect(periodAsRange({ kind: "on", on: "2026-03-31" })).toEqual(DEFAULT_PERIOD);
    expect(periodAsRange({ kind: "named", named: "q2" })).toEqual({ kind: "named", named: "q2" });
  });
});

describe("the cache key", () => {
  it("distinguishes one period from another", () => {
    // R10.AC4
    expect(periodKey({ kind: "named", named: "q1" })).not.toBe(periodKey({ kind: "named", named: "q2" }));
    expect(periodKey({ kind: "range", start: "2026-01-01", end: "2026-12-31" })).toBe(
      "start=2026-01-01&end=2026-12-31",
    );
  });
});
