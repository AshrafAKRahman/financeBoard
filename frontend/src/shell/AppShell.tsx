/** The frame every screen lives in (R2, R3). */
import { GlobalOutlined, LogoutOutlined } from "@ant-design/icons";
import { Button, Empty, Layout, Menu, Select, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";

import { useMe, useSignOut } from "@/api/session";
import type { Locale } from "@/i18n";
import { applyLocale } from "@/i18n";

const REPORTS = [
  ["trial-balance", "reports.trialBalance"],
  ["profit-and-loss", "reports.profitAndLoss"],
  ["balance-sheet", "reports.balanceSheet"],
  ["cash-flow", "reports.cashFlow"],
  ["aged-receivables", "reports.agedReceivables"],
  ["aged-payables", "reports.agedPayables"],
  ["vat-return", "reports.vatReturn"],
] as const;

export function AppShell() {
  const { t, i18n } = useTranslation();
  const me = useMe();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const location = useLocation();
  const { companyId } = useParams();

  const companies = me.data?.companies ?? [];
  const current = companies.find((company) => company.company_id === companyId) ?? companies[0];

  // R2.AC7 — a person with no role is told so, rather than shown an empty frame.
  if (me.isSuccess && companies.length === 0) {
    return (
      <Layout style={{ minHeight: "100vh" }}>
        <Layout.Content style={{ display: "grid", placeItems: "center" }}>
          <Empty description={t("shell.noCompany")} />
        </Layout.Content>
      </Layout>
    );
  }

  const switchLanguage = () => {
    const next: Locale = i18n.language === "ar" ? "en" : "ar";
    void i18n.changeLanguage(next);
    applyLocale(next);
    // R3.AC6 — the screen and its period are untouched.
  };

  const selected = REPORTS.find(([slug]) => location.pathname.endsWith(slug))?.[0];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <a className="skip-link" href="#content">
        {t("shell.skipToContent")}
      </a>

      <Layout.Header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          background: "#fff",
          borderBottom: "1px solid var(--rule)",
          paddingInline: "1rem",
        }}
      >
        <Typography.Text strong style={{ fontSize: 16 }}>
          {t("app.name")}
        </Typography.Text>

        {companies.length > 1 ? (
          <Select
            aria-label={t("shell.company")}
            value={current?.company_id}
            style={{ minWidth: 200 }}
            onChange={(next) => {
              // R2.AC3 — the same screen, the other company's figures.
              const rest = location.pathname.split("/").slice(3).join("/");
              navigate(`/companies/${next}/${rest}${location.search}`);
            }}
            options={companies.map((company) => ({
              value: company.company_id,
              label: company.name,
            }))}
          />
        ) : (
          <Typography.Text type="secondary">{current?.name}</Typography.Text>
        )}

        <Space style={{ marginInlineStart: "auto" }}>
          <Button icon={<GlobalOutlined />} onClick={switchLanguage}>
            {t("shell.language")}
          </Button>
          <Typography.Text type="secondary">
            {t("shell.signedInAs")} {me.data?.name || me.data?.email}
          </Typography.Text>
          <Button
            icon={<LogoutOutlined />}
            onClick={() => signOut.mutate(undefined, { onSettled: () => navigate("/sign-in") })}
          >
            {t("shell.signOut")}
          </Button>
        </Space>
      </Layout.Header>

      <Layout>
        <Layout.Sider width={220} theme="light" breakpoint="lg" collapsedWidth={0}>
          <Menu
            mode="inline"
            selectedKeys={selected ? [selected] : []}
            style={{ height: "100%", borderInlineEnd: 0 }}
            items={REPORTS.map(([slug, label]) => ({
              key: slug,
              label: (
                <Link to={`/companies/${current?.company_id ?? ""}/reports/${slug}${location.search}`}>
                  {t(label)}
                </Link>
              ),
            }))}
          />
        </Layout.Sider>

        <Layout.Content id="content" style={{ padding: "1.5rem", overflowX: "auto" }}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
