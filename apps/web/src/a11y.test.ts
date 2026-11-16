import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "styles.css"), "utf8");

function token(name: string): string {
  const m = new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  if (!m) throw new Error(`token ${name} missing`);
  return m[1] as string;
}
function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => {
    const v = Number.parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * (c[0] as number) + 0.7152 * (c[1] as number) + 0.0722 * (c[2] as number);
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// The app ships a single (light) theme today; if a dark theme is added, extend these checks.
describe("accessibility regression gate (UX-08)", () => {
  it("disables animation and smooth scrolling under prefers-reduced-motion", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*animation-duration: 1ms/);
    expect(css).toMatch(/transition-duration: 1ms/);
    expect(css).toMatch(/scroll-behavior: auto/);
  });

  // WCAG 1.4.11: provenance dots and stripes are graphical objects, 3:1 minimum.
  it.each(["llm", "rule", "user", "parser"])("provenance colour %s has 3:1 contrast", (k) => {
    expect(contrast(token(k), token("surface"))).toBeGreaterThanOrEqual(3);
    expect(contrast(token(k), token("paper"))).toBeGreaterThanOrEqual(3);
  });

  it.each(["ink", "muted", "error", "warn", "ok"])("text colour %s has 4.5:1 on surface", (k) => {
    expect(contrast(token(k), token("surface"))).toBeGreaterThanOrEqual(4.5);
  });

  it("muted text stays readable on the page background", () => {
    expect(contrast(token("muted"), token("paper"))).toBeGreaterThanOrEqual(4.5);
  });

  it("sets the document language synchronously when i18n loads", async () => {
    document.documentElement.lang = "";
    await import("./lib/i18n");
    expect(document.documentElement.lang).toMatch(/^(pl|en)$/);
  });
});
