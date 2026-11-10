import i18n from "../i18n";

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat(i18n.language).format(n);
}

export function formatSeconds(s: number): string {
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`;
}

export function isSimulatedModel(modelId: string): boolean {
  return modelId.startsWith("fake-");
}

export function modelLabel(modelId: string): string {
  if (modelId === "fake-closed") return "Symulator (zamknięty)";
  if (modelId === "fake-open-weight") return "Symulator (otwarty)";
  return modelId;
}
