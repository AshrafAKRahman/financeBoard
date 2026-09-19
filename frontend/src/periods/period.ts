/**
 * The period a report covers, kept in the URL (R6, R2.AC5, R2.AC6).
 *
 * The address is the only place a period is remembered. That is what makes bookmarking,
 * sharing and the browser's back control one mechanism instead of three, and it means there is
 * no second copy of the period to fall out of step.
 *
 * The encoded names are the API's own query parameters, so there is no translation layer and
 * no second vocabulary to learn.
 */

export const NAMED_PERIODS = [
  "this-fiscal-year",
  "last-fiscal-year",
  "this-month",
  "last-month",
  "q1",
  "q2",
  "q3",
  "q4",
] as const;

export type NamedPeriod = (typeof NAMED_PERIODS)[number];

/** A range for reports over a period, or a single date for reports as at a date. */
export type Period =
  | { kind: "named"; named: NamedPeriod }
  | { kind: "range"; start: string; end: string }
  | { kind: "on"; on: string };

export const DEFAULT_PERIOD: Period = { kind: "named", named: "this-fiscal-year" };

export class InvalidPeriod extends Error {
  readonly reason: "end-before-start" | "incomplete" | "unknown-name" | "bad-date";

  constructor(reason: InvalidPeriod["reason"], message: string) {
    super(message);
    this.name = "InvalidPeriod";
    this.reason = reason;
  }
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) {
    return false;
  }
  // Reject 2026-02-31: a date the calendar does not have.
  const [year, month, day] = value.split("-").map((part) => Number.parseInt(part, 10));
  const date = new Date(Date.UTC(year!, month! - 1, day!));
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month! - 1 &&
    date.getUTCDate() === day
  );
}

function isNamed(value: string): value is NamedPeriod {
  return (NAMED_PERIODS as readonly string[]).includes(value);
}

/** Build a range, refusing one that ends before it starts (R6.AC3). */
export function range(start: string, end: string): Period {
  if (!isIsoDate(start) || !isIsoDate(end)) {
    throw new InvalidPeriod("bad-date", "A date must be a real date, as YYYY-MM-DD.");
  }
  if (end < start) {
    throw new InvalidPeriod("end-before-start", "The end date is before the start date.");
  }
  return { kind: "range", start, end };
}

export function asOf(on: string): Period {
  if (!isIsoDate(on)) {
    throw new InvalidPeriod("bad-date", "A date must be a real date, as YYYY-MM-DD.");
  }
  return { kind: "on", on };
}

/** Read the period out of the address, falling back rather than failing (R6.AC1, R6.AC2). */
export function periodFromSearch(search: URLSearchParams): Period {
  const on = search.get("on");
  if (on && isIsoDate(on)) {
    return { kind: "on", on };
  }

  const start = search.get("start");
  const end = search.get("end");
  if (start && end && isIsoDate(start) && isIsoDate(end) && end >= start) {
    return { kind: "range", start, end };
  }

  const named = search.get("period");
  if (named && isNamed(named)) {
    return { kind: "named", named };
  }

  return DEFAULT_PERIOD;
}

/** The API's query parameters for this period. */
export function periodToQuery(period: Period): Record<string, string> {
  switch (period.kind) {
    case "named":
      return { period: period.named };
    case "range":
      return { start: period.start, end: period.end };
    case "on":
      return { on: period.on };
  }
}

/**
 * Write the period into the address, leaving everything else alone, and dropping the
 * parameters that no longer apply so the URL never describes two periods at once.
 */
export function periodToSearch(period: Period, existing?: URLSearchParams): URLSearchParams {
  const search = new URLSearchParams(existing ?? undefined);
  for (const key of ["period", "start", "end", "on"]) {
    search.delete(key);
  }
  for (const [key, value] of Object.entries(periodToQuery(period))) {
    search.set(key, value);
  }
  return search;
}

/**
 * The same period expressed for a report that takes a single date (R6.AC5).
 *
 * A balance sheet as at the end of whatever range is on screen, so moving between a range
 * report and an as-at report keeps the period rather than resetting it (R6.AC4).
 */
export function periodAsOf(period: Period, today: string): Period {
  switch (period.kind) {
    case "on":
      return period;
    case "range":
      return { kind: "on", on: period.end };
    case "named":
      return { kind: "on", on: today };
  }
}

/** And back the other way, so an as-at report's date survives a move to a range report. */
export function periodAsRange(period: Period, fallback: Period = DEFAULT_PERIOD): Period {
  return period.kind === "on" ? fallback : period;
}

/** A key for the query cache: the period, flattened (R10.AC4). */
export function periodKey(period: Period): string {
  const query = periodToQuery(period);
  return Object.entries(query)
    .map(([key, value]) => `${key}=${value}`)
    .join("&");
}
