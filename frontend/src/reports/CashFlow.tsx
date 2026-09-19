/** Where the cash went (R4, R5). */
import { Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useCashFlow } from "@/api/reports";
import { PeriodControl, usePeriod } from "@/periods/PeriodControl";

import { TotalRow } from "./HierarchyTable";
import { Amount, ReportHeader, ReportState } from "./shared";

export default function CashFlow() {
  const { t } = useTranslation();
  const { companyId = "" } = useParams();
  const [period] = usePeriod();
  const report = useCashFlow(companyId, period);
  const currency = report.data?.meta.currency_code ?? "SAR";

  return (
    <>
      <ReportHeader title={t("reports.cashFlow")} meta={report.data?.meta}>
        <PeriodControl />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.sections.every((section) => section.lines.length === 0)}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            <TotalRow
              label={t("reports.openingCash")}
              value={report.data.opening_cash}
              currency={currency}
            />

            {report.data.sections
              .filter((section) => section.lines.length > 0)
              .map((section) => (
                <section key={section.classification}>
                  <Typography.Title level={5}>
                    {t(`reports.${section.classification}`)}
                  </Typography.Title>
                  <Table
                    rowKey={(line) => line.account_id}
                    dataSource={section.lines}
                    pagination={false}
                    size="small"
                    columns={[
                      { title: t("reports.code"), dataIndex: "code", width: 110 },
                      { title: t("reports.account"), dataIndex: "name" },
                      {
                        title: t("reports.total"),
                        dataIndex: "amount",
                        align: "end",
                        width: 160,
                        render: (value: string) => <Amount value={value} currency={currency} />,
                      },
                    ]}
                  />
                  <TotalRow
                    label={t(`reports.${section.classification}`)}
                    value={section.total}
                    currency={currency}
                  />
                </section>
              ))}

            <TotalRow
              label={t("reports.netMovement")}
              value={report.data.net_movement}
              currency={currency}
              tone="strong"
            />
            <TotalRow
              label={t("reports.closingCash")}
              value={report.data.closing_cash}
              currency={currency}
              tone="strong"
            />
          </>
        ) : null}
      </ReportState>
    </>
  );
}
