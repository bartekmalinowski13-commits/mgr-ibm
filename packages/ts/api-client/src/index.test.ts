import { describe, expect, it } from "vitest";
import { ApiError, createApiClient, idempotencyKey, unwrap } from "./index";

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
});
