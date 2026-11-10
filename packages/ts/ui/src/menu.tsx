import * as M from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

export const Menu = M.Root;
export const MenuTrigger = M.Trigger;

export function MenuContent({ children }: { children: ReactNode }) {
  return (
    <M.Portal>
      <M.Content
        align="start"
        sideOffset={6}
        className="z-50 min-w-[232px] rounded-card border border-line bg-surface p-1.5 shadow-dialog"
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
      className="flex cursor-pointer items-center gap-2 rounded-control px-2.5 py-2 text-[15px] text-ink outline-none data-[highlighted]:bg-paper"
    >
      {children}
    </M.Item>
  );
}
