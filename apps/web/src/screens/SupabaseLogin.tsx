import { Button, Input } from "@bomagent/ui";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "../lib/session";
import {
  recoverPassword,
  SupabaseAuthError,
  type SupabaseConfig,
  signInWithPassword,
  signUp,
} from "../lib/supabase";
import { AuthLayout } from "./AuthLayout";

const link = "text-sm underline focus-visible:outline-2 focus-visible:outline-focus";

/** E-mail + password against Supabase Auth; no SSO discovery in this deployment variant. */
export function SupabaseLogin({ cfg }: { cfg: SupabaseConfig }) {
  const { t } = useTranslation();
  const { signIn } = useSession();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string>();
  const [info, setInfo] = useState<string>();
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) =>
    setError(t(`login.supabase.errors.${e instanceof SupabaseAuthError ? e.key : "unknown"}`));
  const clear = () => {
    setError(undefined);
    setInfo(undefined);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    clear();
    try {
      if (creating) {
        const result = await signUp(cfg, email.trim(), password, fullName.trim());
        if (result === "confirm") {
          setInfo(t("login.supabase.checkInbox", { email: email.trim() }));
          setCreating(false);
          setPassword("");
          return;
        }
        signIn(result);
      } else {
        signIn(await signInWithPassword(cfg, email.trim(), password));
      }
      await navigate({ to: "/start" });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const forgot = async () => {
    clear();
    if (!email.trim()) {
      setError(t("login.supabase.recoverNeedsEmail"));
      return;
    }
    try {
      await recoverPassword(cfg, email.trim());
      setInfo(t("login.supabase.recoverSent"));
    } catch (err) {
      fail(err);
    }
  };

  return (
    <AuthLayout title={t("login.title")} lead={t("login.lead")}>
      <form
        onSubmit={submit}
        className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-6"
      >
        {creating ? (
          <label className="flex flex-col gap-1.5 font-medium">
            {t("login.supabase.fullName")}
            <Input
              required
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
        ) : null}
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
          {t("login.supabase.password")}
          <Input
            type="password"
            required
            minLength={creating ? 8 : undefined}
            autoComplete={creating ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        ) : null}
        {info ? (
          <p role="status" className="text-sm">
            {info}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" disabled={busy}>
            {creating ? t("login.supabase.create") : t("login.supabase.signIn")}
          </Button>
          <button
            type="button"
            className={link}
            onClick={() => {
              setCreating(!creating);
              clear();
            }}
          >
            {creating ? t("login.supabase.haveAccount") : t("login.supabase.newHere")}
          </button>
          {creating ? null : (
            <button type="button" className={link} onClick={() => void forgot()}>
              {t("login.supabase.forgot")}
            </button>
          )}
        </div>
        <p className="border-t border-line pt-4 text-sm text-muted">{t("login.supabase.note")}</p>
      </form>
    </AuthLayout>
  );
}
