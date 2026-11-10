import { createContext, type ReactNode, useContext, useMemo, useRef, useState } from "react";
import { type Api, HttpApi } from "./api/client";
import { MockApi } from "./api/mock";

interface AppState {
  api: Api;
  orgId: string;
  setOrgId: (id: string) => void;
  userName: string;
  newRunOpen: boolean;
  openNewRun: (designId?: string) => void;
  closeNewRun: () => void;
  newRunDesign?: string;
  toast: string | null;
  notify: (message: string) => void;
}

const Ctx = createContext<AppState | null>(null);

/** `api` may be a factory so a mock can follow the active organisation (tests, demo). */
type ApiSource = Api | ((activeOrg: () => string) => Api);

export function AppProvider({ children, api }: { children: ReactNode; api?: ApiSource }) {
  const [orgId, setOrgId] = useState("org-medtech");
  const [newRunOpen, setNewRunOpen] = useState(false);
  const [newRunDesign, setNewRunDesign] = useState<string | undefined>();
  const [toast, setToast] = useState<string | null>(null);
  // a ref, so the long-lived mock API reads the organisation that is active now
  const orgRef = useRef(orgId);
  orgRef.current = orgId;
  const resolved = useMemo<Api>(
    () => {
      const activeOrg = () => orgRef.current;
      if (typeof api === "function") return api(activeOrg);
      return (
        api ?? (import.meta.env.VITE_API_MODE === "mock" ? new MockApi(activeOrg) : new HttpApi())
      );
    },
    // the api object is stable; the mock reads the active organisation through the ref
    [api],
  );
  const value: AppState = {
    api: resolved,
    orgId,
    setOrgId,
    userName: "Bartek",
    newRunOpen,
    newRunDesign,
    openNewRun: (designId) => {
      setNewRunDesign(designId);
      setNewRunOpen(true);
    },
    closeNewRun: () => setNewRunOpen(false),
    toast,
    notify: (message) => {
      setToast(message);
      window.setTimeout(() => setToast(null), 2600);
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp outside AppProvider");
  return ctx;
}
