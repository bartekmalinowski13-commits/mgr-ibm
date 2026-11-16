import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { ApiError } from "@bomagent/api-client";
import { afterEach, describe, expect, it } from "vitest";
import en from "../locales/en.json";
import pl from "../locales/pl.json";
import { problemMessage } from "./api";
import i18n from "./i18n";

const API_SRC = resolve(__dirname, "../../../../services/api/src");

function pythonFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return pythonFiles(path);
    return path.endsWith(".py") ? [path] : [];
  });
}

/** Every `slug="..."` the API can put in a problem `type` URL (openapi.json does not list them). */
function apiSlugs(): string[] {
  const found = new Set<string>();
  for (const file of pythonFiles(API_SRC)) {
    for (const m of readFileSync(file, "utf8").matchAll(/slug="([a-z0-9-]+)"/g)) {
      found.add(m[1] as string);
    }
  }
  return [...found].sort();
}

const problem = (slug: string, detail = "english detail") =>
  new ApiError(409, {
    type: slug ? `https://bomagent.eu/problems/${slug}` : "about:blank",
    title: "Conflict",
    status: 409,
    detail,
  });

afterEach(() => i18n.changeLanguage("pl"));

describe("localised problem messages (UX-05)", () => {
  it("finds the API slugs (guards the enumeration itself)", () => {
    expect(apiSlugs().length).toBeGreaterThan(20);
  });

  it.each([
    ["en", en],
    ["pl", pl],
  ] as const)("covers every API slug in %s", (_lng, bundle) => {
    const errors = (bundle as { errors?: Record<string, string> }).errors ?? {};
    expect(apiSlugs().filter((s) => !errors[s])).toEqual([]);
  });

  it("has the same error keys in PL and EN", () => {
    const keys = (b: object) => Object.keys((b as { errors: object }).errors).sort();
    expect(keys(pl)).toEqual(keys(en));
  });

  it("returns the message in the UI language", async () => {
    await i18n.changeLanguage("en");
    expect(problemMessage(problem("file-in-use"))).toBe(en.errors["file-in-use"]);
    await i18n.changeLanguage("pl");
    expect(problemMessage(problem("file-in-use"))).toBe(pl.errors["file-in-use"]);
    expect(pl.errors["file-in-use"]).not.toBe(en.errors["file-in-use"]);
  });

  it("falls back to the server detail for an unknown slug", () => {
    expect(problemMessage(problem("brand-new-slug", "server says no"))).toBe("server says no");
    expect(problemMessage(problem("", "plain detail"))).toBe("plain detail");
  });

  it("keeps handling plain errors", () => {
    expect(problemMessage(new Error("boom"))).toBe("boom");
  });
});
