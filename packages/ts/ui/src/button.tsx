import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "./cn";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}

const VARIANTS = {
  primary: "bg-ink text-surface hover:bg-ink-hover disabled:bg-ink/40",
  secondary: "bg-surface text-ink border border-line hover:border-ink/40",
  ghost: "text-ink hover:bg-paper",
  danger: "bg-surface text-error border border-error/40 hover:bg-error/5",
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
        "inline-flex items-center justify-center gap-2 rounded-control font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-[15px]",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
});
