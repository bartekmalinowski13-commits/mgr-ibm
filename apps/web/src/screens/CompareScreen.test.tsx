import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../lib/i18n";
import pl from "../locales/pl.json";

const get = vi.fn();
vi.mock("../lib/api", async (orig) => ({
  ...(await orig<typeof import("../lib/api")>()),
  api: { GET: (...args: unknown[]) => get(...args) },
}));
const runsData = vi.fn();
vi.mock("../lib/queries", () => ({
  useRuns: () => ({ isPending: false, isError: false, data: { items: runsData() } }),
  useProjects: () => ({ data: { items: [{ id: "p", name: "Holter" }] } }),
}));
vi.mock("../lib/session", () => ({ useSession: () => ({ orgId: "org" }) }));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children }: { children: ReactNode }) => <a href="/x">{children}</a>,
}));
vi.mock("../router", () => ({
  compareRoute: { useParams: () => ({ projectId: "p" }), useSearch: () => ({}) },
}));

const { CompareScreen, diffBoms, verdict } = await import("./CompareScreen");

const run = (id: string, variant: "A" | "B") => ({
  id,
  variant,
  status: "completed",
  model_id: "m",
  usage: {},
});
const bom = {
  run_id: "a",
  bom: {
    items: [{ line: 1, refdes: ["R1"], quantity: 1, value: "10k", provenance: {} }],
    findings: [],
  },
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompareScreen />
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("pl");
  get.mockReset();
  runsData.mockReset();
});
afterEach(cleanup);

describe("CompareScreen error states (I-3)", () => {
  it("shows an error, never 'no differences', when a BOM fails to load", async () => {
    runsData.mockReturnValue([run("a", "A"), run("b", "B")]);
    get.mockImplementation(async (_path: string, opts: { params: { path: { run_id: string } } }) =>
      opts.params.path.run_id === "a"
        ? { data: bom, response: new Response(null, { status: 200 }) }
        : { error: "<html>502</html>", response: new Response(null, { status: 502 }) },
    );
    renderScreen();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(pl.httpErrors["5xx"]);
    expect(screen.queryByText(pl.compare.same)).toBeNull();
    expect(screen.getByRole("button", { name: pl.common.retry })).toBeTruthy();
  });

  it("asks for two variants instead of loading forever when one variant has no run", () => {
    runsData.mockReturnValue([run("b1", "B"), run("b2", "B")]);
    renderScreen();
    expect(screen.getByText(pl.compare.needTwo)).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("verdict", () => {
  const base = { costA: 0, costB: 0, findingsA: 0, findingsB: 0, differences: 3 };
  it("says the hybrid is cheaper with the real ratio", () => {
    expect(verdict({ ...base, costA: 1.2, costB: 0.4 })).toEqual({
      key: "compare.verdict.cheaper",
      params: { x: 3 },
    });
  });
  it("says it is pricier when B costs clearly more", () => {
    expect(verdict({ ...base, costA: 0.2, costB: 0.5 }).key).toBe("compare.verdict.pricier");
  });
  it("falls back to findings, then to a neutral sentence", () => {
    expect(verdict({ ...base, findingsA: 5, findingsB: 2 }).key).toBe(
      "compare.verdict.fewerFindings",
    );
    expect(verdict({ ...base, findingsA: 1, findingsB: 4 }).key).toBe(
      "compare.verdict.moreFindings",
    );
    expect(verdict(base).key).toBe("compare.verdict.differ");
  });
  it("reports identical results", () => {
    expect(verdict({ ...base, differences: 0 }).key).toBe("compare.verdict.same");
  });
});

describe("CompareScreen content", () => {
  it("lists the differing lines with both MPNs and a verdict from real data", async () => {
    runsData.mockReturnValue([run("a", "A"), run("b", "B")]);
    const mk = (mpn: string) => ({
      run_id: "x",
      bom: {
        items: [{ line: 1, refdes: ["U1"], quantity: 1, mpn, provenance: {} }],
        findings: [],
      },
    });
    get.mockImplementation(async (_p: string, opts: { params: { path: { run_id: string } } }) => ({
      data: opts.params.path.run_id === "a" ? mk("AAA-1") : mk("BBB-2"),
      response: new Response(null, { status: 200 }),
    }));
    renderScreen();
    expect(await screen.findByText("A AAA-1")).toBeTruthy();
    expect(screen.getByText("B BBB-2")).toBeTruthy();
    expect(screen.getByText(pl.compare.result.differ)).toBeTruthy();
    expect(screen.getByRole("table", { name: pl.compare.metrics })).toBeTruthy();
  });

  it("diffBoms marks lines present in one variant only", () => {
    const a = { items: [{ refdes: ["R1"], mpn: "X" }], findings: [] };
    const b = { items: [], findings: [] };
    // biome-ignore lint/suspicious/noExplicitAny: minimal fixtures
    const [d] = diffBoms(a as any, b as any);
    expect(d?.b).toBeUndefined();
    expect(d?.changed.length).toBe(3);
  });

  it("diffBoms treats notations of the same value as equal", () => {
    const item = (refdes: string, value: string) => ({ refdes: [refdes], value, mpn: "X" });
    const a = {
      items: [
        item("C1", "100 nF"),
        item("R1", "4.7 kΩ"),
        item("R2", "10 MΩ"),
        item("FB1", "220 Ω @ 100 MHz"),
        item("U1", "AD8232"),
        item("C2", "10 nF"),
      ],
      findings: [],
    };
    const b = {
      items: [
        item("C1", "100n"),
        item("R1", "4k7"),
        item("R2", "10M"),
        item("FB1", "220R@100MHz"),
        item("U1", "ad8232"),
        item("C2", "100n"),
      ],
      findings: [],
    };
    // biome-ignore lint/suspicious/noExplicitAny: minimal fixtures
    const diffs = diffBoms(a as any, b as any);
    const changed = Object.fromEntries(diffs.map((d) => [d.refdes, d.changed]));
    for (const r of ["C1", "R1", "R2", "FB1", "U1"]) expect(changed[r]).toEqual([]);
    expect(changed.C2).toEqual(["value"]);
  });
});
