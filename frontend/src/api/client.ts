/**
 * The one way this application talks to the API.
 *
 * Same origin, so the session cookie is sent and no CORS is involved (R10.AC3). Every failure
 * becomes an `ApiError` carrying the API's own problem-details code, so a screen can say what
 * was refused rather than "something went wrong" (R9).
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * The page's own origin, which is where the API is (decision D16).
 *
 * The schema's paths already carry `/api/v1` and are used verbatim, so nothing rewrites the
 * generated types. The origin is named explicitly rather than left relative because Node's
 * `fetch` — which jsdom uses under test — requires an absolute URL where a browser does not.
 * Naming it also states the intent: requests go to the origin that served this page, never
 * anywhere else.
 */
export const API_BASE =
  typeof window === "undefined" ? "http://localhost" : window.location.origin;

/** A refusal the API explained, or a failure we could not read. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly title: string | undefined;
  readonly detail: string | undefined;

  constructor(init: {
    status: number;
    code?: string | undefined;
    title?: string | undefined;
    detail?: string | undefined;
  }) {
    super(init.detail ?? init.title ?? `Request failed with status ${init.status}`);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.title = init.title;
    this.detail = init.detail;
  }

  /** R1.AC6 — the session has gone, so this is a sign-out rather than an error. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** R9.AC1 — signed in, but not allowed to read this. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  /** R9.AC4 — the request never reached a server. */
  get isOffline(): boolean {
    return this.status === 0;
  }
}

type ProblemDetails = {
  code?: unknown;
  title?: unknown;
  detail?: unknown;
};

function asText(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/** Turn whatever came back into something a screen can show (R9.AC2, R9.AC6). */
export function toApiError(status: number, body: unknown): ApiError {
  if (status === 0) {
    return new ApiError({
      status: 0,
      code: "network.unreachable",
      title: "Cannot reach the server",
    });
  }
  const problem = (body ?? {}) as ProblemDetails;
  return new ApiError({
    status,
    code: asText(problem.code),
    title: asText(problem.title),
    detail: asText(problem.detail),
  });
}

/** Called when the session has gone, so the shell can show the sign-in form (R1.AC6). */
let onUnauthenticated: (() => void) | undefined;

export function setUnauthenticatedHandler(handler: (() => void) | undefined): void {
  onUnauthenticated = handler;
}

export const client = createClient<paths>({
  baseUrl: API_BASE,
  // The cookie is HttpOnly and SameSite=Lax, so this only works same-origin — which is the
  // whole reason the API serves this application (decision D16).
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  // Look `fetch` up when the request is made, not when this module is first imported.
  // Anything that replaces the global afterwards — a test's network mock, a browser
  // extension — is then honoured instead of being captured too early and ignored.
  fetch: (request) => globalThis.fetch(request),
});

/**
 * Unwrap an `openapi-fetch` result: return the data, or throw an `ApiError`.
 *
 * Every hook goes through here, so 401 handling and problem-details parsing exist once.
 */
export async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let settled: { data?: T; error?: unknown; response: Response };
  try {
    settled = await result;
  } catch {
    throw toApiError(0, undefined);
  }

  const { data, error, response } = settled;
  // Signing in and out answer 204: success, and nothing to say. An empty body is not a
  // failure, so the response's own verdict decides, not the presence of data.
  if (response.ok) {
    return data as T;
  }

  const failure = toApiError(response.status, error);
  if (failure.isUnauthenticated) {
    onUnauthenticated?.();
  }
  throw failure;
}
