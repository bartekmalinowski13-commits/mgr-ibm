import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "./cn";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}

/** Square, 1px ink outline. Primary = filled ink; everything else is outlined or plain. */
const VARIANTS = {
  primary:
    "border border-ink bg-ink text-sheet hover:bg-ink-hover disabled:border-ink/40 disabled:bg-ink/40",
  secondary:
    "border border-ink bg-sheet text-ink hover:bg-tint disabled:border-ink/40 disabled:text-ink/50",
  ghost: "border border-transparent text-ink hover:border-ink hover:bg-tint",
  danger: "border border-status-error bg-sheet text-status-error hover:bg-tint disabled:opacity-50",
} as const;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", className, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 font-medium",
        "disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-[15px]",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
});
