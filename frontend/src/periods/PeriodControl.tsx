/** Choosing what a report covers, kept in the address (R6). */
import { Alert, Button, DatePicker, Radio, Space } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { InvalidPeriod, NAMED_PERIODS, periodFromSearch, periodToSearch, range } from "./period";
import type { NamedPeriod, Period } from "./period";

/** Read and write the period in the address — the only place it lives (R2.AC5, R6.AC4). */
export function usePeriod(): [Period, (next: Period) => void] {
  const [search, setSearch] = useSearchParams();
  const period = periodFromSearch(search);
  const set = (next: Period) => setSearch(periodToSearch(next, search), { replace: false });
  return [period, set];
}

export function PeriodControl({
  mode = "range",
  extra,
}: {
  /** An as-at report asks for one date instead of a range (R6.AC5). */
  mode?: "range" | "on";
  extra?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [period, setPeriod] = usePeriod();
  const [problem, setProblem] = useState<string | undefined>();

  if (mode === "on") {
    const value = period.kind === "on" ? dayjs(period.on) : dayjs();
    return (
      <Space wrap style={{ marginBottom: "1rem" }}>
        <label htmlFor="as-at">{t("period.asAt")}</label>
        <DatePicker
          id="as-at"
          value={value}
          allowClear={false}
          onChange={(next) => next && setPeriod({ kind: "on", on: next.format("YYYY-MM-DD") })}
        />
        {extra}
      </Space>
    );
  }

  return (
    <Space direction="vertical" style={{ marginBottom: "1rem", width: "100%" }}>
      <Space wrap>
        {/* A radio group rather than Ant Design's Segmented: Segmented nests its
            `role="option"` elements inside labels, so the listbox does not own them and
            assistive technology cannot read the set (R11.AC1). These are one-of-many
            choices, which is what a radio group is for. */}
        <Radio.Group
          aria-label={t("period.label")}
          optionType="button"
          buttonStyle="solid"
          value={period.kind === "named" ? period.named : "custom"}
          onChange={(event) => {
            const value = event.target.value as NamedPeriod | "custom";
            if (value !== "custom") {
              setProblem(undefined);
              setPeriod({ kind: "named", named: value });
            }
          }}
          options={[
            ...NAMED_PERIODS.map((named) => ({ value: named, label: t(`period.${named}`) })),
            { value: "custom", label: t("period.custom") },
          ]}
        />

        <DatePicker.RangePicker
          aria-label={t("period.custom")}
          value={
            period.kind === "range" ? [dayjs(period.start), dayjs(period.end)] : null
          }
          onChange={(dates) => {
            if (!dates?.[0] || !dates?.[1]) {
              return;
            }
            try {
              setProblem(undefined);
              // R6.AC3 — a backwards range is refused and the report is left as it was.
              setPeriod(range(dates[0].format("YYYY-MM-DD"), dates[1].format("YYYY-MM-DD")));
            } catch (error) {
              setProblem(
                error instanceof InvalidPeriod && error.reason === "end-before-start"
                  ? t("period.endBeforeStart")
                  : t("period.badDate"),
              );
            }
          }}
        />
        {extra}
      </Space>

      {problem ? <Alert type="error" showIcon message={problem} /> : null}
    </Space>
  );
}

/** A plain button that does not submit anything, for report-level toggles. */
export function Toggle({
  pressed,
  onToggle,
  children,
}: {
  pressed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button type={pressed ? "primary" : "default"} aria-pressed={pressed} onClick={onToggle}>
      {children}
    </Button>
  );
}
