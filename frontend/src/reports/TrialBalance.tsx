/** The trial balance (R1, R5). */
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useTrialBalance } from "@/api/reports";
import type { Locale } from "@/i18n";
import { PeriodControl, usePeriod } from "@/periods/PeriodControl";

import { BalanceTag, HierarchyTable, TotalRow } from "./HierarchyTable";
import { ReportHeader, ReportState } from "./shared";

export default function TrialBalance() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";
  const { companyId = "" } = useParams();
  const [period] = usePeriod();
  const report = useTrialBalance(companyId, period);

  const currency = report.data?.meta.currency_code ?? "SAR";

  return (
    <>
      <ReportHeader title={t("reports.trialBalance")} meta={report.data?.meta}>
        <PeriodControl
          extra={
            report.data ? (
              <BalanceTag
                balances={report.data.balances}
                yes={t("reports.balances")}
                no={t("reports.doesNotBalance")}
              />
            ) : null
          }
        />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.rows.length === 0}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            <HierarchyTable
              rows={report.data.rows}
              currency={currency}
              period={period}
              locale={locale}
              columns={[
                { key: "opening", label: t("reports.opening") },
                { key: "debit", label: t("reports.debit") },
                { key: "credit", label: t("reports.credit") },
                { key: "closing", label: t("reports.closing") },
              ]}
            />
            <TotalRow
              label={`${t("reports.total")} — ${t("reports.debit")}`}
              value={report.data.total_debit}
              currency={currency}
              tone="strong"
            />
            <TotalRow
              label={`${t("reports.total")} — ${t("reports.credit")}`}
              value={report.data.total_credit}
              currency={currency}
              tone="strong"
            />
          </>
        ) : null}
      </ReportState>
    </>
  );
}
