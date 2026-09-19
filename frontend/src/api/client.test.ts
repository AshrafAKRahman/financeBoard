/** The one way to the API: same origin, typed refusals, and 401 as a sign-out (R9, R10). */
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, API_BASE, client, setUnauthenticatedHandler, toApiError, unwrap } from "./client";
import { server } from "@/test/server";

const me = () => unwrap(client.GET("/api/v1/auth/me", {}));

afterEach(() => setUnauthenticatedHandler(undefined));

describe("where requests go", () => {
  it("addresses the origin that served the page, and nowhere else", () => {
    // R10.AC3
    expect(API_BASE).toBe(window.location.origin);
  });

  it("sends the session cookie by sending it same-origin", async () => {
    // R10.AC3 — the cookie is HttpOnly; all this application can do is ask for it to be sent.
    let credentials: RequestCredentials | undefined;
    server.use(
      http.get("/api/v1/auth/me", ({ request }) => {
        credentials = request.credentials;
        return HttpResponse.json({ id: "x", email: "a@b.sa", name: "A", companies: [] });
      }),
    );

    await me();

    expect(credentials).toBe("same-origin");
  });
});

describe("reading a refusal", () => {
  it("carries the API's own code and words", async () => {
    // R9.AC1, R9.AC2
    server.use(
      http.get("/api/v1/auth/me", () =>
        HttpResponse.json(
          { code: "authz.forbidden", title: "Not permitted", detail: "You may not read reports." },
          { status: 403 },
        ),
      ),
    );

    const failure = await me().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      status: 403,
      code: "authz.forbidden",
      detail: "You may not read reports.",
      isForbidden: true,
    });
  });

  it("says something went wrong when the body explains nothing", async () => {
    // R9.AC3, R9.AC6 — a person is never shown a bare status code.
    server.use(http.get("/api/v1/auth/me", () => new HttpResponse(null, { status: 500 })));

    const failure = (await me().catch((error: unknown) => error)) as ApiError;

    expect(failure.status).toBe(500);
    expect(failure.code).toBeUndefined();
    expect(failure.message).toMatch(/failed/i);
  });

  it("tells an unreachable network apart from a server that refused", () => {
    // R9.AC4
    const offline = toApiError(0, undefined);
    const refused = toApiError(403, { code: "authz.forbidden" });

    expect(offline.isOffline).toBe(true);
    expect(offline.title).toBe("Cannot reach the server");
    expect(refused.isOffline).toBe(false);
  });

  it("treats a fetch that never returned as unreachable", async () => {
    // R9.AC4
    server.use(http.get("/api/v1/auth/me", () => HttpResponse.error()));

    const failure = (await me().catch((error: unknown) => error)) as ApiError;

    expect(failure.isOffline).toBe(true);
  });
});

describe("a session that has gone", () => {
  it("calls the sign-out handler once, and still throws", async () => {
    // R1.AC6
    const signedOut = vi.fn();
    setUnauthenticatedHandler(signedOut);
    server.use(http.get("/api/v1/auth/me", () => new HttpResponse(null, { status: 401 })));

    const failure = (await me().catch((error: unknown) => error)) as ApiError;

    expect(failure.isUnauthenticated).toBe(true);
    expect(signedOut).toHaveBeenCalledTimes(1);
  });

  it("leaves a 403 alone — being signed in but unauthorised is not signing out", async () => {
    // R9.AC1
    const signedOut = vi.fn();
    setUnauthenticatedHandler(signedOut);
    server.use(http.get("/api/v1/auth/me", () => new HttpResponse(null, { status: 403 })));

    await me().catch(() => undefined);

    expect(signedOut).not.toHaveBeenCalled();
  });
});

describe("a success with nothing to say", () => {
  it("accepts 204, because signing in answers with no body", async () => {
    // R1.AC1
    await expect(
      unwrap(client.POST("/api/v1/auth/login", { body: { email: "a@b.sa", password: "x" } })),
    ).resolves.toBeUndefined();
  });
});
