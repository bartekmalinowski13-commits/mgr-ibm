import { describe, expect, it } from "vitest";
import { IntentKeys } from "./idempotency";

describe("one idempotency key per user intent (I-2)", () => {
  it("reuses the key while the same form is submitted again", () => {
    const keys = new IntentKeys();
    const first = keys.keyFor("run:A", { project: "p", model: "m" });
    expect(keys.keyFor("run:A", { project: "p", model: "m" })).toBe(first);
    expect(first).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("issues a new key when the form changes", () => {
    const keys = new IntentKeys();
    const first = keys.keyFor("run:A", { project: "p" });
    expect(keys.keyFor("run:A", { project: "q" })).not.toBe(first);
  });

  it("keeps separate keys per scope (one per variant)", () => {
    const keys = new IntentKeys();
    expect(keys.keyFor("run:A", { project: "p" })).not.toBe(keys.keyFor("run:B", { project: "p" }));
  });

  it("issues a new key after the intent succeeded", () => {
    const keys = new IntentKeys();
    const first = keys.keyFor("project", { name: "x" });
    keys.done("project");
    expect(keys.keyFor("project", { name: "x" })).not.toBe(first);
  });

  it("forgets every scope when done() has no argument", () => {
    const keys = new IntentKeys();
    const a = keys.keyFor("run:A", 1);
    const b = keys.keyFor("run:B", 1);
    keys.done();
    expect(keys.keyFor("run:A", 1)).not.toBe(a);
    expect(keys.keyFor("run:B", 1)).not.toBe(b);
  });
});
