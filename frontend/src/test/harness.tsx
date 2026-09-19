/**
 * Rendering a screen the way the browser will, with the API mocked from its own schema.
 *
 * The fixtures below are typed as the generated response types, so a mock cannot drift from
 * the API any more than a screen can (R10.AC1). If the backend renames a field, these stop
 * compiling.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import type {
  AccountDetail,
  Aged,
  BalanceSheet,
  CashFlow,
  ProfitAndLoss,
  ReportMeta,
  ReportRow,
  TrialBalance,
  VatReturn,
} from "@/api/reports";
import type { Me } from "@/api/session";
import i18n, { applyLocale } from "@/i18n";
import type { Locale } from "@/i18n";

export const COMPANY_ID = "01a0b5af-f97f-726c-88c8-677c734968b6";

export const meta: ReportMeta = {
  report: "trial-balance",
  company_id: COMPANY_ID,
  company_name: "Riyadh Trading Co",
  currency_code: "SAR",
  period_start: "2026-01-01",
  period_end: "2026-12-31",
  period_label: "Fiscal year 2026",
  generated_at: "2026-09-19T08:42:11.123456+00:00",
};

export const me: Me = {
  id: "01a0b000-0000-7000-8000-000000000001",
  email: "accountant@example.sa",
  name: "Test Accountant",
  companies: [{ company_id: COMPANY_ID, name: "Riyadh Trading Co", permissions: ["report:read"] }],
};

export function row(partial: Partial<ReportRow> & { name: string }): ReportRow {
  return {
    account_id: null,
    code: null,
    name_ar: null,
    level: 0,
    is_group: false,
    opening: "0.000000",
    debit: "0.000000",
    credit: "0.000000",
    closing: "0.000000",
    children: [],
    ...partial,
  };
}

export const receivable = row({
  account_id: "01a0b5af-1111-7000-8000-000000000001",
  code: "1200",
  name: "Trade Receivables",
  name_ar: "الذمم المدينة التجارية",
  debit: "26450.000000",
  credit: "17250.000000",
  closing: "9200.000000",
});

export const revenue = row({
  account_id: "01a0b5af-1111-7000-8000-000000000002",
  code: "4100",
  name: "Sales Revenue",
  name_ar: "إيرادات المبيعات",
  credit: "23000.000000",
  closing: "-23000.000000",
});

export const trialBalance: TrialBalance = {
  meta,
  rows: [
    row({
      account_id: "01a0b5af-1111-7000-8000-000000000010",
      code: "1",
      name: "Assets",
      is_group: true,
      debit: "26450.000000",
      credit: "17250.000000",
      closing: "9200.000000",
      children: [receivable],
    }),
    revenue,
  ],
  total_debit: "60950.000000",
  total_credit: "60950.000000",
  balances: true,
};

export const profitAndLoss: ProfitAndLoss = {
  meta: { ...meta, report: "profit-and-loss" },
  income: [revenue],
  expenses: [
    row({
      account_id: "01a0b5af-1111-7000-8000-000000000003",
      code: "5300",
      name: "Rent",
      debit: "4000.000000",
      closing: "4000.000000",
    }),
  ],
  total_income: "23000.000000",
  cost_of_revenue: "0.000000",
  other_expenses: "4000.000000",
  gross_profit: "23000.000000",
  net_result: "19000.000000",
  comparison: null,
};

export const balanceSheet: BalanceSheet = {
  meta: { ...meta, report: "balance-sheet" },
  assets: [receivable],
  liabilities: [
    row({ code: "2200", name: "VAT Output", closing: "-3450.000000", credit: "3450.000000" }),
  ],
  equity: [],
  total_assets: "26450.000000",
  total_liabilities: "3450.000000",
  posted_equity: "0.000000",
  retained_earnings: "4000.000000",
  current_year_earnings: "19000.000000",
  total_equity: "23000.000000",
  balances: true,
};

export const cashFlow: CashFlow = {
  meta: { ...meta, report: "cash-flow" },
  opening_cash: "0.000000",
  sections: [
    {
      classification: "operating",
      lines: [
        {
          account_id: "01a0b5af-1111-7000-8000-000000000004",
          code: "1200",
          name: "Trade Receivables",
          name_ar: "الذمم المدينة التجارية",
          amount: "17250.000000",
        },
      ],
      total: "17250.000000",
    },
    { classification: "investing", lines: [], total: "0.000000" },
    { classification: "financing", lines: [], total: "0.000000" },
    { classification: "unclassified", lines: [], total: "0.000000" },
  ],
  net_movement: "17250.000000",
  closing_cash: "17250.000000",
  reconciles: true,
};

export const aged: Aged = {
  meta: { ...meta, report: "aged-receivables" },
  side: "receivable",
  partners: [
    {
      partner_id: "01a0b5af-2222-7000-8000-000000000001",
      partner_name: "Al Noor Est",
      buckets: {
        current: "0.000000",
        "1-30": "9200.000000",
        "31-60": "0.000000",
        "61-90": "0.000000",
        "90+": "0.000000",
      },
      total: "9200.000000",
      items: [],
    },
  ],
  buckets: {
    current: "0.000000",
    "1-30": "9200.000000",
    "31-60": "0.000000",
    "61-90": "0.000000",
    "90+": "0.000000",
  },
  total: "9200.000000",
};

export const vatReturn: VatReturn = {
  meta: { ...meta, report: "vat-return" },
  sales: [
    {
      number: 1,
      name: "Standard rated sales",
      name_ar: "المبيعات الخاضعة للنسبة الأساسية",
      side: "sales",
      net: "23000.000000",
      tax: "3450.000000",
    },
  ],
  purchases: [],
  untagged: [],
  total_sales_net: "23000.000000",
  output_tax: "3450.000000",
  total_purchases_net: "0.000000",
  input_tax: "0.000000",
  net_tax_due: "3450.000000",
};

export const accountDetail: AccountDetail = {
  meta: { ...meta, report: "account-detail" },
  account_id: receivable.account_id!,
  code: "1200",
  name: "Trade Receivables",
  name_ar: "الذمم المدينة التجارية",
  opening_balance: "0.000000",
  lines: [
    {
      line_id: "01a0b5af-3333-7000-8000-000000000001",
      entry_id: "01a0b5af-4444-7000-8000-000000000001",
      entry_number: "INV/2026/00001",
      entry_date: "2026-03-01",
      journal_code: "INV",
      partner_id: "01a0b5af-2222-7000-8000-000000000001",
      partner_name: "Al Noor Est",
      description: "Consultancy",
      document_number: "INV/2026/00001",
      debit: "17250.000000",
      credit: "0.000000",
      running_balance: "17250.000000",
    },
  ],
  total_debit: "17250.000000",
  total_credit: "0.000000",
  closing_balance: "17250.000000",
};

export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

/** Render a screen inside the router, the query client, i18n and Ant Design. */
export function renderScreen(
  element: ReactElement,
  options: {
    path?: string;
    route?: string;
    locale?: Locale;
    queryClient?: QueryClient;
  } = {},
) {
  const {
    route = "/companies/:companyId/reports/trial-balance",
    path = `/companies/${COMPANY_ID}/reports/trial-balance`,
    locale = "en",
    queryClient = makeTestQueryClient(),
  } = options;

  void i18n.changeLanguage(locale);
  applyLocale(locale);

  const router = createMemoryRouter(
    [
      { path: route, element },
      { path: "*", element: <div>elsewhere</div> },
    ],
    { initialEntries: [path] },
  );

  return {
    queryClient,
    router,
    ...render(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <ConfigProvider direction={locale === "ar" ? "rtl" : "ltr"}>
            <RouterProvider router={router} />
          </ConfigProvider>
        </I18nextProvider>
      </QueryClientProvider>,
    ),
  };
}
