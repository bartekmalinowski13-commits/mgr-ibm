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
import { NavDrawer } from "./NavDrawer";
import { NewRunDialog } from "./NewRunDialog";
import { QuotaChips } from "./QuotaChips";

export function Shell() {
  const { t, i18n } = useTranslation();
  const { session, orgId, selectOrg, signOut } = useSession();
  const me = useMe();
  const [title, setTitle] = useState("");
  const [newRun, setNewRun] = useState<NewRunPreset | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [desk, setDesk] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const openNewRun = useCallback((preset?: NewRunPreset) => setNewRun(preset ?? {}), []);
  const shell = useMemo(() => ({ setTitle, openNewRun, setDesk }), [openNewRun]);

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
    "flex items-center gap-3 px-3 py-2 text-[15px] text-on-ink hover:bg-ink-hover hover:text-sheet " +
    "data-[status=active]:bg-sheet data-[status=active]:font-semibold data-[status=active]:text-ink";

  const sidebar = (
    <nav
      aria-label={t("nav.label")}
      className="on-ink flex h-full flex-col gap-6 bg-ink p-4 text-sheet"
    >
      <Menu>
        <MenuTrigger className="flex w-full items-center gap-3 border border-sheet p-2.5 text-left hover:bg-ink-hover">
          <span
            aria-hidden
            className="grid size-9 shrink-0 place-items-center bg-sheet font-display text-lg font-semibold text-ink"
          >
            {(org?.name ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="sr-only">{t("nav.switchOrg")}: </span>
            <span className="block truncate font-medium">{org?.name ?? t("common.loading")}</span>
            <span className="block truncate text-sm text-desk">
              {org?.roles.map((r) => t(`settings.roles.${r}`)).join(", ")}
            </span>
          </span>
          <ChevronsUpDown size={16} aria-hidden className="text-desk" />
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
          className={cn(navItem, "border border-sheet text-left font-semibold text-sheet")}
        >
          <Plus size={18} aria-hidden /> {t("nav.newRun")}
        </button>
      </div>

      {projects.data?.items.length ? (
        <div>
          <p className="px-3 pb-1 text-sm text-desk">{t("nav.recent")}</p>
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
        <p className="px-3 pb-1 text-sm text-desk">{org?.name}</p>
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

      <div className="mt-auto flex flex-col gap-1 border-t border-ink-soft pt-4">
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
            {t("nav.signOut")} <span className="text-desk">({session.email})</span>
          </span>
        </button>
      </div>
    </nav>
  );

  return (
    <ShellCtx.Provider value={shell}>
      <div className="min-h-screen lg:grid lg:grid-cols-[264px_1fr]">
        <aside className="hidden border-r border-ink bg-ink lg:block">
          <div className="sticky top-0 h-screen overflow-y-auto">{sidebar}</div>
        </aside>
        <div className="min-w-0">
          <header className="flex items-center gap-3 border-b border-ink bg-sheet px-4 py-3 sm:px-8">
            <NavDrawer
              open={navOpen}
              onOpenChange={setNavOpen}
              label={t("nav.label")}
              closeLabel={t("common.close")}
            >
              {sidebar}
            </NavDrawer>
            <h1 className="min-w-0 flex-1 truncate font-display text-2xl font-semibold tracking-[-0.01em]">
              {title}
            </h1>
            {usage.data ? (
              <QuotaChips usage={usage.data.usage} limits={usage.data.limits} scope={orgId} />
            ) : null}
            {usage.data ? (
              <Link
                to="/settings"
                className="hidden items-center gap-3 border border-ink bg-sheet py-1 pl-3 pr-1 text-sm hover:bg-tint sm:flex"
              >
                <span className="text-ink-soft">
                  {t("plan.budget", {
                    used: formatEur(used, lang),
                    limit: formatEur(limit, lang),
                  })}
                </span>
                <span className="border-l border-ink px-2.5 py-0.5 font-medium">
                  {t("plan.pill", {
                    plan: t(`plan.names.${usage.data.plan}`, {
                      defaultValue: usage.data.plan ?? "",
                    }),
                  })}
                </span>
              </Link>
            ) : null}
          </header>
          <main
            className={
              desk
                ? "min-h-[calc(100vh-57px)] bg-desk p-3 sm:p-5"
                : "mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-8 sm:py-8"
            }
          >
            <Outlet />
          </main>
        </div>
      </div>
      {newRun ? <NewRunDialog preset={newRun} onClose={() => setNewRun(null)} /> : null}
    </ShellCtx.Provider>
  );
}
