import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  useId,
} from "react";
import { cn } from "./cn";

const CONTROL =
  "w-full rounded-control border border-line bg-surface px-3 text-[15px] text-ink " +
  "placeholder:text-muted/70 focus-visible:border-ink focus-visible:outline-2 " +
  "focus-visible:outline-offset-0 focus-visible:outline-focus aria-[invalid=true]:border-error";

/** Label on the left, control on the right (modal pattern from UX_GUIDELINES §2). */
export function Field({
  label,
  required,
  hint,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}) {
  const id = useId();
  const hintId = hint || error ? `${id}-hint` : undefined;
  return (
    <div className="grid gap-2 py-2 sm:grid-cols-[180px_1fr] sm:items-start sm:gap-6">
      <label htmlFor={id} className="pt-2 text-[15px] font-medium text-ink">
        {label}
        {required ? (
          <span className="text-error" aria-hidden>
            {" "}
            *
          </span>
        ) : null}
      </label>
      <div>
        {children(id, hintId)}
        {error ? (
          <p id={hintId} className="mt-1.5 text-sm text-error">
            {error}
          </p>
        ) : hint ? (
          <p id={hintId} className="mt-1.5 text-sm text-muted">
            {hint}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(CONTROL, "h-10", className)} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...props }, ref) {
    return <select ref={ref} className={cn(CONTROL, "h-10", className)} {...props} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(CONTROL, "min-h-24 py-2", className)} {...props} />;
});
