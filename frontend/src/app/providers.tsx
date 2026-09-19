/** Everything the screens need around them: queries, language, direction, Ant Design. */
import { ConfigProvider, theme } from "antd";
import arEG from "antd/locale/ar_EG";
import enGB from "antd/locale/en_GB";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Locale } from "@/i18n";
import { directionOf } from "@/i18n";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A report is read-only; refetching it because a window regained focus only makes
        // figures flicker.
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

export function Providers({
  children,
  queryClient,
}: {
  children: ReactNode;
  queryClient: QueryClient;
}) {
  const { i18n } = useTranslation();
  const locale = (i18n.language as Locale) ?? "en";
  const direction = directionOf(locale);

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        direction={direction}
        locale={locale === "ar" ? arEG : enGB}
        theme={{
          algorithm: theme.defaultAlgorithm,
          token: { colorPrimary: "#0f5c46", fontSize: 14 },
        }}
      >
        {children}
      </ConfigProvider>
    </QueryClientProvider>
  );
}
