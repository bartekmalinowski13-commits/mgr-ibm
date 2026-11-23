import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogFooter,
  Field,
  Input,
  RunPathMini,
  Select,
} from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, type Schemas } from "../lib/api";
import { useIntentKeys } from "../lib/idempotency";
import type { NewRunPreset } from "../lib/layout";
import { useModels, useProjects } from "../lib/queries";
import { useToast } from "../lib/toast";
import { TEMPLATES } from "./templates";

type Choice = "A" | "B" | "both";

/**
 * Stages per variant as the run path shows them: A is LLM all the way, B is parsed and
 * normalised by rules with an LLM step for the MPN choice (the pipelines in the agents package).
 */
const PATHS: Record<Choice, ("llm" | "rule")[][]> = {
  A: [["llm", "llm", "llm", "llm"]],
  B: [["rule", "rule", "llm", "rule"]],
  both: [
    ["llm", "llm", "llm", "llm"],
    ["rule", "rule", "llm", "rule"],
  ],
};

const VARIANTS: { id: Choice }[] = [{ id: "A" }, { id: "B" }, { id: "both" }];

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
  const pending = useRef(false);
  const keys = useIntentKeys();
  /** Runs this dialog already started, per variant, with the request that started them. */
  const created = useRef(new Map<"A" | "B", { payload: string; run: Schemas["Run"] }>());
  const model = modelId || models.data?.[0]?.id || "";
  const list = projects.data?.items ?? [];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(undefined);
    const requirements = {
      device_name: device,
      applied_part: appliedPart as "none" | "B" | "BF" | "CF",
      power_source: power as "battery" | "usb" | "mains" | "external_psu",
      defibrillation_proof: defib,
      notes: "",
    };
    const variants: ("A" | "B")[] = variant === "both" ? ["A", "B"] : [variant];
    try {
      const runs = [];
      for (const v of variants) {
        const body = { project_id: projectId, variant: v, model_id: model, requirements };
        const payload = JSON.stringify(body);
        // "Both": a variant that already started for this exact form is not started again
        const already = created.current.get(v);
        if (already && already.payload === payload) {
          runs.push(already.run);
          continue;
        }
        const run = await call(
          api.POST("/v1/runs", {
            body,
            headers: { "Idempotency-Key": keys.keyFor(`run:${v}`, body) },
          }),
        );
        created.current.set(v, { payload, run });
        runs.push(run);
      }
      keys.done();
      created.current.clear();
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast(t("newRun.started"));
      onClose();
      const first = runs[0];
      if (runs.length === 1 && first)
        await navigate({ to: "/runs/$runId", params: { runId: first.id } });
      else await navigate({ to: "/projects/$projectId", params: { projectId } });
    } catch (err) {
      const started = variants.filter((v) => created.current.has(v));
      const message = problemMessage(err);
      setError(
        started.length
          ? `${t("newRun.partlyStarted", { variants: started.join(", ") })} ${message}`
          : message,
      );
    } finally {
      pending.current = false;
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
                <p className="pt-2 text-ink-soft">
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
                    "flex cursor-pointer flex-col gap-2 border p-3",
                    "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-focus",
                    variant === v.id
                      ? "border-2 border-ink bg-tint"
                      : "border border-ink hover:bg-tint",
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
                  <RunPathMini
                    rows={PATHS[v.id]}
                    description={t("newRun.pathSketch", {
                      variant: v.id === "both" ? "A, B" : v.id,
                      stages: PATHS[v.id]
                        .map((row) => row.map((a) => t(`run.actor.${a}`)).join(", "))
                        .join("; "),
                    })}
                  />
                  <span className="font-medium">
                    {t(`newRun.variant${v.id === "both" ? "Both" : v.id}`)}
                  </span>
                  <span className="text-sm text-ink-soft">
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
            <p role="alert" className="mt-2 text-status-error">
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
