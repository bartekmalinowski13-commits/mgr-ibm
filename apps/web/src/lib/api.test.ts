import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../locales/en.json";
import pl from "../locales/pl.json";
import { ApiError, call, downloadCsv, evaluateRun, problemMessage, uploadFile } from "./api";
import i18n from "./i18n";

const resp = (body: string, status: number, type = "text/html") =>
  new Response(body, { status, headers: { "content-type": type } });

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("pl");
});

describe("error bodies that are not RFC 9457 (I-1)", () => {
  it.each([
    ["an HTML gateway page", "<html>502</html>", 502],
    ["an empty body", "", 503],
  ])("call() turns %s into an ApiError with a localised message", async (_n, body, status) => {
    const err = await call(Promise.resolve({ error: body, response: resp(body, status) })).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    await i18n.changeLanguage("en");
    expect(problemMessage(err)).toBe(en.httpErrors["5xx"]);
    await i18n.changeLanguage("pl");
    expect(problemMessage(err)).toBe(pl.httpErrors["5xx"]);
  });

  it("maps a 413 without a problem body to the too-large message", async () => {
    vi.stubGlobal("fetch", async () => resp("<html>413 Request Entity Too Large</html>", 413));
    const err = await uploadFile("p", new File(["x"], "a.kicad_pcb")).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(413);
    expect(problemMessage(err)).toBe(pl.httpErrors["413"]);
  });

  it("does not leak a JSON SyntaxError from the multipart helpers", async () => {
    vi.stubGlobal("fetch", async () => resp("<html>504</html>", 504));
    const err = await evaluateRun("r", new File(["x"], "ref.csv")).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(problemMessage(err)).toBe(pl.httpErrors["5xx"]);
  });

  it("still reads a problem+json body from the download helpers", async () => {
    vi.stubGlobal("fetch", async () =>
      resp(
        JSON.stringify({
          type: "https://bomagent.eu/problems/no-bom",
          title: "No BOM",
          status: 409,
        }),
        409,
        "application/problem+json",
      ),
    );
    const err = await downloadCsv("r").catch((e: unknown) => e);
    expect((err as ApiError).problem.type).toBe("https://bomagent.eu/problems/no-bom");
  });

  it("uses a generic message for other statuses and plain JSON bodies", () => {
    const err = new ApiError(418, { message: "teapot" });
    expect(problemMessage(err)).toBe(i18n.t("httpErrors.generic", { status: 418 }));
    expect(problemMessage(err)).toContain("418");
  });

  it("never throws for a hand-built ApiError with a malformed problem", () => {
    const err = new ApiError(500, undefined);
    expect(() => problemMessage(err)).not.toThrow();
  });
});
