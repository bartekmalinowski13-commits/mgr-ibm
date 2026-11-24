import { Button, buttonClass, cn, TitleBlock, VariantChip } from "@bomagent/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  call,
  downloadCsv,
  downloadXlsx,
  problemMessage,
  type Schemas,
  saveBlob,
} from "../lib/api";
import { formatNumber } from "../lib/format";
import { SheetSlot, usePageTitle } from "../lib/layout";
import type { BomItem } from "../lib/provenance";
import { useProjects } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { bomRoute } from "../router";
import { BomTable } from "./BomTable";
import { LoadError, Skeleton } from "./common";
import { ItemPanel } from "./ItemPanel";
import { ReferencePanel } from "./ReferencePanel";
import { VersionHistory } from "./VersionHistory";

/** Sheet 3 of the flow (ADR-0019): the BOM of a finished run with the item panel. */
export function BomScreen() {
  const { runId } = bomRoute.useParams();
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const toast = useToast();
  const run = useQuery({
    queryKey: ["run", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })),
  });
  const bom = useQuery({
    queryKey: ["bom", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}/bom", { params: { path: { run_id: runId } } })),
  });
  const projects = useProjects();
  const project = projects.data?.items.find((p) => p.id === run.data?.project_id);
  const [selected, setSelected] = useState<number>();
  const [evaluation, setEvaluation] = useState<Schemas["Evaluation"]>();
  const lang = i18n.language;
  const version = bom.data?.version;
  usePageTitle(version ? t("bomScreen.title", { version }) : t("bom.title"));

  const exportBom = async (format: "csv" | "xlsx") => {
    try {
      const blob = await (format === "csv" ? downloadCsv(runId) : downloadXlsx(runId));
      saveBlob(blob, `bom-${runId.slice(0, 8)}.${format}`);
      toast(t(format === "csv" ? "run.exported" : "run.exportedXlsx"));
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

  const crumbs = (
    <SheetSlot name="crumbs">
      <Link to="/runs" className="hover:text-ink hover:underline">
        {t("nav.runs")}
      </Link>
      <span aria-hidden>/</span>
      {run.data ? (
        <>
          <Link to="/runs/$runId" params={{ runId }} className="hover:text-ink hover:underline">
            {project?.name ?? t("run.title")}
          </Link>
          <span aria-hidden>/</span>
        </>
      ) : null}
    </SheetSlot>
  );

  if (run.isPending || bom.isPending)
    return (
      <>
        {crumbs}
        <Skeleton rows={6} />
      </>
    );
  if (run.isError) return <LoadError error={run.error} onRetry={() => void run.refetch()} />;
  if (bom.isError) return <LoadError error={bom.error} onRetry={() => void bom.refetch()} />;

  const items: BomItem[] = bom.data.bom.items;
  const findings = bom.data.bom.findings ?? [];
  const item = items.find((i) => i.line === selected);
  const parts = items.reduce((n, i) => n + i.quantity, 0);
  const variant = run.data.variant;
  const fmt2 = new Intl.NumberFormat(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <>
      {crumbs}
      <SheetSlot name="chips">
        <VariantChip
          variant={variant}
          label={t(`variants.${variant}`, { defaultValue: variant })}
        />
      </SheetSlot>
      <SheetSlot name="actions">
        <a href="#reference" className={buttonClass("secondary")}>
          {t("bomScreen.compareReference")}
        </a>
        <Button variant="ghost" onClick={() => void exportBom("xlsx")}>
          {t("run.exportXlsx")}
        </Button>
        <Button onClick={() => void exportBom("csv")}>{t("run.export")}</Button>
      </SheetSlot>
      <SheetSlot name="titleBlock">
        <TitleBlock
          label={t("sheet.titleBlock")}
          name={t("bomScreen.blockName", { version: bom.data.version })}
          sheetLabel={t("sheet.number", { n: 3, m: 4 })}
          cells={[
            { label: t("titleBlock.project"), value: project?.name ?? bom.data.bom.design_name },
            {
              label: t("titleBlock.variant"),
              value: t(`variants.${variant}`, { defaultValue: variant }),
            },
            {
              label: t("titleBlock.lines"),
              value: t("bomScreen.linesValue", {
                lines: formatNumber(items.length, lang),
                parts: formatNumber(parts, lang),
              }),
            },
            {
              label: t("titleBlock.findings"),
              value: t("bomScreen.findingsValue", { count: findings.length }),
            },
            {
              label: t("titleBlock.reference"),
              value:
                evaluation?.summary.line_f1 != null
                  ? `F1 ${fmt2.format(evaluation.summary.line_f1)}`
                  : "—",
            },
            { label: t("titleBlock.export"), value: "CSV, XLSX" },
          ]}
        />
      </SheetSlot>

      <p className="sr-only" aria-live="polite">
        {t("run.findings", { count: findings.length })}
      </p>
      <div
        className={cn(
          "-mx-4 -my-6 grid grid-cols-[minmax(0,1fr)] sm:-mx-10 sm:-my-8",
          item ? "xl:grid-cols-[minmax(0,1fr)_360px]" : "xl:grid-cols-[minmax(0,1fr)_300px]",
        )}
      >
        <div className="min-w-0 px-4 py-6 sm:px-10 sm:py-8 xl:pr-0">
          <BomTable bom={bom.data.bom} selected={selected} onSelect={setSelected} />
          <div className="mt-10">
            <VersionHistory runId={runId} current={bom.data.version} />
          </div>
          <div className="mt-10">
            <ReferencePanel runId={runId} onResult={setEvaluation} />
          </div>
        </div>
        <div className="xl:mt-0 xl:border-l xl:border-line-soft">
          {item ? (
            <ItemPanel
              runId={runId}
              item={item}
              items={items}
              findings={findings}
              onClose={() => setSelected(undefined)}
            />
          ) : (
            <p className="hidden px-6 py-8 text-[15px] text-muted xl:block">
              {t("bomScreen.pick")}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
