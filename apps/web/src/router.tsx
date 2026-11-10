import {
  createRootRoute,
  createRoute,
  createRouter,
  Navigate,
  Outlet,
} from "@tanstack/react-router";
import { AuditScreen } from "./screens/AuditScreen";
import { CompareScreen } from "./screens/CompareScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { OnboardingScreen } from "./screens/OnboardingScreen";
import { ProjectScreen } from "./screens/ProjectScreen";
import { ProjectsScreen } from "./screens/ProjectsScreen";
import { RunScreen } from "./screens/RunScreen";
import { RunsScreen } from "./screens/RunsScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { Shell } from "./screens/Shell";
import { StartScreen } from "./screens/StartScreen";

const root = createRootRoute({ component: Outlet });
const login = createRoute({ getParentRoute: () => root, path: "/login", component: LoginScreen });
const onboarding = createRoute({
  getParentRoute: () => root,
  path: "/onboarding",
  component: OnboardingScreen,
});
const app = createRoute({ getParentRoute: () => root, id: "app", component: Shell });
const index = createRoute({
  getParentRoute: () => app,
  path: "/",
  component: () => <Navigate to="/start" />,
});
const start = createRoute({ getParentRoute: () => app, path: "/start", component: StartScreen });
const projects = createRoute({
  getParentRoute: () => app,
  path: "/projects",
  component: ProjectsScreen,
});
export const projectRoute = createRoute({
  getParentRoute: () => app,
  path: "/projects/$projectId",
  component: ProjectScreen,
});
export const compareRoute = createRoute({
  getParentRoute: () => app,
  path: "/projects/$projectId/compare",
  component: CompareScreen,
  validateSearch: (search: Record<string, unknown>): { a?: string; b?: string } => ({
    a: typeof search.a === "string" ? search.a : undefined,
    b: typeof search.b === "string" ? search.b : undefined,
  }),
});
const runs = createRoute({ getParentRoute: () => app, path: "/runs", component: RunsScreen });
export const runRoute = createRoute({
  getParentRoute: () => app,
  path: "/runs/$runId",
  component: RunScreen,
});
const audit = createRoute({ getParentRoute: () => app, path: "/audit", component: AuditScreen });
const settings = createRoute({
  getParentRoute: () => app,
  path: "/settings",
  component: SettingsScreen,
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
