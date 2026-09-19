/** Clicking a figure through to the entries behind it (R8). */
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AccountDetail from "./AccountDetail";
import { COMPANY_ID, receivable, renderScreen } from "@/test/harness";
import { refuse } from "@/test/server";

describe("the entries behind a figure", () => {
  const detail = {
    route: "/companies/:companyId/reports/accounts/:accountId",
    path: `/companies/${COMPANY_ID}/reports/accounts/${receivable.account_id}`,
  };

  it("shows each line with its running balance", async () => {
    // R8.AC2
    renderScreen(<AccountDetail />, detail);

    expect(await screen.findAllByText("INV/2026/00001")).not.toHaveLength(0);
    expect(screen.getByText("Consultancy")).toBeInTheDocument();
    expect(screen.getByText("Al Noor Est")).toBeInTheDocument();
    expect(screen.getAllByText("17,250.00").length).toBeGreaterThan(0);
  });

  it("names the document a line came from", async () => {
    // R8.AC3
    renderScreen(<AccountDetail />, detail);
    await waitFor(() =>
      expect(screen.getAllByText("INV/2026/00001").length).toBeGreaterThanOrEqual(2),
    );
  });

  it("shows the closing balance, to compare with the figure that was clicked", async () => {
    // R8.AC5
    renderScreen(<AccountDetail />, detail);
    expect(await screen.findByText("Closing balance")).toBeInTheDocument();
  });

  it("offers the way back to the report", async () => {
    // R8.AC4
    renderScreen(<AccountDetail />, detail);
    expect(await screen.findByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("says plainly when an account is gone", async () => {
    // R9.AC2
    refuse("/api/v1/companies/:companyId/reports/accounts/:accountId/detail", 404);
    renderScreen(<AccountDetail />, detail);

    expect(
      await screen.findByText("That is no longer here.", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
  });
});
