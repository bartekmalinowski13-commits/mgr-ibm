import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { NavDrawer } from "./NavDrawer";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <NavDrawer open={open} onOpenChange={setOpen} label="Navigation" closeLabel="Close">
        <nav>
          <a href="/start">Start</a>
          <button type="button" onClick={() => setOpen(false)}>
            Projects
          </button>
        </nav>
      </NavDrawer>
      <button type="button">page behind</button>
    </>
  );
}

afterEach(cleanup);

describe("mobile navigation drawer (I-5)", () => {
  it("is a labelled modal dialog that takes focus and reports its state on the trigger", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Navigation" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Navigation" });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(trigger.getAttribute("aria-controls")).toBe(dialog.id);
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Navigation" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("returns focus to the trigger when a link inside closes it", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Navigation" });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("button", { name: "Projects" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("hides the page behind from assistive technology while open", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Navigation" }));
    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "page behind" })).toBeNull();
  });
});
