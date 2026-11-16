import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../lib/i18n";
import type { BomItem } from "../lib/provenance";
import { ItemPanel } from "./ItemPanel";

vi.mock("../lib/session", () => ({ useSession: () => ({ orgId: "org" }) }));

const item = { line: 3, refdes: ["R1"], quantity: 1, provenance: {} } as unknown as BomItem;
const client = new QueryClient();

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <QueryClientProvider client={client}>
      <button type="button" data-testid="row" onClick={() => setOpen(true)}>
        row
      </button>
      {open ? (
        <ItemPanel runId="r" item={item} findings={[]} onClose={() => setOpen(false)} />
      ) : null}
    </QueryClientProvider>
  );
}

afterEach(cleanup);

describe("ItemPanel focus management (UX-06)", () => {
  it("moves focus into the panel on open and back to the row on Esc", () => {
    render(<Harness />);
    const row = screen.getByTestId("row");
    row.focus();
    fireEvent.click(row);
    const panel = screen.getByRole("complementary");
    expect(panel.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(document.activeElement).toBe(row);
  });

  it("returns focus to the row when closed with the close button", () => {
    render(<Harness />);
    const row = screen.getByTestId("row");
    row.focus();
    fireEvent.click(row);
    fireEvent.click(screen.getByRole("button", { name: /close|zamknij/i }));
    expect(document.activeElement).toBe(row);
  });

  it("wraps Tab inside the panel while it is a drawer", () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId("row"));
    const panel = screen.getByRole("complementary");
    const items = [
      ...panel.querySelectorAll<HTMLElement>("button, input, textarea, [tabindex]"),
    ].filter((el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled);
    const first = items[0] as HTMLElement;
    const last = items[items.length - 1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("has a polite live region for save announcements", () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId("row"));
    const live = screen.getByRole("status");
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("");
  });
});
