/** The pieces every report uses (R4, R5, R9). */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type { ReportRow } from "@/api/reports";

import { HierarchyTable } from "./HierarchyTable";
import { Amount, ReportHeader, ReportState, flattenRows } from "./shared";
import { COMPANY_ID, meta, receivable, renderScreen, row, trialBalance } from "@/test/harness";

const period = { kind: "named", named: "this-fiscal-year" } as const;

describe("an amount on screen", () => {
  it("formats without recomputing", () => {
    // R4.AC1, R4.AC2
    renderScreen(<Amount value="11500.000000" currency="SAR" />);
    expect(screen.getByText("11,500.00")).toBeInTheDocument();
  });

  it("never mirrors, so a figure cannot be read backwards", () => {
    // R3.AC5
    renderScreen(<Amount value="-3450.000000" currency="SAR" />, { locale: "ar" });
    const figure = screen.getByText(/3,450/);
    expect(figure).toHaveAttribute("dir", "ltr");
  });

  it("marks a negative", () => {
    // R4.AC4
    renderScreen(<Amount value="-3450.00" currency="SAR" />);
    expect(screen.getByText("-3,450.00")).toHaveClass("negative");
  });

  it("shows a dash for zero", () => {
    // R4.AC7
    renderScreen(<Amount value="0.000000" currency="SAR" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("a report's header", () => {
  it("says whose figures these are, for when, and when they were read", () => {
    // R5.AC2
    renderScreen(<ReportHeader title="Trial balance" meta={meta} />);
    expect(screen.getByRole("heading", { name: "Trial balance" })).toBeInTheDocument();
    expect(screen.getByText("Riyadh Trading Co")).toBeInTheDocument();
    expect(screen.getByText("Fiscal year 2026")).toBeInTheDocument();
    expect(screen.getByText(/Currency: SAR/)).toBeInTheDocument();
    expect(screen.getByText(/Read at: 19 Sep 2026, 08:42/)).toBeInTheDocument();
  });
});

describe("what a screen shows instead of figures", () => {
  it("says it is loading, out loud", () => {
    // R5.AC8
    renderScreen(
      <ReportState isPending error={null}>
        <div>figures</div>
      </ReportState>,
    );
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });

  it("says a period has nothing in it", () => {
    // R5.AC9
    renderScreen(
      <ReportState isPending={false} error={null} isEmpty>
        <div>figures</div>
      </ReportState>,
    );
    expect(screen.getByText("No figures for this period.")).toBeInTheDocument();
  });

  it("names what was refused, not just that something failed", () => {
    // R9.AC1
    renderScreen(
      <ReportState isPending={false} error={new ApiError({ status: 403 })}>
        <div>figures</div>
      </ReportState>,
    );
    expect(screen.getByText("You do not have permission to read this.")).toBeInTheDocument();
  });

  it("distinguishes an unreachable server from a refusal", () => {
    // R9.AC4
    renderScreen(
      <ReportState isPending={false} error={new ApiError({ status: 0 })}>
        <div>figures</div>
      </ReportState>,
    );
    expect(screen.getByText(/check your connection/)).toBeInTheDocument();
  });

  it("shows the API's own message for an invalid request", () => {
    // R9.AC2
    renderScreen(
      <ReportState
        isPending={false}
        error={
          new ApiError({
            status: 422,
            code: "reporting.invalid_period",
            detail: "The end date is before the start date.",
          })
        }
      >
        <div>figures</div>
      </ReportState>,
    );
    expect(screen.getByText("The end date is before the start date.")).toBeInTheDocument();
  });

  it("offers to try again, and never shows a code alone", () => {
    // R9.AC3, R9.AC6
    const retry = vi.fn();
    renderScreen(
      <ReportState isPending={false} error={new ApiError({ status: 500 })} onRetry={retry}>
        <div>figures</div>
      </ReportState>,
    );
    expect(screen.getByText("Something went wrong reading this report.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("flattening a hierarchy", () => {
  const tree: ReportRow[] = [
    row({ code: "1", name: "Assets", is_group: true, children: [receivable] }),
  ];

  it("walks parents then children", () => {
    // R5.AC3
    expect(flattenRows(tree, new Set()).map((node) => node.code)).toEqual(["1", "1200"]);
  });

  it("hides a collapsed group's children", () => {
    // R5.AC4
    expect(flattenRows(tree, new Set(["1"])).map((node) => node.code)).toEqual(["1"]);
  });
});

describe("the hierarchy on screen", () => {
  const table = (locale: "en" | "ar" = "en") =>
    renderScreen(
      <HierarchyTable
        rows={trialBalance.rows}
        currency="SAR"
        period={period}
        locale={locale}
        columns={[{ key: "closing", label: "Closing" }]}
      />,
    );

  it("shows a group and its children with their subtotals", () => {
    // R5.AC3
    table();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("Trade Receivables")).toBeInTheDocument();
  });

  it("collapses a group and keeps its subtotal", async () => {
    // R5.AC4
    const user = userEvent.setup();
    table();
    await user.click(screen.getAllByRole("button", { expanded: true })[0]!);

    expect(screen.queryByText("Trade Receivables")).not.toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("9,200.00")).toBeInTheDocument();
  });

  it("links a posting account to the entries behind it", () => {
    // R8.AC1
    table();
    const link = screen.getByRole("link", { name: "Trade Receivables" });
    expect(link).toHaveAttribute(
      "href",
      `/companies/${COMPANY_ID}/reports/accounts/${receivable.account_id}?period=this-fiscal-year`,
    );
  });

  it("does not link a group, because nothing posts to one", () => {
    table();
    expect(screen.queryByRole("link", { name: "Assets" })).not.toBeInTheDocument();
  });

  it("shows the Arabic name of an account in Arabic", () => {
    // R3.AC4
    table("ar");
    expect(screen.getByText("الذمم المدينة التجارية")).toBeInTheDocument();
  });
});
