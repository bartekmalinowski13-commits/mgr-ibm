import { cn } from "./cn";

export type Status = "ok" | "warn" | "error" | "pending" | "running";

function Icon({ status }: { status: Status }) {
  switch (status) {
    case "ok":
      return (
        <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden="true">
          <path d="M1.5 6.5 4.5 9.5 10.5 2.5" fill="none" stroke="currentColor" strokeWidth="1.7" />
        </svg>
      );
    case "warn":
      return (
        <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden="true">
          <path d="M6 1 11.4 11H.6Z" fill="currentColor" />
        </svg>
      );
    case "error":
      return (
        <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2 2 10 10M10 2 2 10" stroke="currentColor" strokeWidth="1.9" />
        </svg>
      );
    case "running":
      return (
        <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden="true">
          <circle cx="6" cy="6" r="5.2" fill="currentColor" />
        </svg>
      );
    default:
      return (
        <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden="true">
          <circle
            cx="6"
            cy="6"
            r="4.6"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeDasharray="2 1.6"
          />
        </svg>
      );
  }
}

const STYLE: Record<Status, string> = {
  ok: "text-ok",
  warn: "text-warn",
  error: "bg-error-bg text-error px-2 rounded-chip",
  pending: "text-muted",
  running: "text-llm",
};

/** Status is never colour alone: a shaped icon + text (UX_GUIDELINES §3). */
export function StatusBadge({
  status,
  label,
  className,
}: {
  status: Status;
  label: string;
  className?: string;
}) {
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex items-center gap-1.5 py-0.5 text-[14px] font-semibold leading-5",
        STYLE[status],
        className,
      )}
    >
      <Icon status={status} />
      {label}
    </span>
  );
}
