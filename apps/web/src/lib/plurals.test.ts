import { afterEach, describe, expect, it } from "vitest";
import en from "../locales/en.json";
import pl from "../locales/pl.json";
import i18n from "./i18n";

/** Keys the UI calls with `count` whose text depends on the number (M-4). */
const COUNTED = [
  "projects.components",
  "projects.uploaded",
  "run.findings",
  "history.lines",
  "bom.csvCopied",
  "audit.verifyOk",
] as const;

const lookup = (bundle: object, path: string) =>
  path
    .split(".")
    .reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], bundle);

afterEach(() => i18n.changeLanguage("pl"));

describe("PL and EN plurals (M-4)", () => {
  it.each(COUNTED)("%s has every plural form in both languages", (key) => {
    for (const suffix of ["_one", "_other"]) expect(lookup(en, key + suffix)).toBeTypeOf("string");
    for (const suffix of ["_one", "_few", "_many", "_other"])
      expect(lookup(pl, key + suffix)).toBeTypeOf("string");
  });

  it("reads naturally for 1, 2 and 5", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("projects.uploaded", { count: 1 })).toBe("Uploaded 1 file");
    expect(i18n.t("projects.components", { count: 1 })).toBe("1 component");
    await i18n.changeLanguage("pl");
    expect(i18n.t("projects.uploaded", { count: 1 })).toBe("Wgrano 1 plik");
    expect(i18n.t("projects.uploaded", { count: 2 })).toBe("Wgrano 2 pliki");
    expect(i18n.t("projects.uploaded", { count: 5 })).toBe("Wgrano 5 plików");
    expect(i18n.t("history.lines", { count: 2 })).toBe("2 pozycje");
  });
});
