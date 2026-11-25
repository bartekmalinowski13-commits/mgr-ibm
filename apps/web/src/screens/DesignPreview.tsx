import {
  Button,
  MaskPanel,
  type Provenance,
  ProvenanceGlyph,
  ProvenanceLegend,
  Sheet,
  SheetHeader,
  Silk,
  StatusBadge,
  TitleBlock,
  VariantChip,
  ViaTimeline,
} from "@bomagent/ui";
import { useEffect } from "react";

const KINDS: Provenance[] = ["agent", "rule", "parser", "user"];

/**
 * Preview of the ADR-0019 base components (instead of stories): `/design`, no sign-in, no data.
 * Copy here is sample text for the preview only.
 */
export function DesignPreview() {
  useEffect(() => {
    document.title = "Komponenty – BOM Agent";
  }, []);
  return (
    <main className="min-h-screen bg-vellum p-4">
      <Sheet
        titleBlock={
          <TitleBlock
            label="Tabliczka rysunkowa"
            name="Komponenty"
            sheetLabel="Arkusz 1 z 1"
            cells={[
              { label: "Projekt", value: "BOM Agent" },
              { label: "Rewizja", value: "ADR-0019" },
              { label: "Wariant", value: "A + B" },
              { label: "Model", value: "mistral-large-eu" },
              { label: "Wejście", value: "holter-c.kicad_pcb" },
              { label: "Data", value: "24.11.2026" },
            ]}
          />
        }
      >
        <SheetHeader actions={<Button>Przycisk główny</Button>}>
          <h1 className="text-[17px] font-semibold">Komponenty rysunku wykonawczego</h1>
        </SheetHeader>
        <div className="flex flex-col gap-12 px-4 py-8 sm:px-10">
          <section className="flex flex-col gap-4">
            <h2 className="font-display text-[22px]">Pochodzenie decyzji</h2>
            <ul className="flex flex-wrap gap-6">
              {KINDS.map((k) => (
                <li key={k} className="flex items-center gap-2">
                  <ProvenanceGlyph kind={k} size={16} label={k} />{" "}
                  <span className="font-data text-[12px]">{k}</span>
                </li>
              ))}
            </ul>
            <ProvenanceLegend
              labels={{ parser: "z pliku", rule: "reguła", agent: "agent LLM", user: "człowiek" }}
            />
            <div className="flex flex-wrap gap-3">
              <VariantChip variant="A" label="A: tylko LLM" />
              <VariantChip variant="B" label="B: hybryda" />
              <VariantChip variant="A" />
              <VariantChip variant="B" />
            </div>
          </section>
          <section className="flex flex-col gap-4">
            <h2 className="font-display text-[22px]">Stany i przyciski</h2>
            <div className="flex flex-wrap gap-5">
              <StatusBadge status="ok" label="zgodne" />
              <StatusBadge status="warn" label="sprawdź" />
              <StatusBadge status="error" label="IEC 60601" />
              <StatusBadge status="running" label="Trwa: walidacja" />
              <StatusBadge status="pending" label="W kolejce" />
            </div>
            <div className="flex flex-wrap gap-3">
              <Button>Zatwierdź</Button>
              <Button variant="secondary">Zmień MPN</Button>
              <Button variant="ghost">Eksportuj XLSX</Button>
              <Button variant="danger">Usuń</Button>
              <Button size="sm" variant="secondary">
                Zamknij
              </Button>
            </div>
          </section>
          <section className="flex flex-col gap-4">
            <h2 className="font-display text-[22px]">Ścieżki przebiegu</h2>
            <ViaTimeline
              stateLabels={{ done: "zrobione", current: "trwa", todo: "czeka" }}
              tracks={[
                {
                  label: "A: tylko LLM",
                  tone: "llm",
                  steps: [
                    { name: "Odczyt CAD", state: "done", time: "18 s", executor: "agent" },
                    { name: "Dobór MPN", state: "current", time: "trwa", executor: "agent" },
                    { name: "Walidacja", state: "todo", executor: "agent" },
                  ],
                },
                {
                  label: "B: hybryda",
                  tone: "rule",
                  steps: [
                    { name: "Odczyt CAD", state: "done", time: "2 s", executor: "parser" },
                    { name: "Dobór MPN", state: "done", time: "41 s", executor: "reguły + agent" },
                    { name: "Walidacja", state: "current", time: "trwa", executor: "reguły" },
                  ],
                },
              ]}
            />
          </section>
          <section className="flex flex-col gap-4">
            <h2 className="font-display text-[22px]">Panel płytki</h2>
            <MaskPanel className="max-w-[560px] px-12 py-10">
              <Silk>BOM-AGENT REV C · WARIANT A ↔ B</Silk>
              <p className="mt-3 font-display text-[40px]">Jeden wniosek na ekran.</p>
              <p className="mt-3 text-[16px]">
                Panel płytki pojawia się tylko tam, gdzie pada wniosek.
              </p>
              <button type="button" className="mt-4 underline underline-offset-4">
                Fokus na płytce jest złoty
              </button>
            </MaskPanel>
          </section>
        </div>
      </Sheet>
    </main>
  );
}
