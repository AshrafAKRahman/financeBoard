/** Cash flow, the aged reports, the VAT return (R5.AC1, R5.AC7, R7.AC2). */
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Aged from "./Aged";
import CashFlow from "./CashFlow";
import VatReturn from "./VatReturn";
import { COMPANY_ID, renderScreen } from "@/test/harness";

const at = (report: string) => ({
  route: `/companies/:companyId/reports/${report}`,
  path: `/companies/${COMPANY_ID}/reports/${report}`,
});

describe("the cash flow", () => {
  it("groups movements by what the cash was for", async () => {
    // R5.AC1
    renderScreen(<CashFlow />, at("cash-flow"));

    expect(await screen.findAllByRole("heading", { name: "Operating" })).not.toHaveLength(0);
    expect(screen.getByText("Closing cash")).toBeInTheDocument();
  });
});

describe("aged receivables", () => {
  it("shows each partner across the buckets", async () => {
    // R5.AC1
    renderScreen(<Aged side="receivables" companyId={COMPANY_ID} />, at("aged-receivables"));

    expect(await screen.findByText("Al Noor Est")).toBeInTheDocument();
    expect(screen.getAllByText("9,200.00").length).toBeGreaterThan(0);
  });

  it("charts the same figures as the table", async () => {
    // R7.AC2, R7.AC4
    renderScreen(<Aged side="receivables" companyId={COMPANY_ID} />, at("aged-receivables"));
    await screen.findByText("Al Noor Est");

    const chart = screen.getByRole("img", { name: /Receivables by age/ });
    expect(chart).toBeInTheDocument();

    const alternative = screen.getByRole("table", { name: /figures shown in the chart/i });
    expect(within(alternative).getByText("9,200.00")).toBeInTheDocument();
  });
});

describe("the VAT return", () => {
  it("labels every box with its ZATCA number and name", async () => {
    // R5.AC7
    renderScreen(<VatReturn />, at("vat-return"));

    expect(await screen.findByText("Standard rated sales")).toBeInTheDocument();
    expect(screen.getByText("Net tax due")).toBeInTheDocument();
    expect(screen.getAllByText("3,450.00").length).toBeGreaterThan(0);
  });
});
