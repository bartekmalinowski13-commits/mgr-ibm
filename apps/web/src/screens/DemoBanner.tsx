import { FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useRuntime } from "../lib/queries";

/** Persistent notice on demo deployments: the model is deterministic, BOMs are illustrative. */
export function DemoBanner() {
  const { t } = useTranslation();
  const runtime = useRuntime();
  if (runtime.data?.mode !== "demo") return null;
  return (
    <div
      role="status"
      data-testid="demo-banner"
      className="flex items-start gap-2 border-b border-warn/40 bg-warn/10 px-4 py-2 text-sm text-ink sm:px-8"
    >
      <FlaskConical size={16} aria-hidden className="mt-0.5 shrink-0" />
      <p>
        <strong>{t("demo.title")}</strong> {t("demo.body")}
      </p>
    </div>
  );
}
