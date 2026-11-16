import { cn, Menu, MenuContent, MenuItem, MenuTrigger } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, Outlet, useNavigate } from "@tanstack/react-router";
import {
  BookOpen,
  Check,
  ChevronsUpDown,
  FolderKanban,
  Home,
  Languages,
  ListChecks,
  LogOut,
  Menu as MenuIcon,
  Plus,
  ScrollText,
  Settings,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { type NewRunPreset, ShellCtx } from "../lib/layout";
import { authConfig, logoutUrl } from "../lib/oidc";
import { formatEur } from "../lib/provenance";
import { useMe, useProjects, useUsage } from "../lib/queries";
import { useSession } from "../lib/session";
import { signOutRemote } from "../lib/supabase";
import { NewRunDialog } from "./NewRunDialog";

export function Shell() {
  const { t, i18n } = useTranslation();
  const { session, orgId, selectOrg, signOut } = useSession();
  const me = useMe();
  const [title, setTitle] = useState("");
  const [newRun, setNewRun] = useState<NewRunPreset | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const openNewRun = useCallback((preset?: NewRunPreset) => setNewRun(preset ?? {}), []);
  const shell = useMemo(() => ({ setTitle, openNewRun }), [openNewRun]);

  const orgs = me.data?.organizations ?? [];
  const org = orgs.find((o) => o.org_id === orgId);
  const isAdmin = !!org?.roles.some((r) => r === "owner" || r === "admin");
  const usage = useUsage(isAdmin);
  const projects = useProjects();
  const firstOrg = orgs[0]?.org_id;
  useEffect(() => {
    if (me.isSuccess && !org && firstOrg) selectOrg(firstOrg);
  }, [me.isSuccess, org, firstOrg, selectOrg]);

  if (!session) return <Navigate to="/login" />;
  if (me.isSuccess && orgs.length === 0) return <Navigate to="/onboarding" />;
  if (me.isSuccess && !org) return null; // the effect above picks the first organisation

  const switchOrg = (id: string) => {
    selectOrg(id);
    queryClient.clear();
    void navigate({ to: "/start" });
  };
  const used = usage.data?.usage.cost_eur ?? 0;
  const limit = usage.data?.limits.llm_budget_eur_per_month ?? 0;
  const lang = i18n.language.startsWith("pl") ? "pl-PL" : "en-GB";

  const navItem =
    "flex items-center gap-3 rounded-control px-3 py-2 text-[15px] text-ink/80 hover:bg-paper hover:text-ink " +
    "focus-visible:outline-2 focus-visible:outline-focus data-[status=active]:bg-paper data-[status=active]:font-medium data-[status=active]:text-ink";

  const sidebar = (
    <nav aria-label={t("nav.label")} className="flex h-full flex-col gap-6 p-4">
      <Menu>
        <MenuTrigger className="flex w-full items-center gap-3 rounded-card border border-line bg-surface p-2.5 text-left hover:border-ink/30 focus-visible:outline-2 focus-visible:outline-focus">
          <span
            aria-hidden
            className="grid size-9 shrink-0 place-items-center rounded-control bg-ink font-display text-lg font-extrabold text-surface"
          >
            {(org?.name ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="sr-only">{t("nav.switchOrg")}: </span>
            <span className="block truncate font-medium">{org?.name ?? t("common.loading")}</span>
            <span className="block truncate text-sm text-muted">
              {org?.roles.map((r) => t(`settings.roles.${r}`)).join(", ")}
            </span>
          </span>
          <ChevronsUpDown size={16} aria-hidden className="text-muted" />
        </MenuTrigger>
        <MenuContent>
          {orgs.map((o) => (
            <MenuItem key={o.org_id} onSelect={() => switchOrg(o.org_id)}>
              <span className="flex-1 truncate">{o.name}</span>
              {o.org_id === orgId ? <Check size={16} aria-hidden /> : null}
            </MenuItem>
          ))}
          <MenuItem onSelect={() => void navigate({ to: "/onboarding" })}>
            <Plus size={16} aria-hidden /> {t("nav.newOrg")}
          </MenuItem>
        </MenuContent>
      </Menu>

      <div className="flex flex-col gap-1">
        <Link to="/start" className={navItem} onClick={() => setNavOpen(false)}>
          <Home size={18} aria-hidden /> {t("nav.start")}
        </Link>
        <button
          type="button"
          onClick={() => {
            setNavOpen(false);
            openNewRun();
          }}
          className={cn(navItem, "text-left font-medium text-ink")}
        >
          <Plus size={18} aria-hidden /> {t("nav.newRun")}
        </button>
      </div>

      {projects.data?.items.length ? (
        <div>
          <p className="px-3 pb-1 text-sm text-muted">{t("nav.recent")}</p>
          <div className="flex flex-col gap-0.5">
            {projects.data.items.slice(0, 4).map((p) => (
              <Link
                key={p.id}
                to="/projects/$projectId"
                params={{ projectId: p.id }}
                className={cn(navItem, "py-1.5")}
                onClick={() => setNavOpen(false)}
              >
                <span className="truncate">{p.name}</span>
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <p className="px-3 pb-1 text-sm text-muted">{org?.name}</p>
        <Link to="/projects" className={navItem} onClick={() => setNavOpen(false)}>
          <FolderKanban size={18} aria-hidden /> {t("nav.projects")}
        </Link>
        <Link to="/runs" className={navItem} onClick={() => setNavOpen(false)}>
          <ListChecks size={18} aria-hidden /> {t("nav.runs")}
        </Link>
        <Link to="/kb" className={navItem} onClick={() => setNavOpen(false)}>
          <BookOpen size={18} aria-hidden /> {t("nav.kb")}
        </Link>
        <Link to="/audit" className={navItem} onClick={() => setNavOpen(false)}>
          <ScrollText size={18} aria-hidden /> {t("nav.audit")}
        </Link>
        <Link to="/settings" className={navItem} onClick={() => setNavOpen(false)}>
          <Settings size={18} aria-hidden /> {t("nav.settings")}
        </Link>
      </div>

      <div className="mt-auto flex flex-col gap-1 border-t border-line pt-4">
        <button
          type="button"
          className={cn(navItem, "text-left")}
          onClick={() => void i18n.changeLanguage(i18n.language.startsWith("pl") ? "en" : "pl")}
        >
          <Languages size={18} aria-hidden /> {t("nav.language")}
        </button>
        <button
          type="button"
          className={cn(navItem, "text-left")}
          onClick={() => {
            const token = session.token;
            signOut();
            void authConfig().then((cfg) => {
              if (cfg.mode === "oidc") window.location.assign(logoutUrl(cfg));
              if (cfg.mode === "supabase") void signOutRemote(cfg, token);
            });
          }}
        >
          <LogOut size={18} aria-hidden />
          <span className="min-w-0 truncate">
            {t("nav.signOut")} <span className="text-muted">({session.email})</span>
          </span>
        </button>
      </div>
    </nav>
  );

  return (
    <ShellCtx.Provider value={shell}>
      <div className="min-h-screen lg:grid lg:grid-cols-[264px_1fr]">
        <aside className="hidden border-r border-line bg-surface lg:block">
          <div className="sticky top-0 h-screen overflow-y-auto">{sidebar}</div>
        </aside>
        {navOpen ? (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button
              type="button"
              aria-label={t("common.close")}
              className="absolute inset-0 bg-ink/30"
              onClick={() => setNavOpen(false)}
            />
            <aside className="absolute inset-y-0 left-0 w-[280px] overflow-y-auto bg-surface">
              {sidebar}
            </aside>
          </div>
        ) : null}
        <div className="min-w-0">
          <header className="flex items-center gap-3 border-b border-line bg-paper/90 px-4 py-3 backdrop-blur sm:px-8">
            <button
              type="button"
              aria-label={t("nav.label")}
              className="rounded-control p-2 hover:bg-surface lg:hidden"
              onClick={() => setNavOpen(true)}
            >
              <MenuIcon size={20} aria-hidden />
            </button>
            <h1 className="min-w-0 flex-1 truncate font-display text-xl font-bold">{title}</h1>
            {usage.data ? (
              <Link
                to="/settings"
                className="hidden items-center gap-3 rounded-full border border-line bg-surface py-1 pl-3 pr-1 text-sm sm:flex"
              >
                <span className="text-muted">
                  {t("plan.budget", {
                    used: formatEur(used, lang),
                    limit: formatEur(limit, lang),
                  })}
                </span>
                <span className="rounded-full bg-llm/10 px-2.5 py-0.5 font-medium text-llm">
                  {t("plan.pill", {
                    plan: t(`plan.names.${usage.data.plan}`, {
                      defaultValue: usage.data.plan ?? "",
                    }),
                  })}
                </span>
              </Link>
            ) : null}
          </header>
          <main className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-8 sm:py-8">
            <Outlet />
          </main>
        </div>
      </div>
      {newRun ? <NewRunDialog preset={newRun} onClose={() => setNewRun(null)} /> : null}
    </ShellCtx.Provider>
  );
}
