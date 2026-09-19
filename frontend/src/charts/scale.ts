/**
 * Turning amounts into pixels (R7.AC4).
 *
 * Charts scale from the same strings the table shows. The only arithmetic here is geometry —
 * where a bar ends, where a tick sits — and it happens after the string has been turned into
 * a number *for drawing only*. No figure produced here is ever shown as a figure; the labels
 * come from the formatter, from the original strings.
 */

/** A number for geometry only. Never rendered, never compared with a ledger figure. */
export function toPixelValue(amount: string): number {
  const cleaned = amount.trim().replace(/,/g, "");
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : 0;
}

export type Tick = { value: number; label: string };

/** A rounded step so the axis reads 0, 5,000, 10,000 rather than 0, 4,317, 8,634. */
export function niceStep(span: number, targetTicks: number): number {
  if (span <= 0) {
    return 1;
  }
  const rough = span / Math.max(targetTicks, 1);
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  for (const multiple of [1, 2, 2.5, 5, 10]) {
    const step = magnitude * multiple;
    if (step >= rough) {
      return step;
    }
  }
  return magnitude * 10;
}

/**
 * The scale a chart draws against: where zero sits, and the ticks that label it.
 *
 * Always includes zero, because a bar chart that starts at 4,000 exaggerates every difference.
 */
export function buildScale(values: number[], targetTicks = 4): {
  min: number;
  max: number;
  ticks: Tick[];
  positionOf: (value: number) => number;
} {
  const withZero = [0, ...values];
  const rawMin = Math.min(...withZero);
  const rawMax = Math.max(...withZero);
  const step = niceStep(rawMax - rawMin || 1, targetTicks);
  const min = Math.floor(rawMin / step) * step;
  const max = Math.ceil(rawMax / step) * step;
  const span = max - min || 1;

  const ticks: Tick[] = [];
  for (let value = min; value <= max + step / 2; value += step) {
    const rounded = Math.abs(value) < step / 1e6 ? 0 : value;
    ticks.push({ value: rounded, label: formatTick(rounded) });
  }

  return {
    min,
    max,
    ticks,
    /** 0 at the bottom of the plot, 1 at the top. */
    positionOf: (value: number) => (value - min) / span,
  };
}

/** Axis labels are abbreviated, because an axis is not a ledger. */
export function formatTick(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) {
    return `${trim(value / 1_000_000)}M`;
  }
  if (magnitude >= 1_000) {
    return `${trim(value / 1_000)}k`;
  }
  return trim(value);
}

function trim(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
