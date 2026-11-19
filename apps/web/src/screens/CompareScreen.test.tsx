import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
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
}));
vi.mock("../lib/session", () => ({ useSession: () => ({ orgId: "org" }) }));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("../router", () => ({
  compareRoute: { useParams: () => ({ projectId: "p" }), useSearch: () => ({}) },
}));

const { CompareScreen } = await import("./CompareScreen");

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
