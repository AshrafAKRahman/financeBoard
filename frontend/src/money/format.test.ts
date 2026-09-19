/**
 * Money on screen (R4, R10.AC6).
 *
 * The important tests here are the ones about scale: the ledger stores six decimal places and
 * a JavaScript number cannot hold them, so the formatter must never have met one.
 */
import { describe, expect, it } from "vitest";

import {
  ZERO_DASH,
  decimalPlacesFor,
  formatAmount,
  formatDate,
  formatMoney,
  formatReadAt,
  isNegativeAmount,
  isZeroAmount,
} from "./format";

describe("formatting an amount", () => {
  it("groups thousands", () => {
    // R4.AC1
    expect(formatAmount("11500.000000", "SAR")).toBe("11,500.00");
    expect(formatAmount("1234567.89", "SAR")).toBe("1,234,567.89");
  });

  it("keeps small amounts ungrouped", () => {
    expect(formatAmount("999.99", "SAR")).toBe("999.99");
  });

  it("shows the currency's decimal places", () => {
    expect(formatAmount("100", "SAR")).toBe("100.00");
    expect(formatAmount("100", "KWD")).toBe("100.000");
    expect(formatAmount("100", "JPY")).toBe("100");
  });

  it("marks a negative with a leading minus, the same way everywhere", () => {
    // R4.AC4
    expect(formatAmount("-3450.00", "SAR")).toBe("-3,450.00");
  });

  it("shows a dash for zero at any scale", () => {
    // R4.AC7
    expect(formatAmount("0", "SAR")).toBe(ZERO_DASH);
    expect(formatAmount("0.00", "SAR")).toBe(ZERO_DASH);
    expect(formatAmount("0.000000", "SAR")).toBe(ZERO_DASH);
    expect(formatAmount("-0.000000", "SAR")).toBe(ZERO_DASH);
  });

  it("can be asked to show a zero as a figure", () => {
    expect(formatAmount("0.00", "SAR", { dashOnZero: false })).toBe("0.00");
  });

  it("shows a dash for a missing amount rather than NaN", () => {
    expect(formatAmount(null, "SAR")).toBe(ZERO_DASH);
    expect(formatAmount(undefined, "SAR")).toBe(ZERO_DASH);
    expect(formatAmount("", "SAR")).toBe(ZERO_DASH);
  });

  it("strips leading zeros without eating the number", () => {
    expect(formatAmount("000123.45", "SAR")).toBe("123.45");
    expect(formatAmount("0.50", "SAR")).toBe("0.50");
  });
});

describe("never losing what the ledger sent", () => {
  it("keeps a figure a float would round", () => {
    // R4.AC2, R10.AC6 — 0.1 + 0.2 territory. The string is the truth.
    expect(formatAmount("0.300000", "SAR")).toBe("0.30");
    expect(formatAmount("1234567890123456.78", "SAR")).toBe("1,234,567,890,123,456.78");
  });

  it("keeps significant digits beyond the currency's scale rather than dropping them", () => {
    // Trimming "11500.000000" to "11500.00" loses nothing. Trimming "0.000001" would lose the
    // whole figure, so the full scale is shown instead — visible, not silently rounded away.
    expect(formatAmount("11500.000000", "SAR")).toBe("11,500.00");
    expect(formatAmount("0.000001", "SAR")).toBe("0.000001");
  });

  it("does not round", () => {
    expect(formatAmount("1.999999", "SAR")).toBe("1.999999");
  });
});

describe("recognising amounts", () => {
  it("knows a zero from a small number", () => {
    expect(isZeroAmount("0.000000")).toBe(true);
    expect(isZeroAmount("-0.00")).toBe(true);
    expect(isZeroAmount("0.000001")).toBe(false);
  });

  it("knows a negative from a negative zero", () => {
    expect(isNegativeAmount("-1.00")).toBe(true);
    expect(isNegativeAmount("-0.00")).toBe(false);
    expect(isNegativeAmount("1.00")).toBe(false);
  });

  it("knows each currency's scale", () => {
    expect(decimalPlacesFor("sar")).toBe(2);
    expect(decimalPlacesFor("KWD")).toBe(3);
    expect(decimalPlacesFor("JPY")).toBe(0);
    expect(decimalPlacesFor("XXX")).toBe(2);
  });
});

describe("an amount with its currency", () => {
  it("names the currency", () => {
    // R4.AC3
    expect(formatMoney("11500.00", "SAR")).toBe("11,500.00 SAR");
  });

  it("leaves a dash alone", () => {
    expect(formatMoney("0.00", "SAR")).toBe(ZERO_DASH);
  });
});

describe("dates", () => {
  it("cannot be read as the wrong month", () => {
    // R4.AC6
    expect(formatDate("2026-03-01")).toBe("1 Mar 2026");
    expect(formatDate("2026-12-31")).toBe("31 Dec 2026");
  });

  it("uses Arabic month names in Arabic", () => {
    expect(formatDate("2026-03-01", "ar")).toBe("1 مارس 2026");
  });

  it("shows a dash for no date", () => {
    expect(formatDate(null)).toBe(ZERO_DASH);
  });

  it("leaves something it cannot parse alone rather than inventing a date", () => {
    expect(formatDate("not a date")).toBe("not a date");
  });

  it("shows when the figures were read", () => {
    // R5.AC2
    expect(formatReadAt("2026-09-19T08:42:11.123456+00:00")).toBe("19 Sep 2026, 08:42");
  });
});
