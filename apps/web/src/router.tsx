import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Navigate,
  Outlet,
} from "@tanstack/react-router";
import { LoginScreen } from "./screens/LoginScreen";
import { Shell } from "./screens/Shell";

const root = createRootRoute({ component: Outlet });
const login = createRoute({ getParentRoute: () => root, path: "/login", component: LoginScreen });
const onboarding = createRoute({
  getParentRoute: () => root,
  path: "/onboarding",
  component: lazyRouteComponent(() => import("./screens/OnboardingScreen"), "OnboardingScreen"),
});
const app = createRoute({ getParentRoute: () => root, id: "app", component: Shell });
const index = createRoute({
  getParentRoute: () => app,
  path: "/",
  component: () => <Navigate to="/start" />,
});
const start = createRoute({
  getParentRoute: () => app,
  path: "/start",
  component: lazyRouteComponent(() => import("./screens/StartScreen"), "StartScreen"),
});
const projects = createRoute({
  getParentRoute: () => app,
  path: "/projects",
  component: lazyRouteComponent(() => import("./screens/ProjectsScreen"), "ProjectsScreen"),
});
export const projectRoute = createRoute({
  getParentRoute: () => app,
  path: "/projects/$projectId",
  component: lazyRouteComponent(() => import("./screens/ProjectScreen"), "ProjectScreen"),
});
export const compareRoute = createRoute({
  getParentRoute: () => app,
  path: "/projects/$projectId/compare",
  component: lazyRouteComponent(() => import("./screens/CompareScreen"), "CompareScreen"),
  validateSearch: (search: Record<string, unknown>): { a?: string; b?: string } => ({
    a: typeof search.a === "string" ? search.a : undefined,
    b: typeof search.b === "string" ? search.b : undefined,
  }),
});
const runs = createRoute({
  getParentRoute: () => app,
  path: "/runs",
  component: lazyRouteComponent(() => import("./screens/RunsScreen"), "RunsScreen"),
});
export const runRoute = createRoute({
  getParentRoute: () => app,
  path: "/runs/$runId",
  component: lazyRouteComponent(() => import("./screens/RunScreen"), "RunScreen"),
});
const audit = createRoute({
  getParentRoute: () => app,
  path: "/audit",
  component: lazyRouteComponent(() => import("./screens/AuditScreen"), "AuditScreen"),
});
const settings = createRoute({
  getParentRoute: () => app,
  path: "/settings",
  component: lazyRouteComponent(() => import("./screens/SettingsScreen"), "SettingsScreen"),
});

export const router = createRouter({
  routeTree: root.addChildren([
    login,
    onboarding,
    app.addChildren([
      index,
      start,
      projects,
      projectRoute,
      compareRoute,
      runs,
      runRoute,
      audit,
      settings,
    ]),
  ]),
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
