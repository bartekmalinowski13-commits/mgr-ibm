import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/ui";
import { ComparePage } from "./pages/Compare";
import { AuditPage, NotificationsPage, SettingsPage } from "./pages/Misc";
import { ProjectDetailPage, ProjectsPage } from "./pages/Projects";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/Runs";
import { StartPage } from "./pages/Start";

/* Code-based routes: a handful of screens, no file-based codegen needed. */
const rootRoute = createRootRoute({ component: Outlet });
const shell = createRoute({ getParentRoute: () => rootRoute, id: "shell", component: AppShell });

const routes = [
  createRoute({ getParentRoute: () => shell, path: "/", component: StartPage }),
  createRoute({
    getParentRoute: () => shell,
    path: "/notifications",
    component: NotificationsPage,
  }),
  createRoute({ getParentRoute: () => shell, path: "/projects", component: ProjectsPage }),
  createRoute({
    getParentRoute: () => shell,
    path: "/projects/$projectId",
    component: ProjectDetailPage,
  }),
  createRoute({ getParentRoute: () => shell, path: "/runs", component: RunsPage }),
  createRoute({ getParentRoute: () => shell, path: "/runs/$runId", component: RunPage }),
  createRoute({
    getParentRoute: () => shell,
    path: "/compare",
    component: ComparePage,
    validateSearch: (s: Record<string, unknown>): { a?: string; b?: string } => ({
      a: typeof s.a === "string" ? s.a : undefined,
      b: typeof s.b === "string" ? s.b : undefined,
    }),
  }),
  createRoute({ getParentRoute: () => shell, path: "/audit", component: AuditPage }),
  createRoute({ getParentRoute: () => shell, path: "/settings", component: SettingsPage }),
] as const;

const routeTree = rootRoute.addChildren([shell.addChildren(routes)]);

export function makeRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    defaultNotFoundComponent: () => <EmptyState>404</EmptyState>,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
