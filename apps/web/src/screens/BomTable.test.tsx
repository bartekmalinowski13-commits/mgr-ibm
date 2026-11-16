import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../lib/i18n";
import { BomTable } from "./BomTable";

const mk = (line: number, value: string, mpn = "X") => ({
  line,
  refdes: [`R${line}`],
  quantity: 1,
  value,
  footprint: "R_0603",
  manufacturer: "Acme",
  mpn,
  dnp: false,
  provenance: {},
});
const bom = {
  items: [mk(1, "10k", "B"), mk(2, "1k", "C"), mk(3, "100k", "A")],
  findings: [{ rule_id: "r", line: 2, message: "m", severity: "warning" }],
} as never;

afterEach(cleanup);

const dataRows = () =>
  screen.getAllByRole("row").filter((r) => r.getAttribute("data-line") !== null);
const lines = () => dataRows().map((r) => r.getAttribute("data-line"));

describe("BomTable", () => {
  it("sorts by a column on header click and exposes aria-sort", async () => {
    await i18n.changeLanguage("en");
    render(<BomTable bom={bom} onSelect={() => undefined} />);
    expect(lines()).toEqual(["1", "2", "3"]);
    fireEvent.click(screen.getByRole("button", { name: /MPN/ }));
    expect(lines()).toEqual(["3", "1", "2"]);
    expect(screen.getByRole("columnheader", { name: /MPN/ }).getAttribute("aria-sort")).toBe(
      "ascending",
    );
    fireEvent.click(screen.getByRole("button", { name: /MPN/ }));
    expect(lines()).toEqual(["2", "1", "3"]);
  });

  it("filters by text and by findings", async () => {
    await i18n.changeLanguage("en");
    render(<BomTable bom={bom} onSelect={() => undefined} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "100k" } });
    expect(lines()).toEqual(["3"]);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Only with findings/ }));
    expect(lines()).toEqual(["2"]);
  });

  it("hides a column from the column menu", async () => {
    await i18n.changeLanguage("en");
    render(<BomTable bom={bom} onSelect={() => undefined} />);
    expect(screen.queryByRole("columnheader", { name: /Manufacturer/ })).not.toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Manufacturer" }));
    expect(screen.queryByRole("columnheader", { name: /Manufacturer/ })).toBeNull();
  });

  it("copies the visible lines as CSV", async () => {
    await i18n.changeLanguage("en");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<BomTable bom={bom} onSelect={() => undefined} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "100k" } });
    fireEvent.click(screen.getByRole("button", { name: /Copy CSV/ }));
    expect(writeText).toHaveBeenCalledOnce();
    const csv = writeText.mock.calls[0]?.[0] as string;
    expect(csv.split("\n")).toHaveLength(2);
    expect(csv).toContain("100k");
  });

  it("renders only a window of a very large BOM", async () => {
    await i18n.changeLanguage("en");
    const big = { items: Array.from({ length: 5000 }, (_, i) => mk(i + 1, `v${i}`)), findings: [] };
    render(<BomTable bom={big as never} onSelect={() => undefined} />);
    expect(dataRows().length).toBeGreaterThan(0);
    expect(dataRows().length).toBeLessThan(100);
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").length).toBeGreaterThan(
      3,
    );
  });
});
