/** A report's nested rows, with subtotals and collapsing (R5.AC3, R5.AC4). */
import { Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ReportRow } from "@/api/reports";
import type { Locale } from "@/i18n";
import type { Period } from "@/periods/period";

import { AccountLink, Amount, accountName, flattenRows } from "./shared";
import type { FlatRow } from "./shared";

export type AmountColumn = {
  key: "opening" | "debit" | "credit" | "closing";
  label: string;
};

export function HierarchyTable({
  rows,
  currency,
  period,
  columns,
  locale,
}: {
  rows: ReportRow[];
  currency: string;
  period: Period;
  columns: AmountColumn[];
  locale: Locale;
}) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const flat = flattenRows(rows, collapsed);

  const toggle = (id: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const tableColumns: ColumnsType<FlatRow> = [
    {
      title: t("reports.code"),
      dataIndex: "code",
      width: 110,
      render: (code: string | null) => <span className="amount" dir="ltr">{code ?? ""}</span>,
    },
    {
      title: t("reports.account"),
      dataIndex: "name",
      render: (_: unknown, row: FlatRow) => {
        const id = row.account_id ?? `${row.code ?? row.name}`;
        const name = accountName(row, locale);
        return (
          <span style={{ paddingInlineStart: `${row.depth * 1.25}rem` }}>
            {row.hasChildren ? (
              <button
                type="button"
                aria-expanded={!collapsed.has(id)}
                onClick={() => toggle(id)}
                style={{
                  background: "none",
                  border: 0,
                  cursor: "pointer",
                  padding: 0,
                  marginInlineEnd: ".4rem",
                }}
              >
                {collapsed.has(id) ? "▸" : "▾"}
              </button>
            ) : null}
            {row.is_group ? <strong>{name}</strong> : <AccountLink row={row} period={period}>{name}</AccountLink>}
          </span>
        );
      },
    },
    ...columns.map((column) => ({
      title: column.label,
      dataIndex: column.key,
      align: "end" as const,
      width: 150,
      render: (value: string) => (
        <Amount value={value} currency={currency} strong={false} />
      ),
    })),
  ];

  return (
    <Table<FlatRow>
      rowKey={(row) => row.account_id ?? `${row.code ?? row.name}-${row.depth}`}
      dataSource={flat}
      columns={tableColumns}
      pagination={false}
      size="small"
      sticky
      rowClassName={(row) => (row.is_group ? "group-row" : "")}
    />
  );
}

/** A figure that is a conclusion rather than an account (R5.AC4). */
export function TotalRow({
  label,
  value,
  currency,
  tone,
}: {
  label: string;
  value: string;
  currency: string;
  tone?: "neutral" | "strong";
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "2rem",
        padding: ".5rem 0",
        borderTop: tone === "strong" ? "2px solid var(--rule)" : "1px solid var(--rule)",
        fontWeight: tone === "strong" ? 600 : 400,
      }}
    >
      <span>{label}</span>
      <Amount value={value} currency={currency} dashOnZero={false} strong={tone === "strong"} />
    </div>
  );
}

export function BalanceTag({ balances, yes, no }: { balances: boolean; yes: string; no: string }) {
  return <Tag color={balances ? "green" : "red"}>{balances ? yes : no}</Tag>;
}
