import { clsx } from "clsx";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ProvenanceKind, Severity } from "../api/types";

/* Base components (shadcn/ui-style: plain components we own, styled with our tokens). */

type ButtonVariant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "secondary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      type="button"
      className={clsx(
        "inline-flex h-9 items-center justify-center gap-2 rounded-[var(--radius-control)] px-3.5 text-[13.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        variant === "primary" && "bg-ink text-white hover:bg-ink-soft",
        variant === "secondary" && "border border-line-strong bg-surface hover:bg-paper",
        variant === "ghost" && "text-muted hover:bg-paper hover:text-ink",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx("rounded-[var(--radius-card)] border border-line bg-surface", className)}
      {...props}
    />
  );
}

const PROV_STYLE: Record<ProvenanceKind, string> = {
  agent: "bg-llm-bg text-llm",
  rule: "bg-rule-bg text-rule",
  parser: "bg-parser-bg text-parser",
  user: "bg-user-bg text-user",
};

export const PROV_STRIPE: Record<ProvenanceKind, string> = {
  agent: "var(--color-llm)",
  rule: "var(--color-rule)",
  parser: "var(--color-parser)",
  user: "var(--color-user)",
};

export function ProvChip({ kind }: { kind: ProvenanceKind }) {
  const { t } = useTranslation();
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-[var(--radius-chip)] px-2 py-px text-[11.5px] font-semibold whitespace-nowrap",
        PROV_STYLE[kind],
      )}
    >
      {t(`prov.${kind}`)}
    </span>
  );
}

const SEV_STYLE: Record<Severity, string> = {
  error: "bg-err-bg text-err",
  warning: "bg-warn-bg text-warn",
  review: "bg-review-bg text-review",
  info: "bg-parser-bg text-parser",
};
const SEV_ICON: Record<Severity, string> = { error: "×", warning: "!", review: "?", info: "i" };

export function SeverityChip({ severity }: { severity: Severity | null }) {
  const { t } = useTranslation();
  if (severity == null) {
    return (
      <span className="inline-flex items-center gap-1 rounded-[var(--radius-chip)] bg-ok-bg px-2 py-px text-[11.5px] font-semibold text-ok">
        <span aria-hidden>✓</span>
        {t("bom.ok")}
      </span>
    );
  }
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-[var(--radius-chip)] px-2 py-px text-[11.5px] font-semibold whitespace-nowrap",
        SEV_STYLE[severity],
      )}
    >
      <span aria-hidden>{SEV_ICON[severity]}</span>
      {t(`sev.${severity}`)}
    </span>
  );
}

export function PageHeader({
  title,
  lead,
  actions,
}: {
  title: ReactNode;
  lead?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-[72ch]">
        <h1 className="font-[family-name:var(--font-display)] text-[30px] leading-tight font-bold tracking-[-0.01em]">
          {title}
        </h1>
        {lead && <p className="mt-1 text-muted">{lead}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <Card className="flex flex-col items-start gap-3 p-6 text-muted">
      <p className="max-w-[60ch]">{children}</p>
      {action}
    </Card>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-line/60", className)} aria-hidden />;
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-[family-name:var(--font-mono)] text-[12.5px]">{children}</span>;
}

/** Horizontally scrollable table container that keyboard users can scroll (WCAG 2.1.1). */
export function TableScroll({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={label}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: scroll containers must be keyboard-scrollable
      tabIndex={0}
      className={clsx(
        "overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface",
        className,
      )}
    >
      {children}
    </section>
  );
}
