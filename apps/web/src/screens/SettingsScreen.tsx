import { Button, Input, Select } from "@bomagent/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage } from "../lib/api";
import { formatDate, formatNumber } from "../lib/format";
import { usePageTitle } from "../lib/layout";
import { formatEur } from "../lib/provenance";
import { useMe, useUsage } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { LoadError, Skeleton } from "./common";

const ROLES = ["owner", "admin", "engineer", "reviewer", "viewer"] as const;
const KEY_ROLES = ["engineer", "reviewer", "viewer"] as const;
type Tab = "members" | "keys" | "usage" | "sso";

function Secret({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" className="rounded-card border border-llm/30 bg-llm/5 p-4">
      <p>{label}</p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <code
          className="min-w-0 flex-1 break-all rounded-control bg-surface px-3 py-2 font-mono text-[13px]"
          data-testid="secret"
        >
          {value}
        </code>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            void navigator.clipboard?.writeText(value);
            setCopied(true);
          }}
        >
          {copied ? t("common.copied") : t("common.copy")}
        </Button>
      </div>
    </div>
  );
}

function Section({ title, lead, children }: { title: string; lead?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-display text-2xl font-bold">{title}</h2>
        {lead ? <p className="max-w-[70ch] text-muted">{lead}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Members() {
  const { t, i18n } = useTranslation();
  const { orgId, session } = useSession();
  const toast = useToast();
  const qc = useQueryClient();
  const members = useQuery({
    queryKey: ["members", orgId],
    queryFn: () => call(api.GET("/v1/members")),
  });
  const invites = useQuery({
    queryKey: ["invitations", orgId],
    queryFn: () => call(api.GET("/v1/invitations")),
  });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("engineer");
  const [token, setToken] = useState<string>();
  const [error, setError] = useState<string>();
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", orgId] });

  const invite = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const created = await call(
        api.POST("/v1/invitations", { body: { email, roles: [role as "viewer"] } }),
      );
      setToken(created.token);
      setEmail("");
      await qc.invalidateQueries({ queryKey: ["invitations", orgId] });
    } catch (err) {
      setError(problemMessage(err));
    }
  };
  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      toast(done);
      await refresh();
      await qc.invalidateQueries({ queryKey: ["invitations", orgId] });
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <Section title={t("settings.members")}>
        {members.isPending ? (
          <Skeleton />
        ) : members.isError ? (
          <LoadError error={members.error} />
        ) : (
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {members.data.items.map((m) => (
              <li key={m.user_sub} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{m.display_name || m.email}</p>
                  <p className="text-sm text-muted">{m.email}</p>
                </div>
                <label className="sr-only" htmlFor={`role-${m.user_sub}`}>
                  {t("settings.role")}
                </label>
                <Select
                  id={`role-${m.user_sub}`}
                  className="w-44"
                  value={m.roles[0]}
                  onChange={(e) =>
                    void act(
                      () =>
                        call(
                          api.PATCH("/v1/members/{user_sub}", {
                            params: { path: { user_sub: m.user_sub } },
                            body: { roles: [e.target.value as "viewer"] },
                          }),
                        ),
                      t("settings.rolesChanged"),
                    )
                  }
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(`settings.roles.${r}`)}
                    </option>
                  ))}
                </Select>
                {m.user_sub !== session?.sub ? (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() =>
                      void act(
                        () =>
                          call(
                            api.DELETE("/v1/members/{user_sub}", {
                              params: { path: { user_sub: m.user_sub } },
                            }),
                          ),
                        t("settings.removed"),
                      )
                    }
                  >
                    {t("settings.removeMember")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("settings.invite")}>
        <form
          onSubmit={invite}
          className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4 sm:flex-row sm:items-end"
        >
          <label className="flex flex-1 flex-col gap-1.5 font-medium">
            {t("settings.inviteEmail")}
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1.5 font-medium">
            {t("settings.role")}
            <Select value={role} onChange={(e) => setRole(e.target.value)} className="w-44">
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`settings.roles.${r}`)}
                </option>
              ))}
            </Select>
          </label>
          <Button type="submit">{t("settings.sendInvite")}</Button>
        </form>
        {error ? (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        ) : null}
        {token ? <Secret label={t("settings.invited")} value={token} /> : null}
        <h3 className="mt-2 font-medium">{t("settings.pending")}</h3>
        {invites.data?.items.length ? (
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {invites.data.items.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="min-w-0 flex-1">{i.email}</span>
                <span className="text-sm text-muted">
                  {i.roles.map((r) => t(`settings.roles.${r}`)).join(", ")}
                </span>
                <span className="text-sm text-muted">
                  {t("settings.expires", { date: formatDate(i.expires_at, i18n.language) })}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    void act(
                      () =>
                        call(
                          api.DELETE("/v1/invitations/{invitation_id}", {
                            params: { path: { invitation_id: i.id } },
                          }),
                        ),
                      t("settings.revoke"),
                    )
                  }
                >
                  {t("settings.revoke")}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">{t("settings.noPending")}</p>
        )}
      </Section>
    </div>
  );
}

function Keys() {
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const toast = useToast();
  const qc = useQueryClient();
  const keys = useQuery({
    queryKey: ["api-keys", orgId],
    queryFn: () => call(api.GET("/v1/api-keys")),
  });
  const [name, setName] = useState("");
  const [role, setRole] = useState<(typeof KEY_ROLES)[number]>("viewer");
  const [secret, setSecret] = useState<string>();
  const refresh = () => qc.invalidateQueries({ queryKey: ["api-keys", orgId] });

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const k = await call(api.POST("/v1/api-keys", { body: { name, roles: [role] } }));
      setSecret(k.key);
      setName("");
      await refresh();
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

  return (
    <Section title={t("settings.keys")} lead={t("settings.keysLead")}>
      <form
        onSubmit={create}
        className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4 sm:flex-row sm:items-end"
      >
        <label className="flex flex-1 flex-col gap-1.5 font-medium">
          {t("settings.keyName")}
          <Input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1.5 font-medium">
          {t("settings.role")}
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            className="w-44"
          >
            {KEY_ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`settings.roles.${r}`)}
              </option>
            ))}
          </Select>
        </label>
        <Button type="submit">{t("settings.createKey")}</Button>
      </form>
      {secret ? <Secret label={t("settings.keyCreated")} value={secret} /> : null}
      {keys.data?.items.length ? (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {keys.data.items.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{k.name}</p>
                <p className="text-sm text-muted">
                  <span className="font-mono">{k.prefix}…</span> –{" "}
                  {t("settings.lastUsed", {
                    date: k.last_used_at
                      ? formatDate(k.last_used_at, i18n.language)
                      : t("common.never"),
                  })}
                </p>
              </div>
              <span className="text-sm text-muted">
                {k.roles.map((r) => t(`settings.roles.${r}`)).join(", ")}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  try {
                    const r = await call(
                      api.POST("/v1/api-keys/{key_id}/rotate", {
                        params: { path: { key_id: k.id } },
                      }),
                    );
                    setSecret(r.key);
                    toast(t("settings.rotated"));
                    await refresh();
                  } catch (err) {
                    toast(problemMessage(err), "error");
                  }
                }}
              >
                {t("settings.rotate")}
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={async () => {
                  try {
                    await call(
                      api.DELETE("/v1/api-keys/{key_id}", { params: { path: { key_id: k.id } } }),
                    );
                    toast(t("settings.revoke"));
                    await refresh();
                  } catch (err) {
                    toast(problemMessage(err), "error");
                  }
                }}
              >
                {t("settings.revoke")}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">{t("settings.noKeys")}</p>
      )}
    </Section>
  );
}

function Usage() {
  const { t, i18n } = useTranslation();
  const usage = useUsage(true);
  if (usage.isPending) return <Skeleton />;
  if (usage.isError) return <LoadError error={usage.error} />;
  const { usage: u, limits } = usage.data;
  const rows = [
    {
      key: "runs",
      used: u.runs ?? 0,
      limit: limits.max_runs_per_month ?? 0,
      fmt: (v: number) => formatNumber(v, i18n.language),
    },
    {
      key: "cost_eur",
      used: u.cost_eur ?? 0,
      limit: limits.llm_budget_eur_per_month ?? 0,
      fmt: (v: number) => formatEur(v, i18n.language),
    },
    {
      key: "llm_calls",
      used: u.llm_calls ?? 0,
      fmt: (v: number) => formatNumber(v, i18n.language),
    },
    {
      key: "files_uploaded",
      used: u.files_uploaded ?? 0,
      fmt: (v: number) => formatNumber(v, i18n.language),
    },
  ];
  return (
    <Section title={t("settings.usage")}>
      <dl className="grid gap-4 sm:grid-cols-2">
        {rows.map((r) => (
          <div key={r.key} className="rounded-card border border-line bg-surface p-4">
            <dt className="text-muted">{t(`settings.usageItems.${r.key}`)}</dt>
            <dd className="mt-1 font-display text-2xl font-bold tabular-nums">
              {r.fmt(r.used)}{" "}
              {r.limit ? (
                <span className="font-sans text-base font-normal text-muted">
                  {t("settings.of", { limit: r.fmt(r.limit) })}
                </span>
              ) : null}
              {r.limit ? (
                // biome-ignore lint/a11y/useSemanticElements: styled meter; <meter> cannot be themed consistently
                <div
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={r.limit}
                  aria-valuenow={r.used}
                  aria-label={t(`settings.usageItems.${r.key}`)}
                  className="mt-3 h-2 overflow-hidden rounded-full bg-line"
                >
                  <div
                    className={r.used / r.limit > 0.8 ? "h-full bg-warn" : "h-full bg-ink"}
                    style={{ width: `${Math.min(100, (r.used / r.limit) * 100)}%` }}
                  />
                </div>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

export function SettingsScreen() {
  const { t } = useTranslation();
  usePageTitle(t("settings.title"));
  const { orgId } = useSession();
  const me = useMe();
  const roles = me.data?.organizations.find((o) => o.org_id === orgId)?.roles ?? [];
  const admin = roles.includes("owner") || roles.includes("admin");
  const [tab, setTab] = useState<Tab>("members");
  if (me.isPending) return <Skeleton />;
  if (!admin) return <p className="text-muted">{t("errors.notMember")}</p>;
  const tabs: Tab[] = ["members", "keys", "usage", "sso"];
  return (
    <div className="flex flex-col gap-6">
      <div
        role="tablist"
        aria-label={t("settings.title")}
        className="flex flex-wrap gap-1 border-b border-line"
      >
        {tabs.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-3 py-2 font-medium focus-visible:outline-2 focus-visible:outline-focus ${
              tab === id ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t(`settings.tabs.${id}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "members" ? <Members /> : null}
        {tab === "keys" ? <Keys /> : null}
        {tab === "usage" ? <Usage /> : null}
        {tab === "sso" ? (
          <Section title={t("settings.sso")} lead={t("settings.ssoLead")}>
            {null}
          </Section>
        ) : null}
      </div>
    </div>
  );
}
