import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../lib/i18n";

const openNewRun = vi.fn();
vi.mock("../lib/layout", () => ({
  usePageTitle: () => undefined,
  useShell: () => ({ openNewRun }),
  SheetSlot: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../lib/session", () => ({
  useSession: () => ({ session: { name: "Anna Nowak", email: "a@x.pl" }, orgId: "o1" }),
}));
const runs = [
  {
    id: "aaaaaaaa-1111",
    project_id: "p1",
    variant: "B",
    status: "completed",
    error: null,
    usage: { cost_eur: 0.36, wall_time_s: 128 },
  },
  {
    id: "bbbbbbbb-2222",
    project_id: "p1",
    variant: "A",
    status: "failed",
    error: "brak pliku",
    usage: { cost_eur: 0, wall_time_s: 4 },
  },
];
vi.mock("../lib/queries", () => ({
  useProjects: () => ({
    data: { items: [{ id: "p1", name: "Holter EKG 3-kan.", is_sample: false }] },
  }),
  useRuns: () => ({ data: { items: runs } }),
  useMe: () => ({ data: { organizations: [{ org_id: "o1", name: "Nordvital", roles: [] }] } }),
  useModels: () => ({ data: [{ id: "mistral-large-eu" }] }),
  useUsage: () => ({
    data: {
      plan: "pilot",
      usage: { cost_eur: 24.8, members: 4 },
      limits: { llm_budget_eur_per_month: 40 },
    },
  }),
  useIsOwner: () => false,
  useIsAdmin: () => true,
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => <a href="/">{children}</a>,
}));

const { StartScreen } = await import("./StartScreen");
await i18n.changeLanguage("pl");
afterEach(cleanup);

describe("StartScreen", () => {
  it("greets by first name", () => {
    render(<StartScreen />);
    expect(screen.getByRole("heading", { name: "Cześć, Anna." })).toBeTruthy();
  });

  it("opens the new-run dialog from the blank cell and the templates", () => {
    openNewRun.mockReset();
    render(<StartScreen />);
    fireEvent.click(screen.getByRole("button", { name: /Pusty projekt/ }));
    expect(openNewRun).toHaveBeenLastCalledWith();
    fireEvent.click(screen.getByRole("button", { name: /Holter EKG, 3 kanały/ }));
    expect(openNewRun).toHaveBeenLastCalledWith({ template: "ecg" });
    fireEvent.click(screen.getByRole("button", { name: /Pompa infuzyjna/ }));
    expect(openNewRun).toHaveBeenLastCalledWith({ template: "infusion" });
  });

  it("lists recent runs with number, project, cost and time", () => {
    render(<StartScreen />);
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1] as HTMLElement).getByText("#aaaaaaaa")).toBeTruthy();
    expect(within(rows[1] as HTMLElement).getByText("2 min 08 s")).toBeTruthy();
    expect(within(rows[2] as HTMLElement).getByText(/Nieudany: brak pliku/)).toBeTruthy();
  });

  it("fills the title block", () => {
    render(<StartScreen />);
    expect(screen.getByText("Nordvital")).toBeTruthy();
    expect(screen.getByText(/62% z/)).toBeTruthy();
  });
});
