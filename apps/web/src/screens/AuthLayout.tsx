import type { ReactNode } from "react";

/** Sign-in and onboarding: the product's one large typographic moment, then the form. */
export function AuthLayout({
  title,
  lead,
  children,
}: {
  title: string;
  lead: string;
  children: ReactNode;
}) {
  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-[560px]">
        <p className="mb-8 flex items-center gap-2 font-display text-lg font-extrabold">
          <span aria-hidden className="inline-block h-5 w-1.5 rounded-full bg-llm" />
          <span aria-hidden className="-ml-1 inline-block h-5 w-1.5 rounded-full bg-rule" />
          BOM Agent
        </p>
        <h1 className="font-display text-[44px] font-extrabold leading-[1.05] tracking-tight sm:text-[56px]">
          {title}
        </h1>
        <p className="mt-4 max-w-[60ch] text-[17px] leading-relaxed text-muted">{lead}</p>
        <div className="mt-8">{children}</div>
      </div>
    </main>
  );
}
