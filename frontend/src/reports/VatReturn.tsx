/** The ZATCA VAT return (R5.AC7). */
import { Alert, Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useVatReturn } from "@/api/reports";
import type { VatReturn as VatReturnData } from "@/api/reports";
import { PeriodControl, usePeriod } from "@/periods/PeriodControl";

import { TotalRow } from "./HierarchyTable";
import { Amount, ReportHeader, ReportState } from "./shared";

type Box = VatReturnData["sales"][number];

export default function VatReturn() {
  const { t, i18n } = useTranslation();
  const { companyId = "" } = useParams();
  const [period] = usePeriod();
  const report = useVatReturn(companyId, period);
  const currency = report.data?.meta.currency_code ?? "SAR";
  const arabic = i18n.language === "ar";

  const boxes = (rows: Box[], caption: string) => (
    <section>
      <Typography.Title level={5}>{caption}</Typography.Title>
      <Table<Box>
        rowKey={(box) => box.number}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: t("reports.box"), dataIndex: "number", width: 80 },
          {
            // R5.AC7 — each box carries its ZATCA number and name.
            title: t("reports.account"),
            render: (_: unknown, box: Box) => (arabic ? box.name_ar : box.name),
          },
          {
            title: t("reports.net"),
            dataIndex: "net",
            align: "end",
            width: 160,
            render: (value: string) => <Amount value={value} currency={currency} />,
          },
          {
            title: t("reports.tax"),
            dataIndex: "tax",
            align: "end",
            width: 160,
            render: (value: string) => <Amount value={value} currency={currency} />,
          },
        ]}
      />
    </section>
  );

  return (
    <>
      <ReportHeader title={t("reports.vatReturn")} meta={report.data?.meta}>
        <PeriodControl />
      </ReportHeader>

      <ReportState
        isPending={report.isPending}
        error={report.error}
        isEmpty={report.data?.sales.length === 0 && report.data?.purchases.length === 0}
        onRetry={() => void report.refetch()}
      >
        {report.data ? (
          <>
            {boxes(report.data.sales, t("reports.sales"))}
            <TotalRow
              label={t("reports.outputTax")}
              value={report.data.output_tax}
              currency={currency}
            />

            {boxes(report.data.purchases, t("reports.purchases"))}
            <TotalRow
              label={t("reports.inputTax")}
              value={report.data.input_tax}
              currency={currency}
            />

            <TotalRow
              label={t("reports.netTaxDue")}
              value={report.data.net_tax_due}
              currency={currency}
              tone="strong"
            />

            {report.data.untagged.length > 0 ? (
              <Alert
                style={{ marginTop: "1rem" }}
                type="warning"
                showIcon
                message={t("reports.untagged")}
                description={report.data.untagged
                  .map((entry) => entry.grid_tag ?? "—")
                  .join(", ")}
              />
            ) : null}
          </>
        ) : null}
      </ReportState>
    </>
  );
}
