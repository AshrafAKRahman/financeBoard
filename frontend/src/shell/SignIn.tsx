/** Signing in (R1). The session is the API's cookie; this form only starts it. */
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useSignIn } from "@/api/session";

export function SignIn({ onSignedIn }: { onSignedIn?: () => void }) {
  const { t } = useTranslation();
  const signIn = useSignIn();

  const failure = signIn.error instanceof ApiError ? signIn.error : undefined;
  const message = failure?.isOffline ? t("signIn.unreachable") : t("signIn.refused");

  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: "1rem" }}>
      <Card style={{ width: "min(420px, 100%)" }}>
        <Typography.Title level={2} style={{ marginTop: 0 }}>
          {t("signIn.title")}
        </Typography.Title>

        {signIn.isError ? (
          <Alert type="error" showIcon message={message} style={{ marginBottom: "1rem" }} />
        ) : null}

        <Form
          layout="vertical"
          requiredMark={false}
          onFinish={(values: { email: string; password: string }) => {
            signIn.mutate(values, { onSuccess: () => onSignedIn?.() });
          }}
        >
          <Form.Item
            label={t("signIn.email")}
            name="email"
            rules={[{ required: true, type: "email" }]}
          >
            <Input id="email" autoComplete="username" autoFocus inputMode="email" />
          </Form.Item>

          <Form.Item label={t("signIn.password")} name="password" rules={[{ required: true }]}>
            <Input.Password id="password" autoComplete="current-password" />
          </Form.Item>

          <Button
            type="primary"
            htmlType="submit"
            block
            loading={signIn.isPending}
            // R1.AC3 — the same credentials cannot be sent twice.
            disabled={signIn.isPending}
          >
            {signIn.isPending ? t("signIn.working") : t("signIn.submit")}
          </Button>
        </Form>
      </Card>
    </main>
  );
}
