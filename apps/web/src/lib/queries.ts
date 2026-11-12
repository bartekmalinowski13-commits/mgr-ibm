import { useQuery } from "@tanstack/react-query";
import { api, call } from "./api";
import { useSession } from "./session";

export function useMe() {
  const { session } = useSession();
  return useQuery({
    queryKey: ["me", session?.sub],
    queryFn: () => call(api.GET("/v1/me")),
    enabled: !!session,
  });
}

/** The signed-in user owns the current organisation (may add the sample projects). */
export function useIsOwner(): boolean {
  const { orgId } = useSession();
  const me = useMe();
  return !!me.data?.organizations.find((o) => o.org_id === orgId)?.roles.includes("owner");
}

/** Owners and admins may delete sample projects. */
export function useIsAdmin(): boolean {
  const { orgId } = useSession();
  const me = useMe();
  const roles = me.data?.organizations.find((o) => o.org_id === orgId)?.roles ?? [];
  return roles.includes("owner") || roles.includes("admin");
}

export function useProjects() {
  const { orgId } = useSession();
  return useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => call(api.GET("/v1/projects", { params: { query: { limit: 100 } } })),
    enabled: !!orgId,
  });
}

export function useRuns(projectId?: string) {
  const { orgId } = useSession();
  return useQuery({
    queryKey: ["runs", orgId, projectId ?? "all"],
    queryFn: () =>
      call(
        api.GET("/v1/runs", {
          params: { query: { limit: 100, ...(projectId ? { project_id: projectId } : {}) } },
        }),
      ),
    enabled: !!orgId,
    refetchInterval: (q) =>
      q.state.data?.items.some((r) => r.status === "queued" || r.status === "running")
        ? 2000
        : false,
  });
}

export function useUsage(enabled: boolean) {
  const { orgId } = useSession();
  return useQuery({
    queryKey: ["usage", orgId],
    queryFn: () => call(api.GET("/v1/usage")),
    enabled: !!orgId && enabled,
    retry: false,
  });
}

export function useModels() {
  const { orgId } = useSession();
  return useQuery({
    queryKey: ["models", orgId],
    queryFn: () => call(api.GET("/v1/models")),
    enabled: !!orgId,
    staleTime: 5 * 60_000,
  });
}
