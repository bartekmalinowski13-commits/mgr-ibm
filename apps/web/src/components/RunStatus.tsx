import { clsx } from "clsx";
import { useTranslation } from "react-i18next";

const STYLE: Record<string, string> = {
  queued: "bg-parser-bg text-parser",
  running: "bg-llm-bg text-llm",
  completed: "bg-ok-bg text-ok",
  failed: "bg-err-bg text-err",
};

export function RunStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-[var(--radius-chip)] px-2 py-px text-[11.5px] font-semibold",
        STYLE[status] ?? STYLE.queued,
      )}
    >
      {status === "running" && (
        <span className="size-1.5 animate-pulse rounded-full bg-llm" aria-hidden />
      )}
      {t(`run.status.${status}`, { defaultValue: status })}
    </span>
  );
}

export function VariantBadge({ variant }: { variant: string }) {
  const llm = variant.startsWith("A");
  return (
    <span
      className={clsx(
        "inline-grid h-6 min-w-6 place-items-center rounded-md px-1.5 font-[family-name:var(--font-mono)] text-[12px] font-medium",
        llm ? "bg-llm text-white" : "bg-rule text-white",
      )}
    >
      {variant}
    </span>
  );
}
