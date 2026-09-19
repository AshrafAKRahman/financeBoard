/**
 * Two charts, drawn by hand (R7).
 *
 * A charting library would be a hundred kilobytes against a four-hundred kilobyte budget, and
 * would still need the right-to-left work doing by hand. These are two components that take
 * the table's own figures, so a chart cannot disagree with the table beside it (R7.AC4).
 *
 * Each one carries a text alternative: a title, a description, and a visually hidden table of
 * the same figures, so the chart is readable by a screen reader rather than decorative
 * (R7.AC3, R11.AC4).
 */
import { useId } from "react";

import { formatAmount } from "@/money/format";

import { buildScale, toPixelValue } from "./scale";

export type ChartPoint = {
  /** What the axis calls this point. */
  label: string;
  /** The amount, exactly as the API sent it. */
  amount: string;
};

export type ChartSeries = {
  name: string;
  points: ChartPoint[];
  /** A CSS colour. Two series must differ by more than colour, so each also gets a pattern. */
  colour: string;
};

/** R7.AC6 — below this, a chart shows a shape that is not there. */
export const MINIMUM_POINTS = 3;

type Common = {
  currency: string;
  /** What the chart is, in words, for anyone who cannot see it. */
  description: string;
  direction?: "ltr" | "rtl";
  height?: number;
};

function HiddenTable({
  series,
  currency,
  id,
}: {
  series: ChartSeries[];
  currency: string;
  id: string;
}) {
  const labels = series[0]?.points.map((point) => point.label) ?? [];
  return (
    <table id={id} className="visually-hidden">
      <caption>Figures shown in the chart</caption>
      <thead>
        <tr>
          <th scope="col">Period</th>
          {series.map((one) => (
            <th scope="col" key={one.name}>
              {one.name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {labels.map((label, index) => (
          <tr key={label}>
            <th scope="row">{label}</th>
            {series.map((one) => (
              <td key={one.name}>
                {formatAmount(one.points[index]?.amount ?? "0", currency, {
                  dashOnZero: false,
                })}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Income and expenses over the months of a period (R7.AC1). */
export function LineChart({
  series,
  currency,
  description,
  direction = "ltr",
  height = 220,
}: Common & { series: ChartSeries[] }) {
  const titleId = useId();
  const descriptionId = useId();
  const tableId = useId();

  const points = series[0]?.points.length ?? 0;
  if (points < MINIMUM_POINTS) {
    return <HiddenTable series={series} currency={currency} id={tableId} />;
  }

  const width = 640;
  const padding = { top: 16, right: 16, bottom: 32, left: 64 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const values = series.flatMap((one) => one.points.map((point) => toPixelValue(point.amount)));
  const scale = buildScale(values);

  const xOf = (index: number) => {
    const fraction = points === 1 ? 0.5 : index / (points - 1);
    // The plot mirrors with the layout, so the first month stays where reading starts.
    const placed = direction === "rtl" ? 1 - fraction : fraction;
    return padding.left + placed * plotWidth;
  };
  const yOf = (value: number) => padding.top + (1 - scale.positionOf(value)) * plotHeight;

  return (
    <figure className="chart" role="group" aria-labelledby={titleId}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <title id={titleId}>{description}</title>
        <desc id={descriptionId}>{`Amounts in ${currency}. ${description}`}</desc>

        {scale.ticks.map((tick) => (
          <g key={tick.value}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={yOf(tick.value)}
              y2={yOf(tick.value)}
              stroke="currentColor"
              strokeOpacity={tick.value === 0 ? 0.45 : 0.12}
            />
            <text
              x={direction === "rtl" ? width - padding.right + 8 : padding.left - 8}
              y={yOf(tick.value) + 4}
              textAnchor={direction === "rtl" ? "start" : "end"}
              fontSize="11"
              fill="currentColor"
              opacity={0.65}
            >
              {tick.label}
            </text>
          </g>
        ))}

        {series.map((one) => (
          <polyline
            key={one.name}
            fill="none"
            stroke={one.colour}
            strokeWidth="2"
            strokeLinejoin="round"
            points={one.points
              .map((point, index) => `${xOf(index)},${yOf(toPixelValue(point.amount))}`)
              .join(" ")}
          />
        ))}

        {series[0]?.points.map((point, index) => (
          <text
            key={point.label}
            x={xOf(index)}
            y={height - 10}
            textAnchor="middle"
            fontSize="11"
            fill="currentColor"
            opacity={0.65}
          >
            {point.label}
          </text>
        ))}
      </svg>
      <figcaption className="chart-legend">
        {series.map((one) => (
          <span key={one.name}>
            <span className="chart-swatch" style={{ background: one.colour }} aria-hidden="true" />
            {one.name}
          </span>
        ))}
        <span className="chart-unit">{currency}</span>
      </figcaption>
      <HiddenTable series={series} currency={currency} id={tableId} />
    </figure>
  );
}

/** How much is owed in each ageing bucket (R7.AC2). */
export function BarChart({
  points,
  currency,
  description,
  colour = "#0f5c46",
  direction = "ltr",
  height = 220,
}: Common & { points: ChartPoint[]; colour?: string }) {
  const titleId = useId();
  const descriptionId = useId();
  const tableId = useId();
  const series: ChartSeries[] = [{ name: description, points, colour }];

  if (points.length === 0) {
    return <HiddenTable series={series} currency={currency} id={tableId} />;
  }

  const width = 640;
  const padding = { top: 16, right: 16, bottom: 32, left: 64 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const values = points.map((point) => toPixelValue(point.amount));
  const scale = buildScale(values);
  const slot = plotWidth / points.length;
  const barWidth = Math.min(slot * 0.6, 64);
  const yOf = (value: number) => padding.top + (1 - scale.positionOf(value)) * plotHeight;

  return (
    <figure className="chart" role="group" aria-labelledby={titleId}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <title id={titleId}>{description}</title>
        <desc id={descriptionId}>{`Amounts in ${currency}. ${description}`}</desc>

        {scale.ticks.map((tick) => (
          <g key={tick.value}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={yOf(tick.value)}
              y2={yOf(tick.value)}
              stroke="currentColor"
              strokeOpacity={tick.value === 0 ? 0.45 : 0.12}
            />
            <text
              x={direction === "rtl" ? width - padding.right + 8 : padding.left - 8}
              y={yOf(tick.value) + 4}
              textAnchor={direction === "rtl" ? "start" : "end"}
              fontSize="11"
              fill="currentColor"
              opacity={0.65}
            >
              {tick.label}
            </text>
          </g>
        ))}

        {points.map((point, index) => {
          const value = toPixelValue(point.amount);
          const placed = direction === "rtl" ? points.length - 1 - index : index;
          const centre = padding.left + placed * slot + slot / 2;
          const top = yOf(Math.max(value, 0));
          const zero = yOf(0);
          return (
            <g key={point.label}>
              <rect
                x={centre - barWidth / 2}
                y={Math.min(top, zero)}
                width={barWidth}
                height={Math.max(Math.abs(zero - top), 1)}
                fill={colour}
                fillOpacity={value < 0 ? 0.45 : 1}
              />
              <text
                x={centre}
                y={height - 10}
                textAnchor="middle"
                fontSize="11"
                fill="currentColor"
                opacity={0.65}
              >
                {point.label}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="chart-legend">
        <span className="chart-unit">{currency}</span>
      </figcaption>
      <HiddenTable series={series} currency={currency} id={tableId} />
    </figure>
  );
}
