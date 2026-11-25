import { Dialog, DialogTrigger, SheetContent } from "@bomagent/ui";
import { Menu as MenuIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Navigation drawer below `lg` (and at high zoom): a modal dialog with focus trap, Escape to
 * close and focus return to the hamburger, which reports `aria-expanded`/`aria-controls`.
 */
export function NavDrawer({
  open,
  onOpenChange,
  label,
  closeLabel,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  closeLabel: string;
  children: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        aria-label={label}
        className="rounded-control p-2 hover:bg-sheet focus-visible:outline-2 focus-visible:outline-ink lg:hidden"
      >
        <MenuIcon size={20} aria-hidden />
      </DialogTrigger>
      <SheetContent title={label} closeLabel={closeLabel} className="lg:hidden">
        {children}
      </SheetContent>
    </Dialog>
  );
}
