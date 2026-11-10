import * as Dialog from "@radix-ui/react-dialog";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { clsx } from "clsx";
import { type ReactNode, useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import type { Design, Requirements, Variant } from "../api/types";
import { useApp } from "../state";
import { Button } from "./ui";

/* Model catalogue as the API enforces it (packages/py/llm catalog): real models stay
 * disabled until their EU availability is verified by a human. */
export const MODELS = [
  { id: "fake-closed", label: "Symulator", license: "closed", enabled: true },
  { id: "fake-open-weight", label: "Symulator", license: "open-weight", enabled: true },
  { id: "claude-opus-eu", label: "Claude · Bedrock UE", license: "closed", enabled: false },
  { id: "gpt-eu", label: "GPT · Azure OpenAI EU", license: "closed", enabled: false },
  { id: "llama-eu", label: "Llama · Bedrock UE", license: "open-weight", enabled: false },
] as const;

type Choice = Variant | "AB";

interface FormValues {
  name: string;
  designId: string;
  appliedPart: NonNullable<Requirements["applied_part"]>;
  power: NonNullable<Requirements["power_source"]>;
  modelId: string;
  variant: Choice;
}
const DEFAULTS: FormValues = {
  name: "",
  designId: "",
  appliedPart: "BF",
  power: "battery",
  modelId: "fake-closed",
  variant: "AB",
};

function Row({
  label,
  htmlFor,
  children,
  error,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
  error?: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-1.5 border-t border-line px-6 py-3.5 first:border-t-0 sm:grid-cols-[160px_1fr] sm:items-center sm:gap-6">
      <label htmlFor={htmlFor} className="text-[13.5px] text-ink-soft">
        {label}
      </label>
      <div>
        {children}
        {error && (
          <p role="alert" className="mt-1 text-[12.5px] text-err">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

const inputCls =
  "h-9 w-full rounded-[var(--radius-control)] border border-line bg-paper px-3 text-[13.5px] focus:border-ink focus:bg-surface focus:outline-none";

function PipelineGlyph({ steps }: { steps: Array<"l" | "r"> }) {
  return (
    <span className="flex gap-1" aria-hidden>
      {steps.map((s, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed decorative sequence
          key={i}
          className={clsx("h-2 w-5 rounded-sm", s === "l" ? "bg-llm" : "bg-rule")}
        />
      ))}
    </span>
  );
}

async function allDesigns(
  api: ReturnType<typeof useApp>["api"],
): Promise<Array<Design & { projectName: string }>> {
  const projects = (await api.listProjects()).items;
  const lists = await Promise.all(projects.map((p) => api.listDesigns(p.id)));
  return lists.flatMap((l, i) =>
    l.items.map((d) => ({ ...d, projectName: projects[i]?.name ?? "" })),
  );
}

export function NewRunDialog() {
  const { t } = useTranslation();
  const { api, orgId, newRunOpen, closeNewRun, newRunDesign, notify } = useApp();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: designs = [] } = useQuery({
    queryKey: [orgId, "all-designs"],
    queryFn: () => allDesigns(api),
    enabled: newRunOpen,
  });
  const parsed = designs.filter((d) => d.status === "parsed");
  const { register, handleSubmit, control, formState, reset, getValues, setValue } =
    useForm<FormValues>({
      defaultValues: DEFAULTS,
    });
  // fresh form each time the dialog opens (optionally pre-selecting a design)
  useEffect(() => {
    if (newRunOpen) reset({ ...DEFAULTS, designId: newRunDesign ?? "" });
  }, [newRunOpen, newRunDesign, reset]);
  // designs load after opening: pick the first ready one without touching what was typed
  const firstParsed = parsed[0]?.id;
  useEffect(() => {
    if (firstParsed && !getValues("designId")) setValue("designId", firstParsed);
  }, [firstParsed, getValues, setValue]);

  const submit = handleSubmit(async (v) => {
    const variants: Variant[] = v.variant === "AB" ? ["A", "B"] : [v.variant];
    const requirements: Requirements = {
      device_name: v.name,
      applied_part: v.appliedPart,
      power_source: v.power,
      defibrillation_proof: false,
      notes: "",
    };
    const runs = await Promise.all(
      variants.map((variant) =>
        api.createRun(
          { design_id: v.designId, variant, model_id: v.modelId, requirements },
          crypto.randomUUID(),
        ),
      ),
    );
    await qc.invalidateQueries({ queryKey: [orgId] });
    closeNewRun();
    notify(t("newRun.started"));
    if (runs.length === 2)
      await navigate({ to: "/compare", search: { a: runs[0]?.id, b: runs[1]?.id } });
    else if (runs[0]) await navigate({ to: "/runs/$runId", params: { runId: runs[0].id } });
  });

  return (
    <Dialog.Root open={newRunOpen} onOpenChange={(o) => !o && closeNewRun()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/35" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 z-50 max-h-[92vh] w-[min(640px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-[var(--radius-card)] bg-surface shadow-[0_24px_80px_rgba(21,24,30,0.25)]"
          aria-describedby={undefined}
        >
          <form onSubmit={submit} noValidate>
            <div className="flex items-center justify-between border-b border-line px-6 py-4">
              <Dialog.Title className="text-[17px] font-semibold">{t("newRun.title")}</Dialog.Title>
              <Dialog.Close
                className="rounded-md p-1 text-muted hover:bg-paper"
                aria-label={t("newRun.cancel")}
              >
                <svg viewBox="0 0 20 20" className="size-5" aria-hidden>
                  <path
                    d="M5 5l10 10M15 5L5 15"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </Dialog.Close>
            </div>
            <Row
              label={`${t("newRun.name")}*`}
              htmlFor="nr-name"
              error={formState.errors.name && t("newRun.required")}
            >
              <input
                id="nr-name"
                className={inputCls}
                {...register("name", { required: true, maxLength: 200 })}
              />
            </Row>
            <Row
              label={`${t("newRun.design")}*`}
              htmlFor="nr-design"
              error={formState.errors.designId && t("newRun.noDesign")}
            >
              <select
                id="nr-design"
                className={inputCls}
                {...register("designId", { required: true })}
              >
                {parsed.length === 0 && <option value="">{t("newRun.noDesign")}</option>}
                {parsed.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.projectName} · {d.filenames[0]}
                  </option>
                ))}
              </select>
            </Row>
            <Row label={t("newRun.appliedPart")} htmlFor="nr-ap">
              <select id="nr-ap" className={inputCls} {...register("appliedPart")}>
                <option value="none">brak</option>
                <option value="B">B</option>
                <option value="BF">BF – kontakt z ciałem</option>
                <option value="CF">CF – kontakt z sercem</option>
              </select>
            </Row>
            <Row label={t("newRun.power")} htmlFor="nr-power">
              <select id="nr-power" className={inputCls} {...register("power")}>
                <option value="battery">bateria</option>
                <option value="usb">USB</option>
                <option value="mains">sieć (zasilacz wewnętrzny)</option>
                <option value="external_psu">zewnętrzny zasilacz medyczny</option>
              </select>
            </Row>
            <Row label={t("newRun.model")} htmlFor="nr-model">
              <select id="nr-model" className={inputCls} {...register("modelId")}>
                {MODELS.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.enabled}>
                    {m.label} (
                    {m.license === "closed" ? t("newRun.closed") : t("newRun.openWeight")})
                    {m.enabled ? "" : " – wymaga weryfikacji"}
                  </option>
                ))}
              </select>
            </Row>
            <Row label={t("newRun.variant")}>
              <Controller
                control={control}
                name="variant"
                render={({ field }) => (
                  <RadioGroup.Root
                    value={field.value}
                    onValueChange={field.onChange}
                    aria-label={t("newRun.variant")}
                    className="grid grid-cols-1 gap-2 sm:grid-cols-3"
                  >
                    {(
                      [
                        [
                          "A",
                          t("newRun.variantA"),
                          t("newRun.variantAHint"),
                          ["l", "l", "l", "l", "l"],
                        ],
                        [
                          "B",
                          t("newRun.variantB"),
                          t("newRun.variantBHint"),
                          ["r", "r", "l", "r", "r"],
                        ],
                        ["AB", "A + B", t("compare.title"), ["l", "r", "l", "r", "l"]],
                      ] as const
                    ).map(([value, title, hint, glyph]) => (
                      <RadioGroup.Item
                        key={value}
                        value={value}
                        className="flex flex-col items-start gap-2 rounded-[var(--radius-control)] border border-line p-3 text-left hover:border-line-strong data-[state=checked]:border-ink data-[state=checked]:shadow-[0_0_0_1px_var(--color-ink)]"
                      >
                        <PipelineGlyph steps={[...glyph]} />
                        <span className="text-[13.5px] font-semibold">{title}</span>
                        <span className="text-[12px] leading-snug text-muted">{hint}</span>
                      </RadioGroup.Item>
                    ))}
                  </RadioGroup.Root>
                )}
              />
            </Row>
            <div className="flex justify-end gap-2 border-t border-line px-6 py-4">
              <Button onClick={closeNewRun}>{t("newRun.cancel")}</Button>
              <Button variant="primary" type="submit" disabled={formState.isSubmitting}>
                {t("newRun.submit")}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
