/** The balance sheet, with the earnings nobody posted (R3, R5.AC6). */
import { Typography } from "antd";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useBalanceSheet } from "@/api/reports";
import type { Locale } from "@/i18n";
import { PeriodControl, usePeriod } from "@/periods/PeriodControl";

import { BalanceTag, HierarchyTable, TotalRow } from "./HierarchyTable";
import { ReportHeader, ReportState } from "./shared";

export default function BalanceSheet() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";
  const { companyId = "" } = useParams();
  const [period] = usePeriod();
  const on = period.kind === "on" ? period.on : dayjs().format("YYYY-MM-DD");
  const report = useBalanceSheet(companyId, on);

  const currency = report.data?.meta.currency_code ?? "SAR";
  const columns = [{ key: "closing" as const, label: t("reports.closing") }];

  return (
    <>
      <ReportHeader title={t("reports.balanceSheet")} meta={report.data?.meta}>
        <PeriodControl
          mode="on"
          extra={
            report.data ? (
              <BalanceTag
                balances={report.data.balances}
                yes={t("reports.sheetBalances")}
                no={t("reports.sheetDoesNotBalance")}
              />
            ) : null
          }
        />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.assets.length === 0 && report.data?.liabilities.length === 0}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            <Typography.Title level={5}>{t("reports.assets")}</Typography.Title>
            <HierarchyTable
              rows={report.data.assets}
              currency={currency}
              period={period}
              locale={locale}
              columns={columns}
            />
            <TotalRow
              label={t("reports.assets")}
              value={report.data.total_assets}
              currency={currency}
              tone="strong"
            />

            <Typography.Title level={5}>{t("reports.liabilities")}</Typography.Title>
            <HierarchyTable
              rows={report.data.liabilities}
              currency={currency}
              period={period}
              locale={locale}
              columns={columns}
            />
            <TotalRow
              label={t("reports.liabilities")}
              value={report.data.total_liabilities}
              currency={currency}
              tone="strong"
            />

            <Typography.Title level={5}>{t("reports.equity")}</Typography.Title>
            <HierarchyTable
              rows={report.data.equity}
              currency={currency}
              period={period}
              locale={locale}
              columns={columns}
            />
            {/* Computed, never posted — decision D6. */}
            <TotalRow
              label={t("reports.retainedEarnings")}
              value={report.data.retained_earnings}
              currency={currency}
            />
            <TotalRow
              label={t("reports.currentYearEarnings")}
              value={report.data.current_year_earnings}
              currency={currency}
            />
            <TotalRow
              label={t("reports.equity")}
              value={report.data.total_equity}
              currency={currency}
              tone="strong"
            />
          </>
        ) : null}
      </ReportState>
    </>
  );
}
