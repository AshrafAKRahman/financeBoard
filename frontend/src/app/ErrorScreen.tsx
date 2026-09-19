/** An unrecognised failure becomes words and a way onward, never a stack trace (R9.AC3, R9.AC6). */
import { Button, Result } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate, useRouteError } from "react-router-dom";

import { ApiError } from "@/api/client";

export function ErrorScreen() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const error = useRouteError();

  const message =
    error instanceof ApiError
      ? error.isForbidden
        ? t("errors.forbidden")
        : error.isOffline
          ? t("errors.offline")
          : (error.detail ?? t("errors.unexpected"))
      : t("errors.unexpected");

  return (
    <Result
      status="warning"
      title={message}
      extra={
        <Button type="primary" onClick={() => navigate(0)}>
          {t("app.retry")}
        </Button>
      }
    />
  );
}
