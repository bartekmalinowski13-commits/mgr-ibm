import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { clsx } from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../state";
import { NewRunDialog } from "./NewRunDialog";

function Icon({ d }: { d: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className="size-[18px] shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden
    >
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICONS = {
  home: "M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3.5v-4.5h-5V17H4a1 1 0 0 1-1-1z",
  bell: "M10 3a4.5 4.5 0 0 0-4.5 4.5c0 4-1.5 5.5-1.5 5.5h12s-1.5-1.5-1.5-5.5A4.5 4.5 0 0 0 10 3zM8.5 16a1.6 1.6 0 0 0 3 0",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zm4.5-1.5L17 17",
  plus: "M10 4v12M4 10h12",
  folder: "M3 6a1 1 0 0 1 1-1h4l1.5 2H16a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
  play: "M6 4.5v11l9-5.5z",
  compare: "M4 5h5v10H4zM11 8h5v7h-5z",
  book: "M4 4.5h5a2 2 0 0 1 2 2V16a2 2 0 0 0-2-2H4zM16 4.5h-5",
  shield: "M10 3 4 5.5v4.5c0 3.5 2.6 6 6 7 3.4-1 6-3.5 6-7V5.5z",
  cog: "M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4",
};

function NavItem({
  to,
  icon,
  children,
}: {
  to: string;
  icon: keyof typeof ICONS;
  children: ReactNode;
}) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const active = to === "/" ? path === "/" : path.startsWith(to);
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={clsx(
        "flex items-center gap-3 rounded-[var(--radius-control)] px-2.5 py-1.5 text-[13.5px] whitespace-nowrap",
        active ? "bg-paper font-medium text-ink" : "text-ink-soft hover:bg-paper",
      )}
    >
      <Icon d={ICONS[icon]} />
      {children}
    </Link>
  );
}

function OrgSwitcher() {
  const { t } = useTranslation();
  const { api, orgId, setOrgId } = useApp();
  const { data: orgs = [] } = useQuery({ queryKey: ["orgs"], queryFn: () => api.organisations() });
  const current = orgs.find((o) => o.id === orgId) ?? orgs[0];
  const initials = (current?.name ?? "··")
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("");
  return (
    <Dropdown.Root>
      <Dropdown.Trigger
        className="flex w-full items-center gap-2.5 rounded-[var(--radius-control)] px-2 py-1.5 text-left hover:bg-paper"
        aria-label={t("nav.switchOrg")}
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-ink text-[12px] font-semibold text-white">
          {initials}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold">{current?.name}</span>
        <Icon d="M6 8l4 4 4-4" />
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="start"
          sideOffset={6}
          className="z-50 min-w-[240px] rounded-[var(--radius-card)] border border-line bg-surface p-1.5 shadow-[0_8px_30px_rgba(21,24,30,0.12)]"
        >
          {orgs.map((o) => (
            <Dropdown.Item
              key={o.id}
              onSelect={() => setOrgId(o.id)}
              className="flex cursor-pointer items-center justify-between gap-3 rounded-md px-2.5 py-2 text-[13.5px] outline-none data-[highlighted]:bg-paper"
            >
              {o.name}
              {o.id === current?.id && <span aria-hidden>✓</span>}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function Sidebar() {
  const { t } = useTranslation();
  const { api, orgId, openNewRun } = useApp();
  const { data } = useQuery({ queryKey: [orgId, "projects"], queryFn: () => api.listProjects() });
  return (
    <aside className="flex flex-col gap-2 border-b border-line bg-surface px-3 py-3 lg:sticky lg:gap-5 lg:border-b-0 lg:py-4 lg:top-0 lg:h-screen lg:border-r">
      <OrgSwitcher />
      <nav aria-label="Main" className="flex gap-0.5 overflow-x-auto lg:flex-col">
        <NavItem to="/" icon="home">
          {t("nav.start")}
        </NavItem>
        <NavItem to="/notifications" icon="bell">
          {t("nav.notifications")}
        </NavItem>
        <button
          type="button"
          onClick={() => openNewRun()}
          className="flex items-center gap-3 rounded-[var(--radius-control)] px-2.5 py-1.5 text-left text-[13.5px] whitespace-nowrap text-ink-soft hover:bg-paper"
        >
          <span className="grid size-[18px] place-items-center rounded-full bg-ink text-white">
            <svg viewBox="0 0 20 20" className="size-3" aria-hidden>
              <path d={ICONS.plus} stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
            </svg>
          </span>
          {t("nav.newRun")}
        </button>
      </nav>
      <section className="hidden lg:block">
        <h2 className="px-2.5 pb-1 text-[12px] text-muted">{t("nav.yourProjects")}</h2>
        <ul className="flex flex-col gap-0.5">
          {data?.items.slice(0, 4).map((p) => (
            <li key={p.id}>
              <Link
                to="/projects/$projectId"
                params={{ projectId: p.id }}
                className="block truncate rounded-md px-2.5 py-1 text-[13px] text-ink-soft hover:bg-paper"
              >
                {p.name}
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <nav aria-label="Organisation" className="flex gap-0.5 overflow-x-auto lg:flex-col">
        <NavItem to="/projects" icon="folder">
          {t("nav.projects")}
        </NavItem>
        <NavItem to="/runs" icon="play">
          {t("nav.runs")}
        </NavItem>
        <NavItem to="/compare" icon="compare">
          {t("nav.compare")}
        </NavItem>
        <NavItem to="/audit" icon="shield">
          {t("nav.audit")}
        </NavItem>
        <NavItem to="/settings" icon="cog">
          {t("nav.settings")}
        </NavItem>
      </nav>
      <div className="mt-auto hidden px-2.5 font-[family-name:var(--font-display)] text-[15px] font-extrabold tracking-[0.12em] lg:block">
        BOM AGENT
      </div>
    </aside>
  );
}

function Topbar() {
  const { t } = useTranslation();
  const { api } = useApp();
  const path = useRouterState({ select: (s) => s.location.pathname });
  const section =
    path === "/" ? t("nav.start") : t(`nav.${path.split("/")[1]}`, { defaultValue: "" });
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line px-6 py-3 lg:px-10">
      <span className="text-[13.5px] text-ink-soft">{section}</span>
      <div className="flex items-center gap-2">
        {api.mode === "mock" && (
          <span className="hidden rounded-[var(--radius-chip)] border border-line-strong px-2.5 py-0.5 text-[12px] text-muted md:inline">
            {t("mock")}
          </span>
        )}
        <span className="flex items-center gap-2 rounded-[var(--radius-chip)] bg-llm-bg py-0.5 pr-3 pl-0.5 text-[12.5px] text-llm">
          <span className="grid size-5 place-items-center rounded-full bg-llm text-[11px] font-semibold text-white">
            15
          </span>
          {t("plan.trialLeft", { days: 15 })}
          <Link to="/settings" className="font-semibold underline-offset-2 hover:underline">
            {t("plan.seePlans")}
          </Link>
        </span>
      </div>
    </div>
  );
}

export function AppShell() {
  const { toast } = useApp();
  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)]">
      <Sidebar />
      <div className="min-w-0">
        <Topbar />
        <main className="mx-auto w-full max-w-[1280px] px-6 py-8 lg:px-10">
          <Outlet />
        </main>
      </div>
      <NewRunDialog />
      <div
        role="status"
        aria-live="polite"
        className={clsx(
          "fixed right-5 bottom-5 rounded-[var(--radius-control)] bg-ink px-4 py-2.5 text-[13px] text-white transition-all",
          toast ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-2 opacity-0",
        )}
      >
        {toast}
      </div>
    </div>
  );
}
