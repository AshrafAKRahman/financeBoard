/**
 * One hook per report (R5, R10.AC4).
 *
 * Every key begins with the company, so changing company evicts that company's figures rather
 * than showing them under another company's name (R10.AC5). The period is part of the key, so
 * moving between periods is a fetch rather than a stale screen.
 */
import { useQuery } from "@tanstack/react-query";

import type { Period } from "@/periods/period";
import { periodKey, periodToQuery } from "@/periods/period";

import { client, unwrap } from "./client";
import type { components } from "./schema";

export type TrialBalance = components["schemas"]["TrialBalanceOut"];
export type ProfitAndLoss = components["schemas"]["ProfitAndLossOut"];
export type BalanceSheet = components["schemas"]["BalanceSheetOut"];
export type CashFlow = components["schemas"]["CashFlowOut"];
export type Aged = components["schemas"]["AgedOut"];
export type VatReturn = components["schemas"]["VatReturnOut"];
export type AccountDetail = components["schemas"]["AccountDetailOut"];
export type ReportRow = components["schemas"]["RowOut"];
export type ReportMeta = components["schemas"]["MetaOut"];

export const reportsKey = (companyId: string) => ["reports", companyId] as const;

const key = (companyId: string, report: string, period: Period, extra?: string) =>
  [...reportsKey(companyId), report, periodKey(period), extra ?? ""] as const;

/** Reports are read-only, so a failure is worth one retry and no more. */
const options = { retry: 1, staleTime: 60_000, placeholderData: keepPrevious } as const;

/** R9.AC5 — while a period is refetching, the figures already on screen stay. */
function keepPrevious<T>(previous: T | undefined): T | undefined {
  return previous;
}

export function useTrialBalance(
  companyId: string,
  period: Period,
  extras: { journalId?: string; hideUnused?: boolean } = {},
) {
  return useQuery({
    ...options,
    queryKey: key(companyId, "trial-balance", period, JSON.stringify(extras)),
    queryFn: () =>
      unwrap(
        client.GET("/api/v1/companies/{company_id}/reports/trial-balance", {
          params: {
            path: { company_id: companyId },
            query: {
              ...periodToQuery(period),
              ...(extras.journalId ? { journal_id: extras.journalId } : {}),
              hide_unused: extras.hideUnused ?? true,
            },
          },
        }),
      ),
  });
}

export function useProfitAndLoss(companyId: string, period: Period, comparison = false) {
  return useQuery({
    ...options,
    queryKey: key(companyId, "profit-and-loss", period, String(comparison)),
    queryFn: () =>
      unwrap(
        client.GET("/api/v1/companies/{company_id}/reports/profit-and-loss", {
          params: {
            path: { company_id: companyId },
            query: { ...periodToQuery(period), comparison },
          },
        }),
      ),
  });
}

export function useBalanceSheet(companyId: string, on: string) {
  return useQuery({
    ...options,
    queryKey: key(companyId, "balance-sheet", { kind: "on", on }),
    queryFn: () =>
      unwrap(
        client.GET("/api/v1/companies/{company_id}/reports/balance-sheet", {
          params: { path: { company_id: companyId }, query: { on } },
        }),
      ),
  });
}

export function useCashFlow(companyId: string, period: Period) {
  return useQuery({
    ...options,
    queryKey: key(companyId, "cash-flow", period),
    queryFn: () =>
      unwrap(
        client.GET("/api/v1/companies/{company_id}/reports/cash-flow", {
          params: { path: { company_id: companyId }, query: periodToQuery(period) },
        }),
      ),
  });
}

export function useAged(
  companyId: string,
  side: "receivables" | "payables",
  on: string,
  partnerId?: string,
) {
  const path =
    side === "receivables"
      ? ("/api/v1/companies/{company_id}/reports/aged-receivables" as const)
      : ("/api/v1/companies/{company_id}/reports/aged-payables" as const);
  return useQuery({
    ...options,
    queryKey: key(companyId, `aged-${side}`, { kind: "on", on }, partnerId ?? ""),
    queryFn: () =>
      unwrap(
        client.GET(path, {
          params: {
            path: { company_id: companyId },
            query: { on, ...(partnerId ? { partner_id: partnerId } : {}) },
          },
        }),
      ),
  });
}

export function useVatReturn(companyId: string, period: Period) {
  return useQuery({
    ...options,
    queryKey: key(companyId, "vat-return", period),
    queryFn: () =>
      unwrap(
        client.GET("/api/v1/companies/{company_id}/reports/vat-return", {
          params: { path: { company_id: companyId }, query: periodToQuery(period) },
        }),
      ),
  });
}

export function useAccountDetail(
  companyId: string,
  accountId: string,
  period: Period,
  partnerId?: string,
) {
  return useQuery({
    ...options,
    queryKey: key(companyId, `account-detail:${accountId}`, period, partnerId ?? ""),
    queryFn: () =>
      unwrap(
        client.GET("/api/v1/companies/{company_id}/reports/accounts/{account_id}/detail", {
          params: {
            path: { company_id: companyId, account_id: accountId },
            query: {
              ...periodToQuery(period),
              ...(partnerId ? { partner_id: partnerId } : {}),
            },
          },
        }),
      ),
  });
}
