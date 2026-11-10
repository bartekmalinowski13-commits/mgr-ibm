import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import { cn } from "./cn";

export type Status = "ok" | "warn" | "error" | "pending" | "running";

const STYLE: Record<Status, { cls: string; Icon: typeof CheckCircle2 }> = {
  ok: { cls: "text-ok bg-ok/10", Icon: CheckCircle2 },
  warn: { cls: "text-warn bg-warn/10", Icon: AlertTriangle },
  error: { cls: "text-error bg-error/10", Icon: XCircle },
  pending: { cls: "text-muted bg-paper", Icon: CircleDashed },
  running: { cls: "text-llm bg-llm/10", Icon: Loader2 },
};

/** Status is never colour alone: icon + text (UX_GUIDELINES §3). */
export function StatusBadge({ status, label }: { status: Status; label: string }) {
  const { cls, Icon } = STYLE[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-medium",
        cls,
      )}
    >
      <Icon
        size={14}
        aria-hidden
        className={status === "running" ? "motion-safe:animate-spin" : undefined}
      />
      {label}
    </span>
  );
}
