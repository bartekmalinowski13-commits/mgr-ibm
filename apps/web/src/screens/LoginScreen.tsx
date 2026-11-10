import { Button, Input } from "@bomagent/ui";
import { Navigate, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { devSignIn, useSession } from "../lib/session";
import { AuthLayout } from "./AuthLayout";

export function LoginScreen() {
  const { t } = useTranslation();
  const { session, signIn } = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  if (session) return <Navigate to="/start" />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      signIn(await devSignIn(email.trim(), name.trim()));
      await navigate({ to: "/start" });
    } catch {
      setError(t("common.unknownError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t("login.title")} lead={t("login.lead")}>
      <form
        onSubmit={submit}
        className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-6"
      >
        <label className="flex flex-col gap-1.5 font-medium">
          {t("login.email")}
          <Input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1.5 font-medium">
          {t("login.name")}
          <Input
            required
            autoComplete="given-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={busy} className="mt-2 self-start">
          {t("login.submit")}
        </Button>
        <p className="border-t border-line pt-4 text-sm text-muted">{t("login.devNote")}</p>
      </form>
    </AuthLayout>
  );
}
