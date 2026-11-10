import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MockApi } from "./api/mock";
import { makeRouter } from "./router";
import { AppProvider } from "./state";

function renderApp(path: string, mock?: MockApi) {
  const router = makeRouter(createMemoryHistory({ initialEntries: [path] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AppProvider api={mock ?? ((org) => new MockApi(org))}>
        <RouterProvider router={router} />
      </AppProvider>
    </QueryClientProvider>,
  );
  return { router };
}

describe("app (mock API)", () => {
  it("greets the user and summarises the organisation", async () => {
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Cześć, Bartek" })).toBeInTheDocument();
    expect(await screen.findByText("2 zakończone przebiegi")).toBeInTheDocument();
    expect(await screen.findByText("1 projekt")).toBeInTheDocument();
  });

  it("shows a BOM with provenance and filters lines with findings", async () => {
    const api = new MockApi();
    const runB = (await api.listRuns()).items.find((r) => r.variant === "B");
    renderApp(`/runs/${runB?.id}`, api);
    const table = await screen.findByRole("table");
    // header row + 22 lines
    expect(within(table).getAllByRole("row")).toHaveLength(23);
    expect(within(table).getAllByText("agent LLM").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("reguła").length).toBeGreaterThan(0);

    await userEvent.click(screen.getByLabelText("Tylko pozycje z uwagami"));
    // review findings on J1, J2, TP1/TP2; the R9 info finding is not an issue
    expect(within(table).getAllByRole("row")).toHaveLength(4);

    await userEvent.click(within(table).getByRole("button", { name: "J1" }));
    const sheet = await screen.findByRole("dialog", { name: "Szczegóły pozycji 9" });
    expect(within(sheet).getByText(/patient connection/)).toBeInTheDocument();
  });

  it("a reviewer corrects a line: the decision is marked as made by a person", async () => {
    const api = new MockApi();
    const runB = (await api.listRuns()).items.find((r) => r.variant === "B");
    renderApp(`/runs/${runB?.id}`, api);
    const table = await screen.findByRole("table");
    await userEvent.click(within(table).getByRole("button", { name: "J1" }));
    const sheet = await screen.findByRole("dialog", { name: "Szczegóły pozycji 9" });
    const mpn = within(sheet).getByLabelText("MPN");
    await userEvent.clear(mpn);
    await userEvent.type(mpn, "22-23-2041");
    await userEvent.click(within(sheet).getByRole("button", { name: "Zapisz poprawkę" }));
    expect(await within(sheet).findByText("Napisz krótko, dlaczego")).toBeInTheDocument();
    await userEvent.type(within(sheet).getByLabelText("Uzasadnienie*"), "4-pin w magazynie");
    await userEvent.click(within(sheet).getByRole("button", { name: "Zapisz poprawkę" }));

    await waitFor(async () => {
      const bom = await api.getBom(runB?.id ?? "");
      expect(bom.items.find((i) => i.line === 9)?.provenance.mpn?.kind).toBe("user");
    });
    expect(await screen.findByText("Po przeglądzie · 1 poprawka")).toBeInTheDocument();
  });

  it("switching organisation shows only that organisation's data", async () => {
    renderApp("/projects");
    expect(
      (await screen.findAllByRole("link", { name: /Monitor EKG, 1 odprowadzenie/ })).length,
    ).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Przełącz organizację" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Zespół badawczy IBM/ }));
    expect(await screen.findByText(/Nie masz jeszcze projektów/)).toBeInTheDocument();
    expect(screen.queryAllByRole("link", { name: /Monitor EKG, 1 odprowadzenie/ })).toHaveLength(0);
  });

  it("lists the organisation's documents next to the shared corpus", async () => {
    renderApp("/knowledge");
    expect(await screen.findByText("AD8232 – karta katalogowa")).toBeInTheDocument();
    expect(screen.getAllByText("Wspólny korpus").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Twoja organizacja").length).toBeGreaterThan(0);
  });

  it("starts both variants and lands on the comparison", async () => {
    const { router } = renderApp("/runs");
    const [openDialog] = await screen.findAllByRole("button", { name: "Nowy przebieg" });
    await userEvent.click(openDialog as HTMLElement);
    const dialog = await screen.findByRole("dialog", { name: "Nowy przebieg" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Uruchom przebieg" }));
    expect(await within(dialog).findByText("To pole jest wymagane")).toBeInTheDocument();

    await userEvent.type(within(dialog).getByLabelText("Nazwa*"), "Monitor EKG – test");
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Wersja projektu*")).not.toHaveValue(""),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Uruchom przebieg" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/compare"));
    expect(router.state.location.search).toMatchObject({
      a: expect.any(String),
      b: expect.any(String),
    });
  });
});
