import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "./cn";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}

/** Shared look of buttons and button-like links (ADR-0019: 4 px radius, ink, no shadow). */
export function buttonClass(
  variant: NonNullable<ButtonProps["variant"]> = "primary",
  size: NonNullable<ButtonProps["size"]> = "md",
): string {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-control font-semibold transition-colors",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink",
    "disabled:cursor-not-allowed",
    size === "sm" ? "h-8 px-3 text-[14px]" : "h-10 px-4 text-[15px]",
    VARIANTS[variant],
  );
}

const VARIANTS = {
  primary: "bg-ink text-sheet hover:bg-ink-hover disabled:bg-ink/40",
  secondary:
    "border border-ink bg-sheet text-ink hover:bg-vellum disabled:border-line disabled:text-muted",
  ghost: "text-ink hover:bg-vellum",
  danger: "border border-error bg-sheet text-error hover:bg-error-bg",
} as const;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", className, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(buttonClass(variant, size), className)}
      {...props}
    />
  );
});
