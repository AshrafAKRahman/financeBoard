/** Signing in, signing out, and a session that has gone (R1, R9.AC4, R11.AC5). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { setUnauthenticatedHandler } from "@/api/client";
import { STORAGE_KEY } from "@/i18n";
import { COMPANY_ID, renderScreen } from "@/test/harness";
import { server } from "@/test/server";

import { AppShell } from "./AppShell";
import { SignIn } from "./SignIn";

const inShell = (locale: "en" | "ar" = "en") =>
  renderScreen(<AppShell />, {
    route: "/companies/:companyId/*",
    path: `/companies/${COMPANY_ID}/reports/trial-balance`,
    locale,
  });

describe("signing in", () => {
  it("starts a session and opens the application", async () => {
    // R1.AC1
    const user = userEvent.setup();
    const onSignedIn = vi.fn();
    renderScreen(<SignIn onSignedIn={onSignedIn} />, { route: "*", path: "/sign-in" });

    await user.type(screen.getByLabelText("Email"), "accountant@example.sa");
    await user.type(screen.getByLabelText("Password"), "a-long-enough-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
  });

  it("says the credentials were refused without saying which part", async () => {
    // R1.AC2
    server.use(
      http.post("/api/v1/auth/login", () =>
        HttpResponse.json({ code: "identity.invalid_credentials" }, { status: 401 }),
      ),
    );
    const user = userEvent.setup();
    renderScreen(<SignIn />, { route: "*", path: "/sign-in" });

    await user.type(screen.getByLabelText("Email"), "accountant@example.sa");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const message = await screen.findByText("Those credentials were not accepted.");
    expect(message).toBeInTheDocument();
    expect(message.textContent).not.toMatch(/email|password/i);
  });

  it("says so when the server cannot be reached", async () => {
    // R9.AC4
    server.use(http.post("/api/v1/auth/login", () => HttpResponse.error()));
    const user = userEvent.setup();
    renderScreen(<SignIn />, { route: "*", path: "/sign-in" });

    await user.type(screen.getByLabelText("Email"), "a@b.sa");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText(/check your connection/)).toBeInTheDocument();
  });

  it("keeps nothing of the session in browser storage", () => {
    // R1.AC7, R1.AC8, NFR6
    renderScreen(<SignIn />, { route: "*", path: "/sign-in" });
    expect(Object.keys(localStorage).filter((key) => key !== STORAGE_KEY)).toEqual([]);
    expect(Object.keys(sessionStorage)).toEqual([]);
  });

  it("has a label on every input", () => {
    // R11.AC5
    renderScreen(<SignIn />, { route: "*", path: "/sign-in" });
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});

describe("a session that has gone", () => {
  it("tells the application to show the sign-in form", async () => {
    // R1.AC6
    const onUnauthenticated = vi.fn();
    setUnauthenticatedHandler(onUnauthenticated);
    server.use(http.get("/api/v1/auth/me", () => new HttpResponse(null, { status: 401 })));

    inShell();

    await waitFor(() => expect(onUnauthenticated).toHaveBeenCalled());
    setUnauthenticatedHandler(undefined);
  });
});

describe("signing out", () => {
  it("ends the session and forgets every figure", async () => {
    // R1.AC5, NFR6
    const user = userEvent.setup();
    const { queryClient } = inShell();
    await screen.findByText(/Test Accountant/);
    queryClient.setQueryData(["reports", COMPANY_ID, "trial-balance"], { secret: true });

    await user.click(screen.getByRole("button", { name: /Sign out/ }));

    await waitFor(() => expect(queryClient.getQueryCache().getAll()).toHaveLength(0));
  });
});
