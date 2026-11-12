import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  title,
  description,
  children,
  className,
  closeLabel,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  closeLabel: string;
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 bg-ink/30 motion-safe:animate-[fade_120ms_ease-out]" />
      <D.Content
        className={cn(
          "fixed left-1/2 top-[8vh] w-[min(720px,calc(100vw-32px))] -translate-x-1/2",
          "max-h-[84vh] overflow-y-auto rounded-panel bg-surface p-6 shadow-dialog",
          "focus-visible:outline-none",
          className,
        )}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <D.Title className="font-display text-2xl font-extrabold leading-tight text-ink">
              {title}
            </D.Title>
            {description ? (
              <D.Description className="mt-1 text-[15px] text-muted">{description}</D.Description>
            ) : null}
          </div>
          <D.Close
            aria-label={closeLabel}
            className="rounded-control p-1.5 text-muted hover:bg-paper hover:text-ink focus-visible:outline-2 focus-visible:outline-focus"
          >
            <X size={18} aria-hidden />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  );
}

export function DialogFooter({ children }: { children: ReactNode }) {
  return <div className="mt-6 flex justify-end gap-3 border-t border-line pt-4">{children}</div>;
}
