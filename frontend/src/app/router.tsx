/**
 * Routes, and the sign-in gate around them (R1, R2).
 *
 * Report screens are loaded lazily, which is what keeps the first load inside its budget while
 * using Ant Design (NFR2).
 */
import type { QueryClient } from "@tanstack/react-query";
import { Spin } from "antd";
import { Suspense, lazy, useEffect } from "react";
import {
  Navigate,
  createBrowserRouter,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import { setUnauthenticatedHandler } from "@/api/client";
import { useMe } from "@/api/session";

import { Providers } from "./providers";
import { ErrorScreen } from "./ErrorScreen";
import { AppShell } from "@/shell/AppShell";
import { SignIn } from "@/shell/SignIn";

const TrialBalance = lazy(() => import("@/reports/TrialBalance"));
const ProfitAndLoss = lazy(() => import("@/reports/ProfitAndLoss"));
const BalanceSheet = lazy(() => import("@/reports/BalanceSheet"));
const CashFlow = lazy(() => import("@/reports/CashFlow"));
const Aged = lazy(() => import("@/reports/Aged"));
const VatReturn = lazy(() => import("@/reports/VatReturn"));
const AccountDetail = lazy(() => import("@/reports/AccountDetail"));

function Loading() {
  return (
    <div style={{ display: "grid", placeItems: "center", padding: "3rem" }}>
      <Spin />
    </div>
  );
}

/** R1.AC9 — remember where someone was going before they signed in. */
function SignInScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const intended = (location.state as { from?: string } | null)?.from;

  return <SignIn onSignedIn={() => navigate(intended ?? "/", { replace: true })} />;
}

/** The gate: signed in, or the sign-in form (R1.AC4, R1.AC6). */
function RequireSession() {
  const me = useMe();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      navigate("/sign-in", { replace: true, state: { from: location.pathname + location.search } });
    });
    return () => setUnauthenticatedHandler(undefined);
  }, [navigate, location.pathname, location.search]);

  if (me.isPending) {
    return <Loading />;
  }
  if (me.isError) {
    return (
      <Navigate
        to="/sign-in"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  return <AppShell />;
}

/** Send someone arriving at the root to their first company's first report. */
function Home() {
  const me = useMe();
  const first = me.data?.companies[0];
  if (me.isPending) {
    return <Loading />;
  }
  if (!first) {
    return <AppShell />;
  }
  return <Navigate to={`/companies/${first.company_id}/reports/trial-balance`} replace />;
}

function AgedScreen({ side }: { side: "receivables" | "payables" }) {
  const { companyId } = useParams();
  return <Aged key={side} side={side} companyId={companyId ?? ""} />;
}

export function makeRouter(queryClient: QueryClient) {
  const withProviders = (element: React.ReactNode) => (
    <Providers queryClient={queryClient}>
      <Suspense fallback={<Loading />}>{element}</Suspense>
    </Providers>
  );

  return createBrowserRouter([
    {
      path: "/sign-in",
      element: withProviders(<SignInScreen />),
      errorElement: withProviders(<ErrorScreen />),
    },
    {
      path: "/",
      element: withProviders(<Home />),
      errorElement: withProviders(<ErrorScreen />),
    },
    {
      path: "/companies/:companyId",
      element: withProviders(<RequireSession />),
      errorElement: withProviders(<ErrorScreen />),
      children: [
        { index: true, element: <Navigate to="reports/trial-balance" replace /> },
        { path: "reports/trial-balance", element: <TrialBalance /> },
        { path: "reports/profit-and-loss", element: <ProfitAndLoss /> },
        { path: "reports/balance-sheet", element: <BalanceSheet /> },
        { path: "reports/cash-flow", element: <CashFlow /> },
        { path: "reports/aged-receivables", element: <AgedScreen side="receivables" /> },
        { path: "reports/aged-payables", element: <AgedScreen side="payables" /> },
        { path: "reports/vat-return", element: <VatReturn /> },
        { path: "reports/accounts/:accountId", element: <AccountDetail /> },
      ],
    },
  ]);
}
