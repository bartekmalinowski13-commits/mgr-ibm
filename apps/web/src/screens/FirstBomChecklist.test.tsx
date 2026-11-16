import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../lib/i18n";
import { FirstBomChecklist } from "./FirstBomChecklist";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to, onClick }: { children: ReactNode; to: string; onClick?: () => void }) => (
    <a href={to} onClick={onClick}>
      {children}
    </a>
  ),
}));

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const noop = () => undefined;

describe("FirstBomChecklist", () => {
  it("offers the first open step for a new organisation, in both languages", async () => {
    await i18n.changeLanguage("en");
    render(
      <FirstBomChecklist
        counts={{ projects: 0, runs: 0, completed: 0 }}
        onNewProject={noop}
        onNewRun={noop}
      />,
    );
    expect(screen.getByText("Your first BOM in 3 steps")).not.toBeNull();
    expect(screen.getByText("0 of 3 done")).not.toBeNull();
    expect(screen.getByRole("link", { name: "New project" })).not.toBeNull();
    cleanup();
    await i18n.changeLanguage("pl");
    render(
      <FirstBomChecklist
        counts={{ projects: 0, runs: 0, completed: 0 }}
        onNewProject={noop}
        onNewRun={noop}
      />,
    );
    expect(screen.getByText("Twój pierwszy BOM w 3 krokach")).not.toBeNull();
  });

  it("moves on to the next step and calls the run action", async () => {
    await i18n.changeLanguage("en");
    const onNewRun = vi.fn();
    render(
      <FirstBomChecklist
        counts={{ projects: 1, runs: 0, completed: 0 }}
        onNewProject={noop}
        onNewRun={onNewRun}
      />,
    );
    expect(screen.getByText("1 of 3 done")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "New run" }));
    expect(onNewRun).toHaveBeenCalledOnce();
  });

  it("disappears when complete or dismissed (and stays dismissed)", async () => {
    await i18n.changeLanguage("en");
    const done = render(
      <FirstBomChecklist
        counts={{ projects: 1, runs: 1, completed: 1 }}
        onNewProject={noop}
        onNewRun={noop}
      />,
    );
    expect(screen.queryByTestId("first-bom-checklist")).toBeNull();
    done.unmount();
    const open = render(
      <FirstBomChecklist
        counts={{ projects: 0, runs: 0, completed: 0 }}
        onNewProject={noop}
        onNewRun={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Hide checklist" }));
    expect(screen.queryByTestId("first-bom-checklist")).toBeNull();
    open.unmount();
    render(
      <FirstBomChecklist
        counts={{ projects: 0, runs: 0, completed: 0 }}
        onNewProject={noop}
        onNewRun={noop}
      />,
    );
    expect(screen.queryByTestId("first-bom-checklist")).toBeNull();
  });
});
