/**
 * The pieces every report screen uses (R5, R9).
 *
 * Deliberately three small components rather than one `ReportLayout`: a trial balance, an
 * ageing and a VAT return have genuinely different shapes, and one frame for all of them
 * needed props nobody could name.
 */
import { Alert, Button, Empty, Skeleton, Typography } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import type { ReportMeta, ReportRow } from "@/api/reports";
import type { Locale } from "@/i18n";
import { formatAmount, formatDate, formatReadAt, isNegativeAmount, isZeroAmount } from "@/money/format";
import type { Period } from "@/periods/period";
import { periodToSearch } from "@/periods/period";

/** An amount, aligned, marked, and never mirrored (R4). */
export function Amount({
  value,
  currency,
  dashOnZero = true,
  strong = false,
}: {
  value: string | null | undefined;
  currency: string;
  dashOnZero?: boolean;
  strong?: boolean;
}) {
  const text = formatAmount(value, currency, { dashOnZero });
  const classes = ["amount"];
  if (value && isNegativeAmount(value)) classes.push("negative");
  if (!value || isZeroAmount(value)) classes.push("zero");

  return (
    <span className={classes.join(" ")} dir="ltr">
      {strong ? <strong>{text}</strong> : text}
    </span>
  );
}

/** What this report is, and of what (R5.AC2, R8.AC5). */
export function ReportHeader({
  title,
  meta,
  children,
}: {
  title: string;
  meta: ReportMeta | undefined;
  children?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";

  return (
    <header style={{ marginBottom: "1rem" }}>
      <Typography.Title level={3} style={{ marginTop: 0, marginBottom: ".25rem" }}>
        {title}
      </Typography.Title>
      {meta ? (
        <div className="report-meta">
          <span>{meta.company_name}</span>
          <span>{meta.period_label}</span>
          <span>
            {t("reports.currency")}: {meta.currency_code}
          </span>
          <span>
            {t("reports.readAt")}: {formatReadAt(meta.generated_at, locale)}
          </span>
          <span className="visually-hidden">
            {formatDate(meta.period_start, locale)} – {formatDate(meta.period_end, locale)}
          </span>
        </div>
      ) : null}
      {children}
    </header>
  );
}

/** Loading, refused, broken or empty — always words, never a blank screen (R5.AC8, R9). */
export function ReportState({
  isPending,
  error,
  isEmpty,
  onRetry,
  children,
}: {
  isPending: boolean;
  error: unknown;
  isEmpty?: boolean;
  onRetry?: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();

  if (error) {
    const failure = error instanceof ApiError ? error : undefined;
    const message = failure?.isForbidden
      ? t("errors.forbidden")
      : failure?.isOffline
        ? t("errors.offline")
        : failure?.status === 404
          ? t("errors.notFound")
          : (failure?.detail ?? t("errors.unexpected"));

    return (
      <Alert
        type={failure?.isForbidden ? "warning" : "error"}
        showIcon
        message={message}
        action={
          onRetry ? (
            <Button size="small" onClick={onRetry}>
              {t("app.retry")}
            </Button>
          ) : null
        }
      />
    );
  }

  if (isPending) {
    // R5.AC7 — something is happening, and it is announced.
    return (
      <div role="status" aria-live="polite" aria-label={t("app.loading")}>
        {/* The grey bars stand in for text that is not there yet; the label above is what
            gets announced. Left visible to assistive technology they read as empty headings
            (R11.AC3). */}
        <div aria-hidden="true">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      </div>
    );
  }

  if (isEmpty) {
    return <Empty description={t("reports.empty")} />;
  }

  return <>{children}</>;
}

/** A row flattened out of the hierarchy, with the depth it sits at. */
export type FlatRow = ReportRow & { depth: number; hasChildren: boolean };

export function flattenRows(rows: ReportRow[], collapsed: Set<string>, depth = 0): FlatRow[] {
  return rows.flatMap((row) => {
    const children = (row.children ?? []) as ReportRow[];
    const id = row.account_id ?? `${row.code ?? row.name}`;
    const flat: FlatRow = { ...row, depth, hasChildren: children.length > 0 };
    if (children.length === 0 || collapsed.has(id)) {
      return [flat];
    }
    return [flat, ...flattenRows(children, collapsed, depth + 1)];
  });
}

/** An account's name, which links to the entries behind it (R8.AC1). */
export function AccountLink({
  row,
  period,
  children,
}: {
  row: Pick<ReportRow, "account_id" | "is_group">;
  period: Period;
  children: ReactNode;
}) {
  const { companyId } = useParams();

  if (!row.account_id || row.is_group) {
    return <>{children}</>;
  }
  const search = periodToSearch(period).toString();
  return (
    <Link to={`/companies/${companyId}/reports/accounts/${row.account_id}?${search}`}>
      {children}
    </Link>
  );
}

/** In Arabic, an account's Arabic name; otherwise its English one (R3.AC4). */
export function accountName(row: Pick<ReportRow, "name" | "name_ar">, locale: Locale): string {
  return locale === "ar" && row.name_ar ? row.name_ar : row.name;
}
