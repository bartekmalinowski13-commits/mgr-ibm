import { Check, CircleDashed, CircleDot, OctagonAlert, TriangleAlert } from "lucide-react";
import { cn } from "./cn";

export type Status = "ok" | "warn" | "error" | "pending" | "running";

const STYLE: Record<Status, { cls: string; Icon: typeof Check }> = {
  ok: { cls: "text-ink", Icon: Check },
  warn: { cls: "text-status-warn", Icon: TriangleAlert },
  error: { cls: "text-status-error", Icon: OctagonAlert },
  pending: { cls: "text-ink-soft", Icon: CircleDashed },
  running: { cls: "text-ink", Icon: CircleDot },
};

/** Status is never colour alone: icon + text. Compliant = ink with a check mark. */
export function StatusBadge({ status, label }: { status: Status; label: string }) {
  const { cls, Icon } = STYLE[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium", cls)}>
      <Icon size={14} strokeWidth={2.75} aria-hidden />
      {label}
    </span>
  );
}
