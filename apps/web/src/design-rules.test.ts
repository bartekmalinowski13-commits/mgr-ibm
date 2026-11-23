import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Guard rails of the "technical drawing sheet" identity (docs/design/UX_GUIDELINES.md §3):
 * square corners, no shadows, no gradients except the hatched LLM rail, one animation
 * (the path draw), violet and green only where they mean provenance or variant.
 */
const ROOTS = [resolve(__dirname), resolve(__dirname, "../../../packages/ts/ui/src")];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|css)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}
/** Comments are documentation, and the theme resets (`--shadow-*: initial`) are the guard itself. */
function code(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/--(drop-)?shadow-\*: initial;/g, "");
}
const files = ROOTS.flatMap(sources).map((path) => ({
  path,
  text: code(readFileSync(path, "utf8")),
}));
const tsx = files.filter((f) => f.path.endsWith(".tsx"));

function offenders(pattern: RegExp, scope = files): string[] {
  return scope
    .filter((f) => pattern.test(f.text))
    .map((f) => f.path.replace(`${resolve(__dirname, "../../..")}/`, ""));
}

describe("visual identity guard rails", () => {
  it("has no rounded corners", () => {
    expect(offenders(/\brounded(-(?!none)[a-z0-9[\]-]+)?\b|border-radius:\s*(?!0)/, tsx)).toEqual(
      [],
    );
  });
  it("has no shadows", () => {
    expect(offenders(/\bshadow(-[a-z0-9[\]_-]+)?\b|box-shadow/, files)).toEqual([]);
  });
  it("has no gradients except the hatched LLM rail", () => {
    const gradient = files.filter((f) => /gradient/.test(f.text));
    expect(gradient.map((f) => f.path.split("/").pop())).toEqual(["styles.css"]);
    const css = gradient[0]?.text ?? "";
    expect((css.match(/gradient/g) ?? []).length).toBe(1);
    expect(css).toMatch(/\.rail-agent\s*{[^}]*repeating-linear-gradient\(\s*135deg/);
  });
  it("animates only the path draw", () => {
    expect(offenders(/\banimate-|motion-safe:animate|\btransition(-[a-z]+)?\b/, tsx)).toEqual([]);
    const css = files.find((f) => f.path.endsWith("styles.css"))?.text ?? "";
    expect(css.match(/@keyframes (\w+)/g)).toEqual(["@keyframes draw"]);
    expect(css).toMatch(/animation: draw 240ms/);
  });
  it("does not use the previous identity (Bricolage, Fraunces, warm tones)", () => {
    expect(offenders(/bricolage|fraunces/i)).toEqual([]);
  });
  it("uses violet and green only for provenance and variant", () => {
    // allowed: the provenance primitives in the ui package, the variant helpers, the rails
    const allowed = [
      "packages/ts/ui/src/provenance.tsx",
      "packages/ts/ui/src/run-path.tsx",
      "apps/web/src/styles.css",
      "apps/web/src/lib/provenance.ts",
      "apps/web/src/screens/BomTable.tsx",
      "apps/web/src/screens/ItemPanel.tsx",
      "apps/web/src/screens/RunPathView.tsx",
      "apps/web/src/screens/CompareScreen.tsx",
      "apps/web/src/screens/RunScreen.tsx",
    ];
    const used = offenders(/(bg|text|border|outline|fill|stroke)-prov-(llm|rule)/);
    expect(used.filter((p) => !allowed.includes(p))).toEqual([]);
  });
});
