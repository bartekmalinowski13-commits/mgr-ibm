import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { peekAuthReturn, stashAuthReturn } from "../lib/authReturn";
import { authConfig, completeLogin } from "../lib/oidc";
import { useSession } from "../lib/session";
import {
  type AuthReturn,
  completeSocialLogin,
  parseAuthReturn,
  SupabaseAuthError,
} from "../lib/supabase";
import { AuthLayout } from "./AuthLayout";

/** Return from the hosted login (Cognito) or a social provider (Supabase): PKCE exchange. */
export function AuthCallbackScreen() {
  const { t } = useTranslation();
  const { signIn } = useSession();
  const navigate = useNavigate();
  const [error, setError] = useState<string>();
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return; // the code is single-use (StrictMode mounts twice)
    done.current = true;
    void (async () => {
      try {
        const cfg = await authConfig();
        if (cfg.mode === "supabase") {
          // an error carried in the fragment was moved to the stash by the router
          const stashed = peekAuthReturn();
          stashAuthReturn({ kind: "none" });
          const { search, hash, pathname } = window.location;
          const ret: AuthReturn =
            stashed.kind === "error" ? stashed : parseAuthReturn(search, hash);
          window.history.replaceState(null, "", pathname); // drop code / error from the URL
          if (ret.kind === "error") {
            setError(t(`login.supabase.social.callbackErrors.${ret.reason}`));
            return;
          }
          const session = await completeSocialLogin(cfg, ret.kind === "code" ? ret.code : null);
          signIn(session);
        } else if (cfg.mode === "oidc") {
          signIn(await completeLogin(cfg, new URLSearchParams(window.location.search)));
        } else {
          throw new Error("hosted login is not configured");
        }
        await navigate({ to: "/start", replace: true });
      } catch (err) {
        setError(
          err instanceof SupabaseAuthError && err.key === "socialInvalid"
            ? t("login.supabase.social.callbackErrors.invalid")
            : t("login.callbackError"),
        );
      }
    })();
  }, [navigate, signIn, t]);

  return (
    <AuthLayout title={t("login.title")} lead={t("login.lead")}>
      {error ? (
        <p role="alert" className="rounded-card border border-error/30 bg-error/5 p-4">
          {error}{" "}
          <Link to="/login" className="font-medium underline underline-offset-4">
            {t("login.retry")}
          </Link>
        </p>
      ) : (
        <p role="status" className="text-muted">
          {t("common.loading")}
        </p>
      )}
    </AuthLayout>
  );
}
