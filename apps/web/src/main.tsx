import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./i18n";
import { makeRouter } from "./router";
import { AppProvider } from "./state";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false } },
});
// the hosted demo runs inside a sandboxed frame: keep navigation in memory, not in the URL
const router = makeRouter(
  import.meta.env.VITE_HISTORY === "memory"
    ? createMemoryHistory({ initialEntries: ["/"] })
    : undefined,
);

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppProvider>
        <RouterProvider router={router} />
      </AppProvider>
    </QueryClientProvider>
  </StrictMode>,
);
