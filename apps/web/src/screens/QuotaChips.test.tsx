import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import i18n from "../lib/i18n";
import { ToastProvider } from "../lib/toast";
import { QuotaChips } from "./QuotaChips";

afterEach(cleanup);
const limits = { max_runs_per_month: 10, llm_budget_eur_per_month: 20 };

function view(usage: Record<string, number>) {
  return render(
    <ToastProvider>
      <QuotaChips usage={usage} limits={limits} scope="org" />
    </ToastProvider>,
  );
}

describe("QuotaChips", () => {
  it("shows a chip per limited metric with its level, in the UI language", async () => {
    await i18n.changeLanguage("en");
    view({ runs: 8, cost_eur: 1 });
    const list = screen.getByRole("list", { name: /Plan usage/ });
    const items = Array.from(list.querySelectorAll("li"));
    expect(items.map((i) => i.dataset.level)).toEqual(["warn", "ok"]);
    expect(items[0]?.textContent).toBe("Runs 8/10");
  });

  it("announces a threshold crossing once", async () => {
    await i18n.changeLanguage("en");
    const { rerender } = view({ runs: 8, cost_eur: 1 });
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual([
      "Runs: you have used 80 % of this month's limit.",
    ]);
    rerender(
      <ToastProvider>
        <QuotaChips usage={{ runs: 9, cost_eur: 1 }} limits={limits} scope="org" />
      </ToastProvider>,
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("stays quiet below the threshold", async () => {
    await i18n.changeLanguage("pl");
    view({ runs: 1, cost_eur: 1 });
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });
});
