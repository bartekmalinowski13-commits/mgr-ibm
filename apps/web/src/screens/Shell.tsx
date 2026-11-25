import { buttonClass, cn, Menu, MenuContent, MenuItem, MenuTrigger, Sheet } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, Outlet, useNavigate } from "@tanstack/react-router";
import {
  Activity,
  Check,
  ChevronsUpDown,
  Clock,
  FileText,
  FolderKanban,
  Home,
  Languages,
  LogOut,
  Plus,
  Settings,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { type NewRunPreset, type PageOptions, type SheetSlotName, ShellCtx } from "../lib/layout";
import { authConfig, logoutUrl } from "../lib/oidc";
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
  const [page, setPage] = useState<PageOptions>({ header: true });
  const [slots, setSlots] = useState<Partial<Record<SheetSlotName, HTMLElement | null>>>({});
  const slotRef = useMemo(() => {
    const bind = (name: SheetSlotName) => (el: HTMLElement | null) =>
      setSlots((prev) => (prev[name] === el ? prev : { ...prev, [name]: el }));
    return {
      crumbs: bind("crumbs"),
      chips: bind("chips"),
      actions: bind("actions"),
      titleBlock: bind("titleBlock"),
    };
  }, []);
  const [newRun, setNewRun] = useState<NewRunPreset | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const openNewRun = useCallback((preset?: NewRunPreset) => setNewRun(preset ?? {}), []);
  const shell = useMemo(() => ({ setTitle, setPage, openNewRun, slots }), [openNewRun, slots]);

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

  const navItem =
    "flex items-center gap-3 rounded-control border border-transparent px-3 py-2 text-[15px] text-ink hover:bg-sheet/70 " +
    "focus-visible:outline-2 focus-visible:outline-ink data-[status=active]:border-line data-[status=active]:bg-sheet data-[status=active]:font-semibold";
  const projectCount =
    projects.data && !projects.data.next_cursor ? projects.data.items.length : undefined;
  const initials = (org?.name ?? "?")
    .split(/\s+/)
    .map((w) => w.slice(0, 1))
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const close = () => setNavOpen(false);

  const sidebar = (
    <nav aria-label={t("nav.label")} className="flex h-full flex-col gap-5 p-4">
      <Menu>
        <MenuTrigger className="flex w-full items-center gap-3 rounded-control border border-line bg-sheet p-3 text-left hover:border-ink/40 focus-visible:outline-2 focus-visible:outline-ink">
          <span
            aria-hidden
            className="grid size-10 shrink-0 place-items-center rounded-full border-[1.5px] border-ink font-display text-[13px]"
          >
            {initials}
          </span>
          <span className="min-w-0 flex-1">
            <span className="sr-only">{t("nav.switchOrg")}: </span>
            <span className="block truncate font-semibold">{org?.name ?? t("common.loading")}</span>
            <span className="block truncate text-[13.5px] text-muted">
              {[t("sheet.region"), ...(org?.roles.map((r) => t(`settings.roles.${r}`)) ?? [])].join(
                " · ",
              )}
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

      <button
        type="button"
        onClick={() => {
          close();
          openNewRun();
        }}
        className={buttonClass("primary", "md")}
      >
        <Plus size={18} aria-hidden /> {t("nav.newRun")}
      </button>

      <div className="flex flex-col gap-0.5">
        <Link to="/start" className={navItem} onClick={close}>
          <Home size={18} aria-hidden /> {t("nav.start")}
        </Link>
        <Link to="/projects" className={navItem} onClick={close}>
          <FolderKanban size={18} aria-hidden /> <span className="flex-1">{t("nav.projects")}</span>
          {projectCount !== undefined ? (
            <span className="font-data text-[12px] text-muted">{projectCount}</span>
          ) : null}
        </Link>
        <Link to="/runs" className={navItem} onClick={close}>
          <Activity size={18} aria-hidden /> {t("nav.runs")}
        </Link>
      </div>

      {projects.data?.items.length ? (
        <div>
          <p className="px-3 pb-1 text-[13.5px] text-muted">{t("nav.recent")}</p>
          <div className="flex flex-col gap-0.5">
            {projects.data.items.slice(0, 4).map((p) => (
              <Link
                key={p.id}
                to="/projects/$projectId"
                params={{ projectId: p.id }}
                className={cn(navItem, "py-1.5 text-[14px]")}
                onClick={close}
              >
                <span className="truncate">{p.name}</span>
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-0.5">
        <p className="px-3 pb-1 text-[13.5px] text-muted">{t("nav.organisation")}</p>
        <Link to="/kb" className={navItem} onClick={close}>
          <FileText size={18} aria-hidden /> {t("nav.kb")}
        </Link>
        <Link to="/audit" className={navItem} onClick={close}>
          <Clock size={18} aria-hidden /> {t("nav.audit")}
        </Link>
        <Link to="/settings" className={navItem} onClick={close}>
          <Settings size={18} aria-hidden /> {t("nav.settings")}
        </Link>
      </div>

      {usage.data ? (
        <div className="px-3">
          <QuotaChips usage={usage.data.usage} limits={usage.data.limits} scope={orgId} />
        </div>
      ) : null}

      <div className="mt-auto flex flex-col gap-1 border-t border-line pt-4">
        <p className="px-3 text-[14px] leading-snug">
          <span className="block truncate">{session.name || session.email}</span>
          <span className="block truncate text-muted">
            {org?.roles.map((r) => t(`settings.roles.${r}`)).join(", ")}
          </span>
        </p>
        <div className="mt-1 flex flex-wrap gap-1">
          <button
            type="button"
            className={cn(navItem, "py-1.5 text-[14px]")}
            onClick={() => void i18n.changeLanguage(i18n.language.startsWith("pl") ? "en" : "pl")}
          >
            <Languages size={16} aria-hidden /> {t("nav.language")}
          </button>
          <button
            type="button"
            className={cn(navItem, "py-1.5 text-[14px]")}
            title={session.email}
            onClick={() => {
              const token = session.token;
              signOut();
              void authConfig().then((cfg) => {
                if (cfg.mode === "oidc") window.location.assign(logoutUrl(cfg));
                if (cfg.mode === "supabase") void signOutRemote(cfg, token);
              });
            }}
          >
            <LogOut size={16} aria-hidden /> {t("nav.signOut")}
          </button>
        </div>
      </div>
    </nav>
  );

  return (
    <ShellCtx.Provider value={shell}>
      <div className="min-h-screen bg-vellum lg:grid lg:grid-cols-[248px_1fr]">
        <aside className="hidden border-r border-line lg:block">
          <div className="sticky top-0 h-screen overflow-y-auto">{sidebar}</div>
        </aside>
        <div className="min-w-0">
          <header className="flex items-center gap-3 border-b border-line px-4 py-2.5 lg:hidden">
            <NavDrawer
              open={navOpen}
              onOpenChange={setNavOpen}
              label={t("nav.label")}
              closeLabel={t("common.close")}
            >
              {sidebar}
            </NavDrawer>
            <span className="min-w-0 flex-1 truncate font-semibold">{org?.name}</span>
          </header>
          <main className="w-full px-2 py-3 sm:px-4 sm:py-4">
            <Sheet titleBlock={<div ref={slotRef.titleBlock} className="contents" />}>
              <div
                className={cn(
                  "flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line-soft px-4 py-4 sm:px-10 sm:py-5",
                  !page.header && "sr-only",
                )}
              >
                <div className="flex w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[15px] text-muted sm:text-[17px] lg:w-auto lg:flex-1">
                  {/* only the parent crumbs are navigation; the title and chips stay outside */}
                  <nav
                    aria-label={t("sheet.breadcrumb")}
                    className="contents [&:not(:has(a))]:hidden"
                  >
                    <div ref={slotRef.crumbs} className="contents" />
                  </nav>
                  <h1 className="min-w-0 font-semibold text-ink">{title}</h1>
                  <div ref={slotRef.chips} className="contents" />
                </div>
                <div
                  ref={slotRef.actions}
                  className="flex flex-wrap items-center gap-3 empty:hidden"
                />
              </div>
              <div className="px-4 py-6 sm:px-10 sm:py-8">
                <Outlet />
              </div>
            </Sheet>
          </main>
        </div>
      </div>
      {newRun ? <NewRunDialog preset={newRun} onClose={() => setNewRun(null)} /> : null}
    </ShellCtx.Provider>
  );
}
