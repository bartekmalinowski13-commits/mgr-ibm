import { createContext, useContext, useEffect } from "react";

export interface NewRunPreset {
  projectId?: string;
  template?: "ecg" | "pulseox" | "eeg" | "infusion";
}

export interface ShellApi {
  setTitle: (title: string) => void;
  openNewRun: (preset?: NewRunPreset) => void;
  /** document screens (BOM, comparison) sit on the grey desk, edge to edge */
  setDesk: (desk: boolean) => void;
}

export const ShellCtx = createContext<ShellApi>({
  setTitle: () => undefined,
  openNewRun: () => undefined,
  setDesk: () => undefined,
});

/** Page title in the top bar and the browser tab. */
export function usePageTitle(title: string): void {
  const { setTitle } = useContext(ShellCtx);
  useEffect(() => {
    setTitle(title);
    document.title = `${title} – BOM Agent`;
  }, [title, setTitle]);
}

export const useShell = () => useContext(ShellCtx);

/** Puts the page on the grey desk (document screens only) for as long as it is mounted. */
export function useDeskLayout(): void {
  const { setDesk } = useContext(ShellCtx);
  useEffect(() => {
    setDesk(true);
    return () => setDesk(false);
  }, [setDesk]);
}
