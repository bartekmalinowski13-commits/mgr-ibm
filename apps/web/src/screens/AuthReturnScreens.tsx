import { Button, Input } from "@bomagent/ui";
import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { peekAuthReturn, stashAuthReturn } from "../lib/authReturn";
import { authConfig } from "../lib/oidc";
import { SupabaseAuthError, updatePassword } from "../lib/supabase";
import { AuthLayout } from "./AuthLayout";

const link = "font-medium underline underline-offset-4 focus-visible:outline-2";

/** Landing page of the password-recovery e-mail: sets a new password with the link's token. */
export function ResetPasswordScreen() {
  const { t } = useTranslation();
  const [token] = useState(() => {
    const r = peekAuthReturn();
    return r.kind === "recovery" ? r.accessToken : undefined;
  });
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setError(undefined);
    try {
      const cfg = await authConfig();
      if (cfg.mode !== "supabase") throw new SupabaseAuthError("unknown", 0);
      await updatePassword(cfg, token, password);
      stashAuthReturn({ kind: "none" });
      setPassword("");
      setDone(true);
    } catch (err) {
      setError(
        t(`login.supabase.errors.${err instanceof SupabaseAuthError ? err.key : "unknown"}`),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t("login.reset.title")} lead={t("login.reset.lead")}>
      {done ? (
        <p role="status" className="rounded-card border border-line bg-surface p-4">
          {t("login.reset.done")}{" "}
          <Link to="/login" className={link}>
            {t("login.reset.signIn")}
          </Link>
        </p>
      ) : token ? (
        <form
          onSubmit={submit}
          className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-6"
        >
          <label className="flex flex-col gap-1.5 font-medium">
            {t("login.reset.newPassword")}
            <Input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error ? (
            <p role="alert" className="text-sm text-error">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={busy} className="self-start">
            {t("login.reset.submit")}
          </Button>
        </form>
      ) : (
        <p role="alert" className="rounded-card border border-error/30 bg-error/5 p-4">
          {t("login.reset.missing")}{" "}
          <Link to="/login" className={link}>
            {t("login.retry")}
          </Link>
        </p>
      )}
    </AuthLayout>
  );
}

/** Landing page of the sign-up confirmation e-mail. The link's token is discarded. */
export function EmailConfirmedScreen() {
  const { t } = useTranslation();
  return (
    <AuthLayout title={t("login.confirmed.title")} lead={t("login.confirmed.lead")}>
      <Link to="/login" className={link}>
        {t("login.reset.signIn")}
      </Link>
    </AuthLayout>
  );
}
