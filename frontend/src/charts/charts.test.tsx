/** Charts draw the table's own figures (R7, R11.AC4). */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BarChart, LineChart, MINIMUM_POINTS } from "./Charts";
import type { ChartPoint, ChartSeries } from "./Charts";
import { buildScale, formatTick, niceStep, toPixelValue } from "./scale";

const months = (amounts: string[]): ChartPoint[] =>
  amounts.map((amount, index) => ({ label: `M${index + 1}`, amount }));

const income: ChartSeries = {
  name: "Income",
  points: months(["10000.00", "12000.00", "9000.00", "15000.00"]),
  colour: "#0f5c46",
};
const expenses: ChartSeries = {
  name: "Expenses",
  points: months(["4000.00", "4500.00", "5000.00", "4200.00"]),
  colour: "#8f5511",
};

const buckets: ChartPoint[] = [
  { label: "Current", amount: "5000.00" },
  { label: "1-30", amount: "2500.00" },
  { label: "31-60", amount: "0.00" },
  { label: "61-90", amount: "1200.00" },
  { label: "90+", amount: "800.00" },
];

describe("the scale", () => {
  it("always includes zero, so differences are not exaggerated", () => {
    const scale = buildScale([4000, 4200, 4500]);
    expect(scale.min).toBe(0);
  });

  it("picks rounded steps a person can read", () => {
    expect(niceStep(10000, 4)).toBe(2500);
    expect(formatTick(2500)).toBe("2.5k");
    expect(formatTick(1_000_000)).toBe("1M");
    expect(formatTick(0)).toBe("0");
  });

  it("reads an amount string for geometry without breaking on nonsense", () => {
    expect(toPixelValue("11500.000000")).toBe(11500);
    expect(toPixelValue("-3450.00")).toBe(-3450);
    expect(toPixelValue("not a number")).toBe(0);
  });

  it("maps the bottom of the scale to 0 and the top to 1", () => {
    const scale = buildScale([0, 100]);
    expect(scale.positionOf(scale.min)).toBe(0);
    expect(scale.positionOf(scale.max)).toBe(1);
  });
});

describe("a line chart of income and expenses", () => {
  it("draws a line per series", () => {
    // R7.AC1
    const { container } = render(
      <LineChart series={[income, expenses]} currency="SAR" description="Income and expenses by month" />,
    );
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
  });

  it("names the currency on the chart", () => {
    // R7.AC3
    render(<LineChart series={[income]} currency="SAR" description="Income by month" />);
    expect(screen.getByRole("img")).toHaveAccessibleDescription(/SAR/);
  });

  it("gives a screen reader the same figures as the picture", () => {
    // R7.AC4, R11.AC4 — the alternative is the figures, not a summary of them.
    render(<LineChart series={[income]} currency="SAR" description="Income by month" />);
    const table = screen.getByRole("table", { name: /figures shown in the chart/i });
    expect(within(table).getByText("10,000.00")).toBeInTheDocument();
    expect(within(table).getByText("15,000.00")).toBeInTheDocument();
  });

  it("shows the figures without a chart when there is no trend to show", () => {
    // R7.AC6
    const twoMonths: ChartSeries = { ...income, points: income.points.slice(0, MINIMUM_POINTS - 1) };
    const { container } = render(
      <LineChart series={[twoMonths]} currency="SAR" description="Income by month" />,
    );
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("mirrors when the layout does", () => {
    // R7.AC5 — the first month sits where reading starts in each direction.
    const first = (direction: "ltr" | "rtl") => {
      const { container, unmount } = render(
        <LineChart series={[income]} currency="SAR" description="Income" direction={direction} />,
      );
      const x = Number(
        container.querySelector("polyline")?.getAttribute("points")?.split(",")[0] ?? "0",
      );
      unmount();
      return x;
    };
    expect(first("ltr")).toBeLessThan(first("rtl"));
  });
});

describe("a bar chart of the ageing buckets", () => {
  it("draws a bar per bucket", () => {
    // R7.AC2
    const { container } = render(
      <BarChart points={buckets} currency="SAR" description="Receivables by age" />,
    );
    expect(container.querySelectorAll("rect")).toHaveLength(buckets.length);
  });

  it("labels every bucket", () => {
    const { container } = render(
      <BarChart points={buckets} currency="SAR" description="Receivables by age" />,
    );
    const labels = [...container.querySelectorAll("text")].map((node) => node.textContent);
    for (const bucket of buckets) {
      expect(labels).toContain(bucket.label);
    }
  });

  it("gives an empty bucket a bar of no height rather than skipping it", () => {
    const { container } = render(
      <BarChart points={buckets} currency="SAR" description="Receivables by age" />,
    );
    const heights = [...container.querySelectorAll("rect")].map((node) =>
      Number(node.getAttribute("height")),
    );
    expect(Math.min(...heights)).toBeLessThanOrEqual(1);
  });

  it("carries the figures in its text alternative", () => {
    // R11.AC4
    render(<BarChart points={buckets} currency="SAR" description="Receivables by age" />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("5,000.00")).toBeInTheDocument();
    expect(within(table).getByText("0.00")).toBeInTheDocument();
  });

  it("says what it shows", () => {
    // R7.AC3
    render(<BarChart points={buckets} currency="SAR" description="Receivables by age" />);
    expect(screen.getByRole("img", { name: "Receivables by age" })).toBeInTheDocument();
  });

  it("shows nothing to draw as a table alone", () => {
    render(<BarChart points={[]} currency="SAR" description="Receivables by age" />);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
