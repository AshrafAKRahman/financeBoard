/** Profit and loss, with a chart of the months behind it (R2, R5, R7.AC1). */
import { Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useProfitAndLoss } from "@/api/reports";
import { LineChart } from "@/charts/Charts";
import type { ChartSeries } from "@/charts/Charts";
import type { Locale } from "@/i18n";
import { directionOf } from "@/i18n";
import { PeriodControl, Toggle, usePeriod } from "@/periods/PeriodControl";

import { HierarchyTable, TotalRow } from "./HierarchyTable";
import { ReportHeader, ReportState } from "./shared";

export default function ProfitAndLoss() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";
  const { companyId = "" } = useParams();
  const [period] = usePeriod();
  const [comparison, setComparison] = useState(false);
  const report = useProfitAndLoss(companyId, period, comparison);

  const currency = report.data?.meta.currency_code ?? "SAR";

  // R7.AC4 — the chart takes the report's own figures, and does no arithmetic of its own.
  const series: ChartSeries[] = report.data
    ? [
        {
          name: t("reports.income"),
          colour: "#0f5c46",
          points: report.data.income.map((row) => ({
            label: row.code ?? row.name,
            amount: row.credit,
          })),
        },
        {
          name: t("reports.expenses"),
          colour: "#8f5511",
          points: report.data.expenses.map((row) => ({
            label: row.code ?? row.name,
            amount: row.debit,
          })),
        },
      ]
    : [];

  return (
    <>
      <ReportHeader title={t("reports.profitAndLoss")} meta={report.data?.meta}>
        <PeriodControl
          extra={
            <Toggle pressed={comparison} onToggle={() => setComparison((on) => !on)}>
              {t("period.compare")}
            </Toggle>
          }
        />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.income.length === 0 && report.data?.expenses.length === 0}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            {series[0] && series[0].points.length >= 3 ? (
              <LineChart
                series={series}
                currency={currency}
                description={t("reports.incomeAndExpenses")}
                direction={directionOf(locale)}
              />
            ) : null}

            <Typography.Title level={5}>{t("reports.income")}</Typography.Title>
            <HierarchyTable
              rows={report.data.income}
              currency={currency}
              period={period}
              locale={locale}
              columns={[{ key: "credit", label: t("reports.total") }]}
            />

            <Typography.Title level={5}>{t("reports.expenses")}</Typography.Title>
            <HierarchyTable
              rows={report.data.expenses}
              currency={currency}
              period={period}
              locale={locale}
              columns={[{ key: "debit", label: t("reports.total") }]}
            />

            <TotalRow
              label={t("reports.costOfRevenue")}
              value={report.data.cost_of_revenue}
              currency={currency}
            />
            <TotalRow
              label={t("reports.grossProfit")}
              value={report.data.gross_profit}
              currency={currency}
              tone="strong"
            />
            <TotalRow
              label={t("reports.netResult")}
              value={report.data.net_result}
              currency={currency}
              tone="strong"
            />

            {report.data.comparison ? (
              <TotalRow
                label={`${t("reports.comparison")} — ${t("reports.netResult")}`}
                value={report.data.comparison.net_result}
                currency={currency}
              />
            ) : null}
          </>
        ) : null}
      </ReportState>
    </>
  );
}
