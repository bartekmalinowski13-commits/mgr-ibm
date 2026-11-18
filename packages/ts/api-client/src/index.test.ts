import { describe, expect, it } from "vitest";
import { ApiError, createApiClient, idempotencyKey, toProblem, unwrap } from "./index";

describe("api client", () => {
  it("sends bearer token and organisation header, unwraps data", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "https://api.example.eu",
      getToken: () => "tok",
      getOrgId: () => "11111111-1111-1111-1111-111111111111",
      fetch: async (input) => {
        const req = input as Request;
        seen.push(req);
        return new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      },
    });
    const page = unwrap(await client.GET("/v1/projects", { params: { query: { limit: 10 } } }));
    expect(page.items).toEqual([]);
    expect(seen[0]?.headers.get("authorization")).toBe("Bearer tok");
    expect(seen[0]?.headers.get("x-org-id")).toBe("11111111-1111-1111-1111-111111111111");
    expect(seen[0]?.url).toContain("limit=10");
  });

  it("throws ApiError with problem details", async () => {
    const client = createApiClient({
      baseUrl: "https://api.example.eu",
      getToken: () => "tok",
      fetch: async () =>
        new Response(JSON.stringify({ title: "Forbidden", status: 403, detail: "no" }), {
          status: 403,
          headers: { "content-type": "application/problem+json" },
        }),
    });
    const result = await client.GET("/v1/me");
    expect(() => unwrap(result)).toThrow(ApiError);
    expect(idempotencyKey()).toMatch(/^[0-9a-f-]{36}$/);
  });

  it.each([
    ["an HTML gateway page", "<html>502 Bad Gateway</html>", "text/html", 502],
    ["an empty body", "", "text/plain", 503],
    ["plain JSON without a type", JSON.stringify({ message: "too big" }), "application/json", 413],
  ])("normalises %s into an RFC 9457 problem", async (_name, body, type, status) => {
    const client = createApiClient({
      baseUrl: "https://api.example.eu",
      getToken: () => "tok",
      fetch: async () => new Response(body, { status, headers: { "content-type": type } }),
    });
    const result = await client.GET("/v1/me");
    let caught: unknown;
    try {
      unwrap(result);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const problem = (caught as ApiError).problem;
    expect(problem.type).toBe("about:blank");
    expect(problem.status).toBe(status);
    expect(typeof problem.title).toBe("string");
  });

  it("keeps a real problem body as it is", () => {
    const real = { type: "https://bomagent.eu/problems/x", title: "X", status: 409, detail: "d" };
    expect(toProblem(409, "Conflict", real)).toEqual(real);
    expect(toProblem(500, "", undefined)).toEqual({
      type: "about:blank",
      title: "HTTP 500",
      status: 500,
    });
  });
});
