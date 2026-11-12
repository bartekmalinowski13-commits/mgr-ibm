import { idempotencyKey } from "@bomagent/api-client";
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogFooter,
  Field,
  Input,
  Select,
} from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage } from "../lib/api";
import type { NewRunPreset } from "../lib/layout";
import { useModels, useProjects } from "../lib/queries";
import { useToast } from "../lib/toast";
import { TEMPLATES } from "./templates";

type Choice = "A" | "B" | "both";

/** Pipeline sketch in provenance colours: violet = LLM step, green = rule step. */
function PipelineSketch({ steps }: { steps: ("llm" | "rule")[] }) {
  return (
    <svg viewBox={`0 0 ${steps.length * 28} 16`} aria-hidden className="h-4">
      <line
        x1="8"
        y1="8"
        x2={steps.length * 28 - 20}
        y2="8"
        className="stroke-line"
        strokeWidth="2"
      />
      {steps.map((s, i) => (
        <circle
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed decorative sequence
          key={i}
          cx={8 + i * 28}
          cy="8"
          r="6"
          className={s === "llm" ? "fill-llm" : "fill-rule"}
        />
      ))}
    </svg>
  );
}

const VARIANTS: { id: Choice; steps: ("llm" | "rule")[] }[] = [
  { id: "A", steps: ["llm", "llm", "llm", "llm"] },
  { id: "B", steps: ["rule", "rule", "llm", "rule"] },
  { id: "both", steps: ["llm", "rule", "llm", "rule"] },
];

export function NewRunDialog({ preset, onClose }: { preset: NewRunPreset; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const projects = useProjects();
  const models = useModels();
  const template = preset.template ? TEMPLATES[preset.template] : undefined;
  const [projectId, setProjectId] = useState(preset.projectId ?? "");
  const [variant, setVariant] = useState<Choice>("B");
  const [modelId, setModelId] = useState("");
  const [device, setDevice] = useState(
    preset.template ? t(`start.templates.${preset.template}.title`) : "",
  );
  const [appliedPart, setAppliedPart] = useState<string>(template?.appliedPart ?? "none");
  const [power, setPower] = useState<string>(template?.power ?? "battery");
  const [defib, setDefib] = useState(template?.defib ?? false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const model = modelId || models.data?.[0]?.id || "";
  const list = projects.data?.items ?? [];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const requirements = {
        device_name: device,
        applied_part: appliedPart as "none" | "B" | "BF" | "CF",
        power_source: power as "battery" | "usb" | "mains" | "external_psu",
        defibrillation_proof: defib,
        notes: "",
      };
      const variants: ("A" | "B")[] = variant === "both" ? ["A", "B"] : [variant];
      const runs = [];
      for (const v of variants) {
        runs.push(
          await call(
            api.POST("/v1/runs", {
              body: { project_id: projectId, variant: v, model_id: model, requirements },
              headers: { "Idempotency-Key": idempotencyKey() },
            }),
          ),
        );
      }
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast(t("newRun.started"));
      onClose();
      const first = runs[0];
      if (runs.length === 1 && first)
        await navigate({ to: "/runs/$runId", params: { runId: first.id } });
      else await navigate({ to: "/projects/$projectId", params: { projectId } });
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={t("newRun.title")}
        description={t("newRun.lead")}
        closeLabel={t("common.close")}
      >
        <form onSubmit={submit}>
          <Field label={t("newRun.project")} required>
            {(id) =>
              list.length ? (
                <Select
                  id={id}
                  required
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  <option value="">{t("newRun.pickProject")}</option>
                  {list.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              ) : (
                <p className="pt-2 text-muted">
                  {t("newRun.noProjects")}{" "}
                  <Link
                    to="/projects"
                    onClick={onClose}
                    className="font-medium text-ink underline underline-offset-4"
                  >
                    {t("projects.new")}
                  </Link>
                </p>
              )
            }
          </Field>

          <fieldset className="grid gap-2 py-2 sm:grid-cols-[180px_1fr] sm:gap-6">
            <legend className="sr-only">{t("newRun.variant")}</legend>
            <span aria-hidden className="pt-2 text-[15px] font-medium">
              {t("newRun.variant")}
            </span>
            <div className="grid gap-3 sm:grid-cols-3">
              {VARIANTS.map((v) => (
                <label
                  key={v.id}
                  className={cn(
                    "flex cursor-pointer flex-col gap-2 rounded-card border p-3",
                    "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-focus",
                    variant === v.id ? "border-ink bg-paper/60" : "border-line hover:border-ink/40",
                  )}
                >
                  <input
                    type="radio"
                    name="variant"
                    value={v.id}
                    checked={variant === v.id}
                    onChange={() => setVariant(v.id)}
                    className="sr-only"
                  />
                  <PipelineSketch steps={v.steps} />
                  <span className="font-medium">
                    {t(`newRun.variant${v.id === "both" ? "Both" : v.id}`)}
                  </span>
                  <span className="text-sm text-muted">
                    {t(`newRun.variant${v.id === "both" ? "Both" : v.id}Hint`)}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <Field label={t("newRun.model")} required>
            {(id) => (
              <Select id={id} value={model} onChange={(e) => setModelId(e.target.value)}>
                {(models.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id} (
                    {m.license_class === "closed" ? t("newRun.closed") : t("newRun.openWeight")})
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("newRun.device")}>
            {(id) => (
              <Input
                id={id}
                maxLength={200}
                value={device}
                onChange={(e) => setDevice(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("newRun.appliedPart")}>
            {(id) => (
              <Select id={id} value={appliedPart} onChange={(e) => setAppliedPart(e.target.value)}>
                {["none", "B", "BF", "CF"].map((p) => (
                  <option key={p} value={p}>
                    {t(`newRun.appliedParts.${p}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("newRun.power")}>
            {(id) => (
              <Select id={id} value={power} onChange={(e) => setPower(e.target.value)}>
                {["battery", "usb", "mains", "external_psu"].map((p) => (
                  <option key={p} value={p}>
                    {t(`newRun.powers.${p}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="py-2 sm:pl-[204px]">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={defib}
                onChange={(e) => setDefib(e.target.checked)}
                className="size-4 accent-ink"
              />
              {t("newRun.defib")}
            </label>
          </div>
          {error ? (
            <p role="alert" className="mt-2 text-error">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="secondary" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={busy || !projectId || !model}>
              {t("newRun.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
