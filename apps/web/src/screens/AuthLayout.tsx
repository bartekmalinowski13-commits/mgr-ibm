import { ProvenanceRail, Sheet, ZoneFrame } from "@bomagent/ui";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Sign-in and onboarding: the brand screen. A drawing sheet on the desk with the zone frame
 * (numbers 1-6, used only here and in the BOM PDF export), the wordmark and the form.
 */
export function AuthLayout({
  title,
  lead,
  children,
}: {
  title: string;
  lead: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <main className="min-h-screen bg-desk p-3 sm:p-5">
      <Sheet className="mx-auto flex min-h-[calc(100vh-24px)] max-w-[1240px] flex-col sm:min-h-[calc(100vh-40px)]">
        <ZoneFrame />
        <div className="grid flex-1 lg:grid-cols-[1.35fr_1fr]">
          <div className="flex flex-col justify-between gap-10 border-b border-ink p-6 sm:p-10 lg:border-b-0 lg:border-r">
            <p className="font-display text-[64px] font-semibold leading-[0.9] tracking-[-0.02em] sm:text-[112px]">
              BOM Agent
            </p>
            <div className="flex flex-col gap-6">
              <section
                aria-label={t("brand.example")}
                className="flex max-w-[460px] flex-col gap-2"
              >
                <div className="relative border border-rule py-3 pl-8 pr-3">
                  <ProvenanceRail kind="agent" />
                  <span className="font-mono text-[13px]">{t("brand.sampleLlm")}</span>
                </div>
                <div className="relative border border-rule py-3 pl-8 pr-3">
                  <ProvenanceRail kind="rule" />
                  <span className="font-mono text-[13px]">{t("brand.sampleRule")}</span>
                </div>
                <p className="text-sm text-ink-soft">{t("brand.legend")}</p>
              </section>
              <p className="max-w-[44ch] text-[17px] leading-relaxed text-ink-soft">{lead}</p>
            </div>
          </div>
          <div className="p-6 sm:p-10">
            <h1 className="font-display text-[36px] font-semibold leading-[1.05] tracking-[-0.01em]">
              {title}
            </h1>
            <div className="mt-6">{children}</div>
          </div>
        </div>
      </Sheet>
    </main>
  );
}
