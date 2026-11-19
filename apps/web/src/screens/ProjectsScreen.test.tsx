import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../lib/i18n";

const post = vi.fn();
vi.mock("../lib/api", async (orig) => ({
  ...(await orig<typeof import("../lib/api")>()),
  api: { POST: (...args: unknown[]) => post(...args) },
}));
vi.mock("../lib/queries", () => ({
  useProjects: () => ({ isPending: false, isError: false, data: { items: [] } }),
  useIsOwner: () => false,
}));
const navigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => navigate,
  Link: ({ children }: { children: ReactNode }) => <a href="/">{children}</a>,
}));

const { ProjectsScreen } = await import("./ProjectsScreen");

const keyOf = (call: unknown) =>
  (call as [string, { headers: Record<string, string> }])[1].headers["Idempotency-Key"];

beforeEach(() => {
  post.mockReset();
  navigate.mockReset();
});
afterEach(cleanup);

function setup() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ProjectsScreen />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "ECG" } });
  return screen.getByRole("button", { name: /create|utwórz/i }) as HTMLButtonElement;
}

describe("ProjectsScreen create (I-2)", () => {
  it("ignores a double submit while the project is being created", async () => {
    let resolve: (v: unknown) => void = () => undefined;
    post.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    const submit = setup();
    fireEvent.click(submit);
    await waitFor(() => expect(submit.disabled).toBe(true));
    fireEvent.click(submit);
    fireEvent.submit(submit.form as HTMLFormElement);
    expect(post).toHaveBeenCalledTimes(1);
    resolve({ data: { id: "p1" }, response: new Response(null, { status: 201 }) });
    await waitFor(() => expect(navigate).toHaveBeenCalled());
  });

  it("retries a failed create with the same idempotency key", async () => {
    const failed = {
      error: { type: "about:blank", title: "Bad Gateway", status: 502 },
      response: new Response(null, { status: 502 }),
    };
    post.mockResolvedValueOnce(failed).mockResolvedValueOnce(failed);
    const submit = setup();
    fireEvent.click(submit);
    await screen.findByRole("alert");
    await waitFor(() => expect(submit.disabled).toBe(false));
    fireEvent.click(submit);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(keyOf(post.mock.calls[1])).toBe(keyOf(post.mock.calls[0]));
  });
});
