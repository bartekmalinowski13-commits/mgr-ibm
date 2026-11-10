import { createContext, useContext, useEffect } from "react";

export interface NewRunPreset {
  projectId?: string;
  template?: "ecg" | "pulseox" | "eeg" | "infusion";
}

export interface ShellApi {
  setTitle: (title: string) => void;
  openNewRun: (preset?: NewRunPreset) => void;
}

export const ShellCtx = createContext<ShellApi>({
  setTitle: () => undefined,
  openNewRun: () => undefined,
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
