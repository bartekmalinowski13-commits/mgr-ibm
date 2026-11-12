import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Navigate,
  Outlet,
  redirect,
} from "@tanstack/react-router";
import { captureFragmentReturn } from "./lib/authReturn";
import { LoginScreen } from "./screens/LoginScreen";
import { Shell } from "./screens/Shell";

const root = createRootRoute({
  component: Outlet,
  // e-mail links (recovery, confirmation) and provider errors land on the Site URL with
  // the result in the URL fragment: move it out of the address bar and show its screen
  beforeLoad: () => {
    const target = captureFragmentReturn();
    if (target) throw redirect({ to: target, replace: true });
  },
});
const login = createRoute({ getParentRoute: () => root, path: "/login", component: LoginScreen });
const callback = createRoute({
  getParentRoute: () => root,
  path: "/auth/callback",
  component: lazyRouteComponent(() => import("./screens/AuthCallbackScreen"), "AuthCallbackScreen"),
});
const reset = createRoute({
  getParentRoute: () => root,
  path: "/auth/reset",
  component: lazyRouteComponent(() => import("./screens/AuthReturnScreens"), "ResetPasswordScreen"),
});
const confirmed = createRoute({
  getParentRoute: () => root,
  path: "/auth/confirmed",
  component: lazyRouteComponent(
    () => import("./screens/AuthReturnScreens"),
    "EmailConfirmedScreen",
  ),
});
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
const kb = createRoute({
  getParentRoute: () => app,
  path: "/kb",
  component: lazyRouteComponent(() => import("./screens/KbScreen"), "KbScreen"),
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
    callback,
    reset,
    confirmed,
    onboarding,
    app.addChildren([
      index,
      start,
      projects,
      projectRoute,
      compareRoute,
      runs,
      runRoute,
      kb,
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
