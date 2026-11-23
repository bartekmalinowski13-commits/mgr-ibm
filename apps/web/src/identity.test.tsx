import { ProvenanceRail, RunPath, Segmented, TitleBlock } from "@bomagent/ui";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { advanceLive, EMPTY_LIVE, stagesFromTrace } from "./lib/runPath";
import { revisionLetter } from "./screens/RunTitleBlock";

afterEach(cleanup);

describe("live run stages", () => {
  const ev = (steps: number, step: string, calls: number) => ({
    status: "running",
    steps,
    step,
    usage: { llm_calls: calls },
  });
  it("marks a stage as LLM when the call counter rose", () => {
    let s = advanceLive(EMPTY_LIVE, ev(1, "normalize_group", 0));
    s = advanceLive(s, ev(2, "select_mpn:C1", 1));
    expect(s.stages.map((x) => x.actor)).toEqual(["rule", "llm"]);
    expect(s.drawIndex).toBe(1);
  });
  it("ignores repeated events and fills gaps", () => {
    const s = advanceLive(EMPTY_LIVE, ev(1, "a", 0));
    expect(advanceLive(s, ev(1, "a", 0))).toBe(s);
    expect(advanceLive(s, ev(3, "c", 2)).stages.map((x) => x.node)).toEqual(["a", "…", "c"]);
  });
  it("builds stages from a trace", () => {
    expect(stagesFromTrace([{ node: "validate", duration_s: 1, llm_calls: 0 }])[0]?.actor).toBe(
      "rule",
    );
  });
});

describe("signature components", () => {
  it("RunPath is an image with a text description and draws the finished segment", () => {
    const { container } = render(
      <RunPath
        variant="B"
        description="Variant B run path"
        drawIndex={0}
        complete
        steps={[
          { id: "a", label: "Parse", actor: "parser" },
          { id: "b", label: "MPN", actor: "llm" },
        ]}
      />,
    );
    expect(screen.getByRole("img", { name: "Variant B run path" })).toBeTruthy();
    expect(container.querySelectorAll("path.path-draw")).toHaveLength(1);
  });
  it("ProvenanceRail is decorative and carries the kind", () => {
    const { container } = render(<ProvenanceRail kind="agent" label="LLM agent" />);
    expect(container.querySelector('[data-provenance="agent"]')?.getAttribute("aria-hidden")).toBe(
      "true",
    );
    expect(screen.getByText("LLM agent")).toBeTruthy();
  });
  it("TitleBlock shows the demo flag instead of the status", () => {
    render(
      <TitleBlock
        label="Title block"
        title="ECG"
        revision="Rev. B"
        run="Run 1"
        date="23.11.2026"
        status="Done"
        demo="Illustrative"
        variant="Variant B"
        sheet="1/1"
        sheetLabel="Sheet"
      />,
    );
    expect(screen.getByText("Illustrative")).toBeTruthy();
    expect(screen.queryByText("Done")).toBeNull();
  });
  it("Segmented toggles with aria-pressed", () => {
    const onChange = vi.fn();
    render(
      <Segmented
        label="Filters"
        value="all"
        onChange={onChange}
        options={[
          { value: "all", label: "All" },
          { value: "x", label: "X" },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "X" }));
    expect(onChange).toHaveBeenCalledWith("x");
  });
  it("revision letters follow the BOM version", () => {
    expect([1, 2, 26, 27].map(revisionLetter)).toEqual(["A", "B", "Z", "27"]);
  });
});
