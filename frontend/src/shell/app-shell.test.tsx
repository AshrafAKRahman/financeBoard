/** The frame: who is signed in, which company, and the way to each report (R2, R11.AC1). */
import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { COMPANY_ID, me, renderScreen } from "@/test/harness";
import { server } from "@/test/server";

import { AppShell } from "./AppShell";

const inShell = (locale: "en" | "ar" = "en") =>
  renderScreen(<AppShell />, {
    route: "/companies/:companyId/*",
    path: `/companies/${COMPANY_ID}/reports/trial-balance`,
    locale,
  });

describe("the frame", () => {
  it("says who is signed in and which company is being viewed", async () => {
    // R2.AC1
    inShell();
    expect(await screen.findByText(/Test Accountant/)).toBeInTheDocument();
    expect(screen.getByText("Riyadh Trading Co")).toBeInTheDocument();
  });

  it("links to every report", async () => {
    // R2.AC4
    inShell();
    for (const name of [
      "Trial balance",
      "Profit and loss",
      "Balance sheet",
      "Cash flow",
      "Aged receivables",
      "Aged payables",
      "VAT return",
    ]) {
      expect(await screen.findByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("offers a way past the navigation for keyboard users", async () => {
    // R11.AC1
    inShell();
    expect(await screen.findByText("Skip to content")).toHaveAttribute("href", "#content");
  });

  it("shows no company switcher when there is only one company", async () => {
    // R2.AC2
    inShell();
    await screen.findByText(/Test Accountant/);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("offers a switcher when there is more than one company", async () => {
    // R2.AC2
    server.use(
      http.get("/api/v1/auth/me", () =>
        HttpResponse.json({
          ...me,
          companies: [
            ...me.companies,
            { company_id: "01a0b5af-9999-7000-8000-000000000009", name: "Jeddah Trading", permissions: ["report:read"] },
          ],
        }),
      ),
    );
    inShell();
    expect(await screen.findByRole("combobox")).toBeInTheDocument();
  });

  it("says plainly when a person belongs to no company", async () => {
    // R2.AC7
    server.use(
      http.get("/api/v1/auth/me", () => HttpResponse.json({ ...me, companies: [] })),
    );
    inShell();
    expect(
      await screen.findByText(/You do not belong to any company yet/),
    ).toBeInTheDocument();
  });
});
