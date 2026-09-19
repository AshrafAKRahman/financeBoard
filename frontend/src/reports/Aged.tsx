/** Who owes what and for how long (R5, R7.AC2). */
import { Table } from "antd";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";

import { useAged } from "@/api/reports";
import { BarChart } from "@/charts/Charts";
import type { Locale } from "@/i18n";
import { directionOf } from "@/i18n";
import { PeriodControl, usePeriod } from "@/periods/PeriodControl";

import { TotalRow } from "./HierarchyTable";
import { Amount, ReportHeader, ReportState } from "./shared";

const BUCKETS = ["current", "1-30", "31-60", "61-90", "90+"] as const;

export default function Aged({
  side,
  companyId,
}: {
  side: "receivables" | "payables";
  companyId: string;
}) {
  const { t, i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";
  const [period] = usePeriod();
  const on = period.kind === "on" ? period.on : dayjs().format("YYYY-MM-DD");
  const report = useAged(companyId, side, on);
  const currency = report.data?.meta.currency_code ?? "SAR";

  const title = side === "receivables" ? t("reports.agedReceivables") : t("reports.agedPayables");

  return (
    <>
      <ReportHeader title={title} meta={report.data?.meta}>
        <PeriodControl mode="on" />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.partners.length === 0}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            <BarChart
              // R7.AC4 — the same figures the table below shows.
              points={BUCKETS.map((bucket) => ({
                label: bucket === "current" ? t("reports.current") : bucket,
                amount: report.data.buckets[bucket] ?? "0",
              }))}
              currency={currency}
              description={t("reports.receivablesByAge")}
              direction={directionOf(locale)}
            />

            <Table
              rowKey={(partner) => partner.partner_id ?? partner.partner_name}
              dataSource={report.data.partners}
              pagination={false}
              size="small"
              columns={[
                { title: t("reports.partner"), dataIndex: "partner_name" },
                ...BUCKETS.map((bucket) => ({
                  title: bucket === "current" ? t("reports.current") : bucket,
                  align: "end" as const,
                  width: 130,
                  render: (_: unknown, partner: { buckets: Record<string, string> }) => (
                    <Amount value={partner.buckets[bucket]} currency={currency} />
                  ),
                })),
                {
                  title: t("reports.total"),
                  dataIndex: "total",
                  align: "end" as const,
                  width: 150,
                  render: (value: string) => (
                    <Amount value={value} currency={currency} strong />
                  ),
                },
              ]}
            />

            <TotalRow
              label={t("reports.total")}
              value={report.data.total}
              currency={currency}
              tone="strong"
            />
          </>
        ) : null}
      </ReportState>
    </>
  );
}
