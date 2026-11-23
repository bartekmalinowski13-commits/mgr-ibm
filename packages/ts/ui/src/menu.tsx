import * as M from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

export const Menu = M.Root;
export const MenuTrigger = M.Trigger;

export function MenuContent({ children }: { children: ReactNode }) {
  return (
    <M.Portal>
      <M.Content
        align="start"
        sideOffset={4}
        className="z-50 min-w-[232px] border border-ink bg-sheet p-1 text-ink"
      >
        {children}
      </M.Content>
    </M.Portal>
  );
}

export function MenuItem({ children, onSelect }: { children: ReactNode; onSelect: () => void }) {
  return (
    <M.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2 px-2.5 py-2 text-[15px] text-ink outline-none data-[highlighted]:bg-ink data-[highlighted]:text-sheet"
    >
      {children}
    </M.Item>
  );
}
