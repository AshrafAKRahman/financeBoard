/** Arabic, and the layout that mirrors with it (R3). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { STORAGE_KEY } from "@/i18n";
import TrialBalance from "@/reports/TrialBalance";
import { COMPANY_ID, renderScreen } from "@/test/harness";

import { AppShell } from "./AppShell";

const at = (report: string) => ({
  route: `/companies/:companyId/reports/${report}`,
  path: `/companies/${COMPANY_ID}/reports/${report}`,
});

const inShell = (locale: "en" | "ar" = "en") =>
  renderScreen(<AppShell />, {
    route: "/companies/:companyId/*",
    path: `/companies/${COMPANY_ID}/reports/trial-balance`,
    locale,
  });

describe("changing language", () => {
  it("mirrors the layout and keeps the screen", async () => {
    // R3.AC3, R3.AC6
    const user = userEvent.setup();
    const { router } = inShell();
    await screen.findByText(/Test Accountant/);
    const before = router.state.location.pathname;

    await user.click(screen.getByRole("button", { name: /العربية/ }));

    await waitFor(() => expect(document.documentElement.dir).toBe("rtl"));
    expect(document.documentElement.lang).toBe("ar");
    expect(router.state.location.pathname).toBe(before);
  });

  it("remembers the choice and nothing else", async () => {
    // R3.AC7, NFR6
    const user = userEvent.setup();
    inShell();
    await screen.findByText(/Test Accountant/);

    await user.click(screen.getByRole("button", { name: /العربية/ }));

    await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toBe("ar"));
    expect(Object.keys(localStorage)).toEqual([STORAGE_KEY]);
  });

  it("shows the navigation in Arabic", async () => {
    // R3.AC2
    inShell("ar");
    expect(await screen.findByRole("link", { name: "ميزان المراجعة" })).toBeInTheDocument();
  });
});

describe("Arabic figures and names", () => {
  it("shows an account's Arabic name, and its English one where there is none", async () => {
    // R3.AC4
    renderScreen(<TrialBalance />, { ...at("trial-balance"), locale: "ar" });

    expect(await screen.findByText("الذمم المدينة التجارية")).toBeInTheDocument();
    // `name_ar: null` on this row — the English name stands in rather than a blank.
    expect(screen.getByText("Assets")).toBeInTheDocument();
  });

  it("keeps every figure and date reading left to right", async () => {
    // R3.AC5
    renderScreen(<TrialBalance />, { ...at("trial-balance"), locale: "ar" });
    await screen.findByText("الذمم المدينة التجارية");

    const figures = document.querySelectorAll<HTMLElement>("span.amount");
    expect(figures.length).toBeGreaterThan(0);
    for (const figure of figures) {
      expect(figure.getAttribute("dir")).toBe("ltr");
    }
  });
});
