import { Button, Input } from "@bomagent/ui";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "../lib/session";
import {
  enabledProviders,
  recoverPassword,
  type SocialProvider,
  SupabaseAuthError,
  type SupabaseConfig,
  signInWithPassword,
  signUp,
  startSocialLogin,
} from "../lib/supabase";
import { AuthLayout } from "./AuthLayout";

const link = "text-sm underline focus-visible:outline-2 focus-visible:outline-focus";

// Single-colour glyphs (currentColor): neutral, so they follow the theme and the contrast rules
const ICONS: Record<SocialProvider, string> = {
  google:
    "M12.48 10.92v3.28h7.84c-.24 1.84-.853 3.187-1.787 4.133-1.147 1.147-2.933 2.4-6.053 2.4-4.827 0-8.6-3.893-8.6-8.72s3.773-8.72 8.6-8.72c2.6 0 4.507 1.027 5.907 2.347l2.307-2.307C18.747 1.44 16.133 0 12.48 0 5.867 0 .307 5.387.307 12s5.56 12 12.173 12c3.573 0 6.267-1.173 8.373-3.36 2.16-2.16 2.84-5.213 2.84-7.667 0-.76-.053-1.467-.173-2.053H12.48z",
  azure: "M1 1h10.5v10.5H1zM12.5 1H23v10.5H12.5zM1 12.5h10.5V23H1zM12.5 12.5H23V23H12.5z",
  apple:
    "M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.39-2.376-2-.156-3.675 1.09-4.61 1.09zM15.53 3.83c.843-1.012 1.4-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.559-1.701",
};

function ProviderIcon({ provider }: { provider: SocialProvider }) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" className="size-5 fill-current">
      <path d={ICONS[provider]} />
    </svg>
  );
}

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
  const providers = enabledProviders(cfg.providers);
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

  const social = async (provider: SocialProvider) => {
    setBusy(true);
    clear();
    try {
      await startSocialLogin(cfg, provider); // leaves the page
    } catch (err) {
      fail(err);
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
        {providers.length > 0 ? (
          <>
            <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
              <legend className="sr-only">{t("login.supabase.social.group")}</legend>
              {providers.map((p) => (
                <Button
                  key={p}
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void social(p)}
                  className="justify-center gap-3"
                >
                  <ProviderIcon provider={p} />
                  {t("login.supabase.social.continueWith", {
                    provider: t(`login.supabase.social.providers.${p}`),
                  })}
                </Button>
              ))}
            </fieldset>
            <div className="flex items-center gap-3 text-sm text-muted" aria-hidden>
              <span className="h-px flex-1 bg-line" />
              {t("login.supabase.social.or")}
              <span className="h-px flex-1 bg-line" />
            </div>
          </>
        ) : null}
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
