import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authConfig, completeLogin } from "../lib/oidc";
import { useSession } from "../lib/session";
import { AuthLayout } from "./AuthLayout";

/** Return from the hosted login: exchange the code (PKCE) and start the session. */
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
        if (cfg.mode !== "oidc") throw new Error("hosted login is not configured");
        signIn(await completeLogin(cfg, new URLSearchParams(window.location.search)));
        await navigate({ to: "/start", replace: true });
      } catch {
        setError(t("login.callbackError"));
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
