/**
 * What this application leaves on the machine (NFR6).
 *
 * A controller checks figures on a borrowed laptop. Signing out has to leave nothing behind,
 * so the only thing ever written is which language to speak — never a figure, never a name,
 * never anything that identifies a company.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { STORAGE_KEY } from "@/i18n";
import TrialBalance from "@/reports/TrialBalance";
import { AppShell } from "@/shell/AppShell";
import { COMPANY_ID, renderScreen } from "@/test/harness";

const everythingStored = () =>
  [
    ...Object.entries({ ...localStorage }),
    ...Object.entries({ ...sessionStorage }),
  ] as [string, string][];

const at = {
  route: "/companies/:companyId/reports/trial-balance",
  path: `/companies/${COMPANY_ID}/reports/trial-balance`,
};

describe("what survives on the machine", () => {
  it("writes one key and one key only, whatever is on screen", async () => {
    // NFR6 — the language is the entire permitted footprint.
    renderScreen(<TrialBalance />, at);
    await screen.findByText("Trade Receivables");

    expect(everythingStored().map(([key]) => key)).toEqual([STORAGE_KEY]);
    expect(Object.keys(sessionStorage)).toEqual([]);
  });

  it("holds no figure from a report that has been read", async () => {
    // NFR6 — the figures live in memory, which signing out empties.
    renderScreen(<TrialBalance />, at);
    await screen.findByText("Trade Receivables");

    const written = everythingStored()
      .map(([, value]) => value)
      .join(" ");
    for (const secret of ["11500", "Riyadh Trading Co", "Trade Receivables", COMPANY_ID]) {
      expect(written).not.toContain(secret);
    }
  });

  it("keeps nothing but the language after a language is chosen", async () => {
    // R3.AC7 with NFR6 — a preference is not a figure.
    const user = userEvent.setup();
    renderScreen(<AppShell />, {
      route: "/companies/:companyId/*",
      path: `/companies/${COMPANY_ID}/reports/trial-balance`,
    });
    await screen.findByText(/Test Accountant/);

    await user.click(screen.getByRole("button", { name: /العربية/ }));

    await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toBe("ar"));
    expect(everythingStored()).toEqual([[STORAGE_KEY, "ar"]]);
  });

  it("stores the session nowhere, because the session is a cookie it cannot read", async () => {
    // R1.AC7, R1.AC8
    renderScreen(<AppShell />, {
      route: "/companies/:companyId/*",
      path: `/companies/${COMPANY_ID}/reports/trial-balance`,
    });
    await screen.findByText(/Test Accountant/);

    const written = everythingStored()
      .map(([key, value]) => `${key}=${value}`)
      .join(" ");
    expect(written).not.toMatch(/token|session|bearer|jwt|accountant@/i);
  });
});
