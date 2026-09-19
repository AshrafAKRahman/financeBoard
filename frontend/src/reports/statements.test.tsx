/** Trial balance, profit and loss, balance sheet (R5, R6.AC6, R7.AC1). */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import BalanceSheet from "./BalanceSheet";
import ProfitAndLoss from "./ProfitAndLoss";
import TrialBalance from "./TrialBalance";
import { COMPANY_ID, renderScreen } from "@/test/harness";
import { refuse } from "@/test/server";

const at = (report: string) => ({
  route: `/companies/:companyId/reports/${report}`,
  path: `/companies/${COMPANY_ID}/reports/${report}`,
});

describe("the trial balance", () => {
  it("shows the figures and says the books balance", async () => {
    // R5.AC1, R5.AC5
    renderScreen(<TrialBalance />, at("trial-balance"));

    expect(await screen.findByText("Trade Receivables")).toBeInTheDocument();
    expect(screen.getByText("Debits equal credits")).toBeInTheDocument();
    expect(screen.getAllByText("60,950.00").length).toBeGreaterThan(0);
  });

  it("explains a refusal rather than showing an empty table", async () => {
    // R9.AC1
    refuse(`/api/v1/companies/:companyId/reports/trial-balance`, 403);
    renderScreen(<TrialBalance />, at("trial-balance"));

    expect(
      await screen.findByText("You do not have permission to read this.", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
  });
});

describe("the profit and loss", () => {
  it("shows income, expenses and the net result", async () => {
    // R5.AC1
    renderScreen(<ProfitAndLoss />, at("profit-and-loss"));

    expect(await screen.findByText("Sales Revenue")).toBeInTheDocument();
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getByText("Net result")).toBeInTheDocument();
    expect(screen.getByText("19,000.00")).toBeInTheDocument();
  });

  it("can be asked for the preceding period", async () => {
    // R6.AC6
    const user = userEvent.setup();
    renderScreen(<ProfitAndLoss />, at("profit-and-loss"));
    await screen.findByText("Sales Revenue");

    const toggle = screen.getByRole("button", { name: /Compare with the preceding period/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
  });
});

describe("the balance sheet", () => {
  it("shows the earnings nobody posted, and says it balances", async () => {
    // R5.AC6
    renderScreen(<BalanceSheet />, at("balance-sheet"));

    expect(await screen.findByText("Assets equal liabilities plus equity")).toBeInTheDocument();
    expect(screen.getByText("Current year earnings")).toBeInTheDocument();
    expect(screen.getByText("Retained earnings")).toBeInTheDocument();
  });
});
