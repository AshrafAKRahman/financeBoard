/**
 * The API, mocked at the network boundary.
 *
 * Responses are the generated types, so a mock cannot claim a shape the API does not have.
 * Screens go through their real query hooks and their real client, so what is being tested is
 * the screen's wiring, not a stub of it.
 */
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import {
  accountDetail,
  aged,
  balanceSheet,
  cashFlow,
  me,
  profitAndLoss,
  trialBalance,
  vatReturn,
} from "./harness";

const company = "/api/v1/companies/:companyId";

export const handlers = [
  http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
  http.post("/api/v1/auth/login", () => new HttpResponse(null, { status: 204 })),
  http.post("/api/v1/auth/logout", () => new HttpResponse(null, { status: 204 })),
  http.get(`${company}/reports/trial-balance`, () => HttpResponse.json(trialBalance)),
  http.get(`${company}/reports/profit-and-loss`, () => HttpResponse.json(profitAndLoss)),
  http.get(`${company}/reports/balance-sheet`, () => HttpResponse.json(balanceSheet)),
  http.get(`${company}/reports/cash-flow`, () => HttpResponse.json(cashFlow)),
  http.get(`${company}/reports/aged-receivables`, () => HttpResponse.json(aged)),
  http.get(`${company}/reports/aged-payables`, () =>
    HttpResponse.json({ ...aged, side: "payable" }),
  ),
  http.get(`${company}/reports/vat-return`, () => HttpResponse.json(vatReturn)),
  http.get(`${company}/reports/accounts/:accountId/detail`, () =>
    HttpResponse.json(accountDetail),
  ),
];

export const server = setupServer(...handlers);

/** A refusal, for the screens that have to explain one. */
export function refuse(path: string, status: number, body?: unknown) {
  server.use(
    http.get(path, () =>
      body === undefined
        ? new HttpResponse(null, { status })
        : HttpResponse.json(body, { status }),
    ),
  );
}
