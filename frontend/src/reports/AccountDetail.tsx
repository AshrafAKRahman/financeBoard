/** The entries behind a figure (R8). */
import { Button, Table } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { useAccountDetail } from "@/api/reports";
import type { AccountDetail as AccountDetailData } from "@/api/reports";
import type { Locale } from "@/i18n";
import { formatDate } from "@/money/format";
import { PeriodControl, usePeriod } from "@/periods/PeriodControl";

import { TotalRow } from "./HierarchyTable";
import { Amount, ReportHeader, ReportState } from "./shared";

type Line = AccountDetailData["lines"][number];

export default function AccountDetail() {
  const { t, i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";
  const { companyId = "", accountId = "" } = useParams();
  const navigate = useNavigate();
  const [period] = usePeriod();
  const report = useAccountDetail(companyId, accountId, period);
  const currency = report.data?.meta.currency_code ?? "SAR";

  const title = report.data
    ? `${report.data.code} ${locale === "ar" && report.data.name_ar ? report.data.name_ar : report.data.name}`
    : t("reports.accountDetail");

  return (
    <>
      <ReportHeader title={title} meta={report.data?.meta}>
        <PeriodControl
          extra={
            // R8.AC4 — back to the report, where they were reading.
            <Button onClick={() => navigate(-1)}>{t("app.back")}</Button>
          }
        />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.lines.length === 0}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            <TotalRow
              label={t("reports.openingBalance")}
              value={report.data.opening_balance}
              currency={currency}
            />

            <Table<Line>
              rowKey={(line) => line.line_id}
              dataSource={report.data.lines}
              pagination={false}
              size="small"
              columns={[
                {
                  title: t("reports.date"),
                  dataIndex: "entry_date",
                  width: 120,
                  render: (value: string) => formatDate(value, locale),
                },
                { title: t("reports.entry"), dataIndex: "entry_number", width: 160 },
                { title: t("reports.document"), dataIndex: "document_number", width: 160 },
                { title: t("reports.partner"), dataIndex: "partner_name" },
                { title: t("reports.description"), dataIndex: "description" },
                {
                  title: t("reports.debit"),
                  dataIndex: "debit",
                  align: "end",
                  width: 130,
                  render: (value: string) => <Amount value={value} currency={currency} />,
                },
                {
                  title: t("reports.credit"),
                  dataIndex: "credit",
                  align: "end",
                  width: 130,
                  render: (value: string) => <Amount value={value} currency={currency} />,
                },
                {
                  title: t("reports.runningBalance"),
                  dataIndex: "running_balance",
                  align: "end",
                  width: 150,
                  render: (value: string) => (
                    <Amount value={value} currency={currency} dashOnZero={false} />
                  ),
                },
              ]}
            />

            {/* R8.AC5 — comparable with the figure that was clicked. */}
            <TotalRow
              label={t("reports.closingBalance")}
              value={report.data.closing_balance}
              currency={currency}
              tone="strong"
            />
          </>
        ) : null}
      </ReportState>
    </>
  );
}
