import { Button, Field, Input } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage } from "../lib/api";
import { slugify } from "../lib/format";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { AuthLayout } from "./AuthLayout";

export function OnboardingScreen() {
  const { t } = useTranslation();
  const { session, selectOrg } = useSession();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string>();
  const [inviteError, setInviteError] = useState<string>();
  if (!session) return <Navigate to="/login" />;

  const enter = async (orgId: string) => {
    selectOrg(orgId);
    queryClient.clear();
    await navigate({ to: "/start" });
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const org = await call(api.POST("/v1/organizations", { body: { name: name.trim(), slug } }));
      await enter(org.id);
    } catch (err) {
      setError(problemMessage(err));
    }
  };

  const join = async (e: FormEvent) => {
    e.preventDefault();
    setInviteError(undefined);
    try {
      const m = await call(api.POST("/v1/invitations/accept", { body: { token: token.trim() } }));
      toast(t("onboarding.joined", { name: m.name }));
      await enter(m.org_id);
    } catch (err) {
      setInviteError(problemMessage(err));
    }
  };

  return (
    <AuthLayout title={t("onboarding.title")} lead={t("onboarding.lead")}>
      <form onSubmit={create} className="rounded-panel border border-line bg-surface p-6">
        <Field label={t("onboarding.name")} required>
          {(id) => (
            <Input
              id={id}
              required
              maxLength={200}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (!slugTouched) setSlug(slugify(e.target.value));
              }}
            />
          )}
        </Field>
        <Field label={t("onboarding.slug")} required hint={t("onboarding.slugHint")} error={error}>
          {(id, describedBy) => (
            <Input
              id={id}
              required
              pattern="[a-z0-9][a-z0-9\-]{1,62}"
              aria-describedby={describedBy}
              aria-invalid={!!error}
              className="font-mono"
              value={slug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(e.target.value);
              }}
            />
          )}
        </Field>
        <div className="mt-4 flex justify-end">
          <Button type="submit">{t("onboarding.create")}</Button>
        </div>
      </form>

      <form onSubmit={join} className="mt-6 rounded-panel border border-dashed border-line p-6">
        <h2 className="font-display text-xl font-bold">{t("onboarding.inviteTitle")}</h2>
        <p className="mt-1 text-muted">{t("onboarding.inviteLead")}</p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label className="sr-only" htmlFor="invite-token">
            {t("onboarding.token")}
          </label>
          <Input
            id="invite-token"
            className="font-mono"
            placeholder={t("onboarding.token")}
            required
            minLength={20}
            value={token}
            aria-invalid={!!inviteError}
            onChange={(e) => setToken(e.target.value)}
          />
          <Button type="submit" variant="secondary" className="shrink-0">
            {t("onboarding.join")}
          </Button>
        </div>
        {inviteError ? (
          <p role="alert" className="mt-2 text-sm text-error">
            {inviteError}
          </p>
        ) : null}
      </form>
    </AuthLayout>
  );
}
