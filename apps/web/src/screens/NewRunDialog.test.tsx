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
  useProjects: () => ({ data: { items: [{ id: "p1", name: "ECG" }] } }),
  useModels: () => ({ data: [{ id: "m1", license_class: "closed" }] }),
}));
const navigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => navigate,
  Link: ({ children }: { children: ReactNode }) => <a href="/">{children}</a>,
}));

const { NewRunDialog } = await import("./NewRunDialog");

const ok = (id: string) => ({ data: { id }, response: new Response(null, { status: 201 }) });
const fail = () => ({
  error: {
    type: "https://bomagent.eu/problems/budget-exceeded",
    title: "Budget",
    status: 402,
  },
  response: new Response(null, { status: 402 }),
});
const keyOf = (call: unknown[]) =>
  (call[1] as { headers: Record<string, string> }).headers["Idempotency-Key"];
const variantOf = (call: unknown[]) => (call[1] as { body: { variant: string } }).body.variant;

function renderDialog(onClose = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NewRunDialog preset={{ projectId: "p1" }} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  post.mockReset();
  navigate.mockReset();
});
afterEach(cleanup);

describe("NewRunDialog idempotency (I-2)", () => {
  it("does not create variant A twice when B failed and the user retries", async () => {
    post.mockResolvedValueOnce(ok("run-a")).mockResolvedValueOnce(fail());
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("radio", { name: /both|oba/i }));
    const submit = screen.getByRole("button", { name: /^(start run|uruchom)/i });
    fireEvent.click(submit);
    await screen.findByRole("alert");
    expect(post).toHaveBeenCalledTimes(2);
    const keyB = keyOf(post.mock.calls[1] as unknown[]);

    post.mockResolvedValueOnce(ok("run-b"));
    fireEvent.click(submit);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(post).toHaveBeenCalledTimes(3);
    const retry = post.mock.calls[2] as unknown[];
    expect(variantOf(retry)).toBe("B");
    expect(keyOf(retry)).toBe(keyB);
  });

  it("reuses the key when the same form is resubmitted after an error", async () => {
    post.mockResolvedValueOnce(fail()).mockResolvedValueOnce(fail());
    renderDialog();
    const submit = screen.getByRole("button", { name: /^(start run|uruchom)/i });
    fireEvent.click(submit);
    await screen.findByRole("alert");
    await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(submit);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(keyOf(post.mock.calls[1] as unknown[])).toBe(keyOf(post.mock.calls[0] as unknown[]));
  });

  it("uses a new key once the form changes", async () => {
    post.mockResolvedValueOnce(fail()).mockResolvedValueOnce(fail());
    renderDialog();
    const submit = screen.getByRole("button", { name: /^(start run|uruchom)/i });
    fireEvent.click(submit);
    await screen.findByRole("alert");
    await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText(/device|urządzeni/i), { target: { value: "EEG" } });
    fireEvent.click(submit);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(keyOf(post.mock.calls[1] as unknown[])).not.toBe(keyOf(post.mock.calls[0] as unknown[]));
  });

  it("disables submit while the request is pending (no double submit)", async () => {
    let resolve: (v: unknown) => void = () => undefined;
    post.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    renderDialog();
    const submit = screen.getByRole("button", { name: /^(start run|uruchom)/i });
    fireEvent.click(submit);
    await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(submit);
    expect(post).toHaveBeenCalledTimes(1);
    resolve(ok("run-a"));
    await waitFor(() => expect(navigate).toHaveBeenCalled());
  });
});
