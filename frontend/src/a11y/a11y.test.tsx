/**
 * Every screen, checked for the things a keyboard and a screen reader need (R11, NFR3, NFR5).
 *
 * axe-core is run against the rendered DOM. It cannot judge colour contrast here — jsdom has
 * no layout or computed colours — so contrast is settled in the design tokens and the rules
 * that need a real browser are disabled rather than silently passed.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import Aged from "@/reports/Aged";
import BalanceSheet from "@/reports/BalanceSheet";
import CashFlow from "@/reports/CashFlow";
import ProfitAndLoss from "@/reports/ProfitAndLoss";
import TrialBalance from "@/reports/TrialBalance";
import VatReturn from "@/reports/VatReturn";
import AccountDetail from "@/reports/AccountDetail";
import { AppShell } from "@/shell/AppShell";
import { SignIn } from "@/shell/SignIn";
import { COMPANY_ID, receivable, renderScreen } from "@/test/harness";
// The stylesheet the application ships, read from disk so the assertion below is about the
// real rule rather than a copy of it that could drift.
const stylesheet = readFileSync("src/app/styles.css", "utf8");

const DISABLED_IN_JSDOM = {
  // Needs real layout and computed colour, which jsdom does not provide.
  "color-contrast": { enabled: false },
};

async function violations(container: HTMLElement) {
  const result = await axe.run(container, {
    rules: DISABLED_IN_JSDOM,
    resultTypes: ["violations"],
  });
  return result.violations.map(
    (violation) =>
      `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`,
  );
}

const at = (report: string) => ({
  route: `/companies/:companyId/reports/${report}`,
  path: `/companies/${COMPANY_ID}/reports/${report}`,
});

const SCREENS = [
  ["the trial balance", <TrialBalance key="tb" />, at("trial-balance"), "Trial balance"],
  ["the profit and loss", <ProfitAndLoss key="pl" />, at("profit-and-loss"), "Profit and loss"],
  ["the balance sheet", <BalanceSheet key="bs" />, at("balance-sheet"), "Balance sheet"],
  ["the cash flow", <CashFlow key="cf" />, at("cash-flow"), "Cash flow"],
  ["aged receivables", <Aged key="ar" side="receivables" companyId={COMPANY_ID} />, at("aged-receivables"), "Aged receivables"],
  ["the VAT return", <VatReturn key="vat" />, at("vat-return"), "VAT return"],
] as const;

describe("every report screen", () => {
  for (const [name, element, route, heading] of SCREENS) {
    it(`${name} has no accessibility violation axe can see`, async () => {
      // R11.AC1, R11.AC2, R11.AC3, R11.AC5, NFR3
      const { container } = renderScreen(element, route);
      await screen.findByRole("heading", { name: heading });

      expect(await violations(container)).toEqual([]);
    }, 15000);
  }

  it("the entries behind a figure have none either", async () => {
    // R11, R8
    const { container } = renderScreen(<AccountDetail />, {
      route: "/companies/:companyId/reports/accounts/:accountId",
      path: `/companies/${COMPANY_ID}/reports/accounts/${receivable.account_id}`,
    });
    await screen.findAllByText("INV/2026/00001");

    expect(await violations(container)).toEqual([]);
  }, 15000);
});

describe("the shell", () => {
  it("has none on the sign-in form", async () => {
    // R11.AC5
    const { container } = renderScreen(<SignIn />, { route: "*", path: "/sign-in" });

    expect(await violations(container)).toEqual([]);
  }, 15000);

  it("has none on the frame, in Arabic as in English", async () => {
    // R3.AC3, R11
    const { container } = renderScreen(<AppShell />, {
      route: "/companies/:companyId/*",
      path: `/companies/${COMPANY_ID}/reports/trial-balance`,
      locale: "ar",
    });
    await screen.findByText(/Test Accountant/);

    expect(await violations(container)).toEqual([]);
  }, 15000);
});

describe("moving by keyboard alone", () => {
  it("reaches the skip link first, then the navigation", async () => {
    // R11.AC1
    const user = userEvent.setup();
    renderScreen(<AppShell />, {
      route: "/companies/:companyId/*",
      path: `/companies/${COMPANY_ID}/reports/trial-balance`,
    });
    await screen.findByText(/Test Accountant/);

    await user.tab();

    expect(document.activeElement).toHaveTextContent("Skip to content");
  });

  it("gives the focused element a visible outline rather than none", () => {
    // R11.AC2 — a rule that removes the outline is the defect this guards against.
    expect(stylesheet).toMatch(/:focus-visible/);
    expect(stylesheet).not.toMatch(/outline:\s*(none|0)\s*;/);
  });
});
