/**
 * Formatting money and dates for the screen (R4).
 *
 * Amounts arrive from the API as strings — a serialised `Decimal` such as "11500.000000" —
 * and they stay strings the whole way here. Nothing in this file calls `Number()`, because a
 * JavaScript number cannot hold every figure a ledger can, and because the server is the only
 * thing allowed to decide what a figure is (R4.AC2, R10.AC6).
 *
 * So this is string surgery: split on the decimal point, group the integer digits, put it back
 * together. It is duller than `Intl.NumberFormat`, and it is the reason a six-decimal amount
 * survives a screen intact.
 */

export const ZERO_DASH = "—";

export type Locale = "en" | "ar";

export type AmountOptions = {
  /** Decimal places to show. Defaults to the currency's own, via `decimalPlacesFor`. */
  places?: number;
  /** Show a dash instead of a zero, so the eye finds the figures that matter (R4.AC7). */
  dashOnZero?: boolean;
};

/**
 * How many places a currency shows. SAR and most currencies use 2; a few use 0 or 3.
 * The API tells us the currency, not its scale, so this table is the frontend's business.
 */
const PLACES: Record<string, number> = {
  BHD: 3,
  IQD: 3,
  JOD: 3,
  KWD: 3,
  LYD: 3,
  OMR: 3,
  TND: 3,
  JPY: 0,
  KRW: 0,
  CLP: 0,
  ISK: 0,
  VND: 0,
};

export function decimalPlacesFor(currency: string): number {
  return PLACES[currency.toUpperCase()] ?? 2;
}

/** Is this string a zero, whatever its scale? "0", "0.00" and "-0.000000" all are. */
export function isZeroAmount(amount: string): boolean {
  return /^[+-]?0*(\.0*)?$/.test(amount.trim());
}

export function isNegativeAmount(amount: string): boolean {
  return amount.trim().startsWith("-") && !isZeroAmount(amount);
}

function groupDigits(digits: string): string {
  // Insert a separator every three digits from the right, without arithmetic.
  let out = "";
  for (let i = 0; i < digits.length; i += 1) {
    if (i > 0 && (digits.length - i) % 3 === 0) {
      out += ",";
    }
    out += digits[i];
  }
  return out;
}

function toScale(fraction: string, places: number): string {
  if (places === 0) {
    return "";
  }
  if (fraction.length >= places) {
    // Trimming trailing digits the API sent, never rounding: "11500.000000" at 2 places is
    // "11500.00". A figure whose significant digits would be lost is left at its own scale
    // instead, because silently dropping them would change the number.
    const kept = fraction.slice(0, places);
    const dropped = fraction.slice(places);
    return /[1-9]/.test(dropped) ? fraction : kept;
  }
  return fraction.padEnd(places, "0");
}

/**
 * Format an amount the API gave us (R4.AC1, R4.AC5).
 *
 * @param amount a decimal string, e.g. "11500.000000" or "-3450.00"
 */
export function formatAmount(
  amount: string | null | undefined,
  currency: string,
  options: AmountOptions = {},
): string {
  if (amount === null || amount === undefined || amount.trim() === "") {
    return ZERO_DASH;
  }

  const places = options.places ?? decimalPlacesFor(currency);

  if (options.dashOnZero !== false && isZeroAmount(amount)) {
    return ZERO_DASH;
  }

  const trimmed = amount.trim();
  const negative = trimmed.startsWith("-");
  const unsigned = trimmed.replace(/^[+-]/, "");
  const [rawInteger = "0", rawFraction = ""] = unsigned.split(".");
  const integer = groupDigits(rawInteger.replace(/^0+(?=\d)/, ""));
  const fraction = toScale(rawFraction, places);

  const body = fraction === "" ? integer : `${integer}.${fraction}`;
  // A leading minus, not parentheses: the same mark on every report (R4.AC4).
  return negative ? `-${body}` : body;
}

/** The amount with its currency, for a total or a single figure. */
export function formatMoney(
  amount: string | null | undefined,
  currency: string,
  options: AmountOptions = {},
): string {
  const figure = formatAmount(amount, currency, options);
  return figure === ZERO_DASH ? figure : `${figure} ${currency.toUpperCase()}`;
}

const MONTHS: Record<Locale, string[]> = {
  en: [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ],
  ar: [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
  ],
};

/**
 * A date whose day and month cannot be confused (R4.AC6).
 *
 * "2026-03-01" becomes "1 Mar 2026", never "01/03/2026" — which means one thing in Riyadh and
 * another in New York.
 */
export function formatDate(iso: string | null | undefined, locale: Locale = "en"): string {
  if (!iso) {
    return ZERO_DASH;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso.trim());
  if (!match) {
    return iso;
  }
  const [, year, month, day] = match as unknown as [string, string, string, string];
  const name = MONTHS[locale][Number.parseInt(month, 10) - 1] ?? month;
  return `${Number.parseInt(day, 10)} ${name} ${year}`;
}

/** A timestamp for "these figures were read at…" (R5.AC2). */
export function formatReadAt(iso: string | null | undefined, locale: Locale = "en"): string {
  if (!iso) {
    return ZERO_DASH;
  }
  const time = /T(\d{2}):(\d{2})/.exec(iso);
  const date = formatDate(iso, locale);
  return time ? `${date}, ${time[1]}:${time[2]}` : date;
}
