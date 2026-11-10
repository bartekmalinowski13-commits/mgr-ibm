import { Button } from "@bomagent/ui";
import { FileCheck2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { evaluateRun, problemMessage, type Schemas } from "../lib/api";

const HEADLINE = [
  "line_f1",
  "line_precision",
  "line_recall",
  "designator_f1",
  "mpn_coverage",
] as const;
const FIELDS = ["value", "footprint", "manufacturer", "mpn"] as const;

/** Thesis metrics against a reference BOM the user provides (nothing is stored). */
export function ReferencePanel({ runId }: { runId: string }) {
  const { t, i18n } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<Schemas["Evaluation"]>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const pct = (v: number | null | undefined) =>
    v == null
      ? "–"
      : new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 }).format(
          v,
        );

  const run = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(undefined);
    try {
      setResult(await evaluateRun(runId, file));
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <section
      aria-labelledby="ref-title"
      className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="ref-title" className="font-display text-xl font-bold">
            {t("reference.title")}
          </h2>
          <p className="max-w-[70ch] text-sm text-muted">{t("reference.lead")}</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          <FileCheck2 size={16} aria-hidden /> {t("reference.upload")}
        </Button>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          aria-label={t("reference.upload")}
          data-testid="reference-input"
          onChange={(e) => void run(e.target.files?.[0])}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      ) : null}
      {result ? (
        <>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            {HEADLINE.map((k) => (
              <div key={k}>
                <dt className="text-sm text-muted">{t(`reference.metrics.${k}`)}</dt>
                <dd className="font-display text-2xl font-bold tabular-nums">
                  {pct(result.summary[k])}
                </dd>
              </div>
            ))}
          </dl>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {FIELDS.filter((f) => result.fields[f]).map((f) => (
              <div key={f} className="flex gap-1.5">
                <dt className="text-muted">{t(`bom.columns.${f}`)}:</dt>
                <dd className="tabular-nums">{pct(result.summary[`acc_${f}`])}</dd>
              </div>
            ))}
          </dl>
          <h3 className="font-medium">{t("reference.diffs", { count: result.diffs.length })}</h3>
          {result.diffs.length ? (
            <div className="max-h-80 overflow-auto rounded-card border border-line">
              <table className="w-full min-w-[560px] text-left text-[14px]">
                <thead className="sticky top-0 border-b border-line bg-surface text-[13px] text-muted">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("bom.columns.refdes")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("reference.field")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("reference.predicted")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("reference.expected")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.diffs.map((d) => (
                    <tr
                      key={`${d.refdes}-${d.field}`}
                      className="border-b border-line last:border-0"
                    >
                      <td className="px-3 py-2 font-mono text-[13px]">{d.refdes}</td>
                      <td className="px-3 py-2">{d.field}</td>
                      <td className="px-3 py-2 font-mono text-[13px]">{d.predicted || "–"}</td>
                      <td className="px-3 py-2 font-mono text-[13px]">{d.expected || "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
