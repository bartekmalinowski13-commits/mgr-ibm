import { createContext, type ReactNode, useContext, useEffect } from "react";
import { createPortal } from "react-dom";

export interface NewRunPreset {
  projectId?: string;
  template?: "ecg" | "pulseox" | "eeg" | "infusion";
}

/**
 * Places of the drawing sheet (ADR-0019) that a screen fills from inside the page:
 * `crumbs` before the title, `chips` after it, `actions` on the right of the header row,
 * `titleBlock` in the bottom-right corner of the sheet.
 */
export type SheetSlotName = "crumbs" | "chips" | "actions" | "titleBlock";

export interface PageOptions {
  /** false: no header row (the screen renders its own heading, e.g. the Start greeting) */
  header?: boolean;
}

export interface ShellApi {
  setTitle: (title: string) => void;
  setPage: (options: PageOptions) => void;
  openNewRun: (preset?: NewRunPreset) => void;
  slots: Partial<Record<SheetSlotName, HTMLElement | null>>;
}

export const ShellCtx = createContext<ShellApi>({
  setTitle: () => undefined,
  setPage: () => undefined,
  openNewRun: () => undefined,
  slots: {},
});

/** Page title in the sheet header and the browser tab. */
export function usePageTitle(title: string, options: PageOptions = {}): void {
  const { setTitle, setPage } = useContext(ShellCtx);
  const header = options.header ?? true;
  useEffect(() => {
    setTitle(title);
    document.title = `${title} – BOM Agent`;
  }, [title, setTitle]);
  useEffect(() => {
    setPage({ header });
    return () => setPage({ header: true });
  }, [header, setPage]);
}

/** Renders `children` into a place of the sheet owned by the shell. */
export function SheetSlot({ name, children }: { name: SheetSlotName; children: ReactNode }) {
  const target = useContext(ShellCtx).slots[name];
  return target ? createPortal(children, target) : null;
}

export const useShell = () => useContext(ShellCtx);
