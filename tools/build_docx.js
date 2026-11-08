// Generator szablonu pracy magisterskiej (format wzorowany na pracy inżynierskiej, PG WETI)
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, AlignmentType, HeadingLevel, LevelFormat,
  Footer, PageNumber, PageBreak, TableOfContents, Table, TableRow, TableCell, WidthType,
  BorderStyle, ShadingType, TabStopType, VerticalAlign,
} = require("docx");

const ROOT = process.argv[2];
const OUT = process.argv[3];
const img = (p) => fs.readFileSync(path.join(ROOT, p));

const FONT = "Arial";
const BODY = 20; // 10 pt jak w pracy inżynierskiej
const LINE = 360; // interlinia 1,5

// ---------- helpery ----------
const P = (text, opts = {}) => new Paragraph({
  alignment: AlignmentType.JUSTIFIED,
  indent: { firstLine: 567 },
  spacing: { line: LINE, after: 0 },
  children: [new TextRun({ text, ...opts })],
});
// wskazówka redakcyjna – do usunięcia przy pisaniu
const G = (text) => new Paragraph({
  alignment: AlignmentType.JUSTIFIED,
  indent: { firstLine: 567 },
  spacing: { line: LINE, after: 60 },
  children: [new TextRun({ text: "[Do napisania] ", bold: true, italics: true, color: "B45309" }),
             new TextRun({ text, italics: true, color: "6B7280" })],
});
const B = (text) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  alignment: AlignmentType.JUSTIFIED,
  spacing: { line: LINE, after: 0 },
  children: [new TextRun({ text, italics: true, color: "6B7280" })],
});
const H1 = (text, numbered = true) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  pageBreakBefore: true,
  numbering: numbered ? { reference: "headings", level: 0 } : undefined,
  children: [new TextRun(text.toUpperCase())],
});
const H2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, numbering: { reference: "headings", level: 1 }, children: [new TextRun(text)] });
const H3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, numbering: { reference: "headings", level: 2 }, children: [new TextRun(text)] });
const Caption = (text, keepNext = false) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 60, after: keepNext ? 120 : 240 }, keepNext,
  children: [new TextRun({ text, size: 18 })],
});
const Empty = (n = 1) => Array.from({ length: n }, () => new Paragraph({ children: [] }));
const Line = (label, value) => new Paragraph({
  spacing: { after: 0 },
  children: [new TextRun({ text: label, size: 20 }), new TextRun({ text: value, size: 20 })],
});

const border = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(widths, rows) {
  const total = widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((r, ri) => new TableRow({
      tableHeader: ri === 0,
      children: r.map((c, ci) => new TableCell({
        borders, width: { size: widths[ci], type: WidthType.DXA },
        verticalAlign: VerticalAlign.CENTER,
        shading: ri === 0 ? { fill: "E5E7EB", type: ShadingType.CLEAR, color: "auto" } : undefined,
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [new Paragraph({ children: [new TextRun({ text: c, size: 18, bold: ri === 0 })] })],
      })),
    })),
  });
}

// ---------- strona tytułowa ----------
const titlePage = [
  new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: 9070 }],
    children: [
      new ImageRun({ type: "png", data: img("img/pg_logo.png"), transformation: { width: 200, height: 55 } }),
      new TextRun("\t"),
      new ImageRun({ type: "png", data: img("img/eti_logo.png"), transformation: { width: 50, height: 51 } }),
    ],
  }),
  ...Empty(3),
  Line("Imię i nazwisko studenta: ", "Bartosz Malinowski"),
  Line("Nr albumu: ", "165395"),
  Line("Poziom kształcenia: ", "Studia drugiego stopnia"),
  Line("Forma studiów: ", "[stacjonarne / niestacjonarne]"),
  Line("Kierunek studiów: ", "[kierunek – uzupełnić wg systemu Moja PG]"),
  Line("Specjalność: ", "Inżynieria Biomedyczna"),
  ...Empty(4),
  new Paragraph({ children: [new TextRun({ text: "PRACA DYPLOMOWA MAGISTERSKA", bold: true, size: 24 })] }),
  ...Empty(2),
  new Paragraph({ spacing: { after: 200 }, children: [
    new TextRun({ text: "Tytuł pracy w języku polskim: " }),
    new TextRun("Porównanie systemu wieloagentowego opartego na dużych modelach językowych z systemem wieloagentowym z elementami deterministycznymi w zastosowaniu do generowania BOM urządzeń biomedycznych"),
  ] }),
  new Paragraph({ children: [
    new TextRun({ text: "Tytuł pracy w języku angielskim: " }),
    new TextRun("Comparison of an LLM-Based Multi-Agent System and a Multi-Agent System with Deterministic Components for Biomedical Device BOM Generation"),
  ] }),
  ...Empty(3),
  Line("Opiekun pracy: ", "dr inż. Magdalena Mazur-Milecka"),
  Line("Data ostatecznego zatwierdzenia raportu podobieństw w JSA: ", ""),
];

// ---------- oświadczenie ----------
const statement = [
  new Paragraph({ children: [new TextRun({ text: "OŚWIADCZENIE dotyczące pracy dyplomowej zatytułowanej:", bold: true })] }),
  new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Porównanie systemu wieloagentowego opartego na dużych modelach językowych z systemem wieloagentowym z elementami deterministycznymi w zastosowaniu do generowania BOM urządzeń biomedycznych", bold: true })] }),
  Line("Imię i nazwisko studenta: ", "Bartosz Malinowski"),
  Line("Nr albumu: ", "165395"),
  Line("Wydział: ", "Wydział Elektroniki, Telekomunikacji i Informatyki"),
  Line("Kierunek: ", "[kierunek]"),
  Line("Poziom kształcenia: ", "drugi"),
  Line("Forma studiów: ", "[stacjonarne / niestacjonarne]"),
  Line("Typ pracy: ", "praca dyplomowa magisterska"),
  ...Empty(1),
  G("Treść oświadczenia generowana jest w systemie Moja PG. Przed złożeniem pracy wkleić aktualną wersję z portalu (aktualne teksty jednolite ustawy o prawie autorskim i prawach pokrewnych oraz ustawy Prawo o szkolnictwie wyższym i nauce)."),
  ...Empty(2),
  new Paragraph({ children: [new TextRun("[data], Bartosz Malinowski")] }),
  new Paragraph({ children: [new TextRun({ text: "Data i podpis lub uwierzytelnienie w portalu uczelnianym Moja PG", size: 16 })] }),
];

// ---------- streszczenie / abstract ----------
const abstracts = [
  H1("Streszczenie", false),
  G("Ok. 1/2 strony. Cel pracy, zbudowany system (dwa warianty architektury), zbiór danych, przebieg eksperymentu, najważniejsze wyniki liczbowe (np. F1 pozycji BOM, odsetek halucynacji, koszt) i główny wniosek. Pisać na końcu, po rozdziale 7."),
  new Paragraph({ spacing: { before: 240, line: LINE }, children: [new TextRun({ text: "Słowa kluczowe: ", bold: true }), new TextRun("systemy wieloagentowe, duże modele językowe, LLM, RAG, zestawienie materiałowe, BOM, EDA, urządzenia biomedyczne, systemy hybrydowe")] }),
  new Paragraph({ spacing: { line: LINE }, children: [new TextRun({ text: "Dziedzina nauki i techniki, zgodnie z wymogami OECD: ", bold: true }), new TextRun("Nauki inżynieryjne i techniczne; inżynieria medyczna; inżynieria informatyczna")] }),
  H1("Abstract", false),
  G("English version of the summary (same content as Streszczenie)."),
  new Paragraph({ spacing: { before: 240, line: LINE }, children: [new TextRun({ text: "Keywords: ", bold: true }), new TextRun("multi-agent systems, large language models, LLM, retrieval-augmented generation, bill of materials, BOM, EDA, biomedical devices, hybrid systems")] }),
];

// ---------- spis treści ----------
const toc = [
  new Paragraph({ pageBreakBefore: true, children: [new TextRun({ text: "SPIS TREŚCI", bold: true, size: 24 })] }),
  new TableOfContents("Spis treści", { hyperlink: true, headingStyleRange: "1-3" }),
  new Paragraph({ children: [new TextRun({ text: "(W Wordzie: kliknij prawym na spis → Aktualizuj pole → Aktualizuj cały spis.)", italics: true, color: "6B7280", size: 16 })] }),
];

// ---------- skróty ----------
const abbr = [
  ["AI", "artificial intelligence – sztuczna inteligencja"],
  ["BOM", "bill of materials – zestawienie materiałowe"],
  ["CAD", "computer-aided design – projektowanie wspomagane komputerowo"],
  ["EDA", "electronic design automation"],
  ["IEC 60601", "rodzina norm bezpieczeństwa medycznych urządzeń elektrycznych"],
  ["LLM", "large language model – duży model językowy"],
  ["MAS", "multi-agent system – system wieloagentowy"],
  ["MCP", "Model Context Protocol"],
  ["MDR", "Medical Device Regulation – rozporządzenie UE 2017/745"],
  ["MPN", "manufacturer part number – numer katalogowy producenta"],
  ["PCB", "printed circuit board – płytka drukowana"],
  ["RAG", "retrieval-augmented generation – generowanie wspomagane wyszukiwaniem"],
];
const abbrevs = [
  H1("Wykaz ważniejszych skrótów i pojęć", false),
  ...abbr.map(([k, v]) => new Paragraph({
    tabStops: [{ type: TabStopType.LEFT, position: 1700 }], spacing: { after: 0 },
    children: [new TextRun(k), new TextRun("\t- " + v)],
  })),
  G("Uzupełniać na bieżąco, alfabetycznie."),
];

// ---------- rozdziały ----------
const body = [];
const add = (...x) => body.push(...x);

add(H1("Wstęp i cel pracy"));
add(H2("Motywacja"));
add(G("Problem: zestawienie materiałowe (BOM) jest kluczowym artefaktem projektu urządzenia biomedycznego – od niego zależą zakupy, koszt, identyfikowalność komponentów i dokumentacja techniczna wymagana przez MDR/ISO 13485. Ręczne przygotowanie i weryfikacja BOM są czasochłonne i podatne na błędy (zła obudowa, niedostępny komponent, niezgodne parametry)."));
add(G("Kontekst: rozwój LLM i agentów w EDA (ChatEDA, przegląd TODAES 2024). Otwarte pytanie: czy w zadaniu wymagającym precyzji lepiej oddać cały proces agentom LLM, czy ograniczyć LLM do kroków wymagających interpretacji, a resztę wykonać deterministycznie?"));
add(H2("Cel i zakres pracy"));
add(P("Celem pracy jest opracowanie i ewaluacja prototypowego systemu wieloagentowego służącego do automatycznego generowania i walidacji zestawień materiałowych (BOM) dla urządzeń biomedycznych. W ramach pracy przeprowadzona zostanie analiza porównawcza skuteczności podejścia opartego wyłącznie na dużych modelach językowych (LLM) wobec podejścia hybrydowego, łączącego agentów LLM z elementami deterministycznymi."));
add(G("Zakres: projekty w formacie KiCad (otwarte projekty urządzeń biomedycznych), komponenty elektroniczne i sensory; poza zakresem: części mechaniczne, oprogramowanie urządzenia, wycena rynkowa w czasie rzeczywistym (opcjonalnie)."));
add(H2("Pytania badawcze i hipotezy"));
add(B("PB1: Czy wariant hybrydowy generuje BOM o wyższej poprawności pozycji i pól (MPN, ilość, wartość, footprint) niż wariant 100% LLM?"));
add(B("PB2: Jak oba warianty różnią się odsetkiem halucynacji (nieistniejące MPN, błędne parametry)?"));
add(B("PB3: Jaki jest koszt obu podejść (tokeny, czas, liczba wywołań) i ich powtarzalność między uruchomieniami?"));
add(B("H1: Wariant hybrydowy osiąga wyższe F1 pozycji BOM i niższy odsetek halucynacji przy niższym koszcie."));
add(H2("Układ pracy"));
add(G("Krótki opis zawartości rozdziałów 2–8 (po 1–2 zdania na rozdział)."));

add(H1("Przegląd literatury"));
add(H2("Duże modele językowe i agenci LLM"));
add(G("Architektura transformer, wywoływanie narzędzi (function calling, MCP), wzorce agentowe (ReAct, plan-and-execute, reflection)."));
add(H2("Systemy wieloagentowe oparte na LLM"));
add(G("Taksonomia wg Guo i in. [3]: profile agentów, komunikacja, orkiestracja; frameworki (np. LangGraph, AutoGen, CrewAI); znane problemy: kumulacja błędów, koszty, niedeterminizm."));
add(H2("Generowanie wspomagane wyszukiwaniem (RAG)"));
add(G("Lewis i in. [1]; chunking dokumentacji technicznej, wyszukiwanie hybrydowe, specyfika datasheetów (tabele, parametry graniczne)."));
add(H2("Podejścia hybrydowe: LLM i komponenty deterministyczne"));
add(G("Systemy neuro-symboliczne, guardrails, walidacja wyjścia (structured output, JSON Schema), LLM jako komponent w potoku regułowym."));
add(H2("LLM w automatyzacji projektowania elektroniki (EDA)"));
add(G("ChatEDA [2], przegląd LLM for EDA [5]; zastosowania do schematów, PCB, doboru komponentów; luka: brak prac o generowaniu BOM dla urządzeń medycznych."));
add(H2("BOM w projektowaniu urządzeń biomedycznych"));
add(G("Rola BOM w dokumentacji technicznej (MDR 2017/745, ISO 13485), identyfikowalność, wymagania IEC 60601-1 wpływające na dobór komponentów (izolacja, prądy upływu), cykl życia komponentów."));
add(H2("Metody ewaluacji systemów opartych na LLM"));
add(G("RAGAS [4], metryki dokładności strukturalnej, LLM-as-a-judge i jego ograniczenia, powtarzalność."));
add(H2("Podsumowanie przeglądu i luka badawcza"));
add(G("Synteza: co jest znane, czego brakuje, jak niniejsza praca to uzupełnia."));

add(H1("Zbiór danych i baza wiedzy"));
add(H2("Dobór otwartych projektów urządzeń biomedycznych"));
add(G("Kryteria wyboru (licencja otwarta, format KiCad, dostępny BOM, zróżnicowana złożoność). Kandydaci do weryfikacji: projekty EKG/EEG/EMG, pulsoksymetry, interfejsy BCI. Tabela z listą projektów i statystykami (liczba komponentów, unikalnych pozycji)."));
add(H2("Referencyjne zestawienia materiałowe"));
add(G("Źródło BOM referencyjnych, ręczna weryfikacja i ujednolicenie do wspólnego schematu (Dodatek B)."));
add(H2("Dokumentacja techniczna komponentów"));
add(G("Zbieranie datasheetów (elektronika ogólna + sensory biomedyczne), ekstrakcja tekstu i tabel z PDF, metadane."));
add(H2("Budowa bazy wiedzy"));
add(G("Chunking, model embeddingów, indeks wektorowy, wyszukiwanie hybrydowe, ewaluacja jakości wyszukiwania (recall@k)."));
add(H2("Zbiór ewaluacyjny"));
add(G("Podział projektów, przypadki trudne (brak wartości, niejednoznaczne footprinty, komponenty wycofane)."));

add(H1("Narzędzia dostępu do plików CAD"));
add(H2("Struktura plików projektowych KiCad"));
add(G("Formaty .kicad_sch, .kicad_pcb, netlista; pola symboli (Reference, Value, Footprint, MPN, Manufacturer); kicad-cli."));
add(H2("Moduł parsera CAD"));
add(G("Implementacja parsera (wariant B używa bezpośrednio), testy jednostkowe na zbiorze projektów."));
add(H2("Interfejs narzędzi dla agentów"));
add(G("Udostępnienie parsera jako narzędzi (function calling / serwer MCP): list_components, get_component, get_nets, get_footprint. Wariant A korzysta z narzędzi wyłącznie poprzez wywołania agenta."));
add(H2("Weryfikacja modułu"));
add(G("Poprawność ekstrakcji względem kicad-cli bom export."));

add(H1("Projekt i implementacja systemu"));
add(H2("Wymagania funkcjonalne i niefunkcjonalne"));
add(G("Wejście, wyjście (BOM CSV/JSON + raport walidacji), śledzenie kroków, powtarzalność eksperymentu, logowanie tokenów i czasu."));
add(H2("Architektura ogólna"));
add(P("Rysunek 5.1 przedstawia architekturę systemu. Oba warianty korzystają z tego samego wejścia (projekt KiCad i wymagania urządzenia), tej samej bazy wiedzy RAG oraz tego samego modułu ewaluacji. Różnią się wyłącznie sposobem realizacji kroków przetwarzania: w wariancie A każdy krok realizuje agent LLM, w wariancie B kroki parsowania, normalizacji, walidacji i składania BOM są deterministyczne, a LLM używany jest tylko do doboru niejednoznacznych pozycji i naprawy pozycji odrzuconych przez reguły."));
add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200 }, children: [
  new ImageRun({ type: "png", data: img("docs/img/architektura.png"), transformation: { width: 600, height: 360 } }) ] }));
add(Caption("Rys. 5.1. Architektura systemu – wariant A (100% LLM) i wariant B (hybrydowy) [opracowanie własne]"));
add(H2("Wariant A – system wieloagentowy oparty wyłącznie na LLM"));
add(G("Orkiestrator, agent ekstrakcji, agent doboru, agent walidacji, agent kompozycji; protokół komunikacji; prompty (Dodatek A); pętla odrzucenie → ponowny dobór."));
add(H2("Wariant B – system hybrydowy"));
add(G("Parser CAD, normalizacja (jednostki, grupowanie, ilości), agent doboru tylko dla pozycji nierozstrzygniętych regułami, walidator regułowy (JSON Schema, zakresy parametrów, zgodność footprint–obudowa, checklista IEC 60601), agent naprawy z limitem iteracji, generator BOM."));
add(new Paragraph({ spacing: { before: 200 }, children: [] }));
add(Caption("Tab. 5.1. Porównanie realizacji kroków w obu wariantach", true));
add(table([2200, 3435, 3435], [
  ["Krok", "Wariant A – 100% LLM", "Wariant B – hybrydowy"],
  ["Odczyt projektu CAD", "agent LLM wywołuje narzędzia", "parser deterministyczny"],
  ["Normalizacja i grupowanie", "agent LLM", "reguły (kod)"],
  ["Dobór MPN", "agent LLM + RAG (wszystkie pozycje)", "reguły + agent LLM + RAG (tylko nierozstrzygnięte)"],
  ["Walidacja", "agent LLM", "walidator regułowy + agent naprawy"],
  ["Składanie i eksport BOM", "agent LLM", "generator deterministyczny"],
]));
add(H2("Komponenty wspólne"));
add(G("Baza wiedzy RAG, model LLM (ten sam dla obu wariantów), schemat wyjścia BOM, logowanie."));
add(H2("Interfejs użytkownika"));
add(G("Prototyp interfejsu: wczytanie projektu, wybór wariantu, podgląd przebiegu agentów, BOM z oznaczeniem pozycji niepewnych, porównanie wariantów (zrzuty ekranu)."));
add(H2("Stos technologiczny"));
add(G("Język i biblioteki (np. Python, framework agentowy, baza wektorowa), model(e) LLM i wersje, środowisko uruchomieniowe."));

add(H1("Metodyka badań"));
add(H2("Plan eksperymentu"));
add(G("Każdy projekt × każdy wariant × N powtórzeń; stałe parametry modelu (temperatura, wersja), ten sam indeks RAG."));
add(H2("Metryki"));
add(new Paragraph({ spacing: { before: 120 }, children: [] }));
add(Caption("Tab. 6.1. Metryki ewaluacji", true));
add(table([2600, 6470], [
  ["Metryka", "Definicja"],
  ["Precision / Recall / F1 pozycji", "zgodność zbioru pozycji BOM (designator → pozycja) z BOM referencyjnym"],
  ["Dokładność pól", "odsetek poprawnych: MPN, producent, wartość, footprint, ilość"],
  ["Odsetek halucynacji", "pozycje z MPN nieistniejącym w bazie wiedzy lub niezgodnym z parametrami"],
  ["Skuteczność walidacji", "odsetek błędów wykrytych przez moduł walidacji (wstrzyknięte błędy)"],
  ["Koszt", "liczba tokenów, wywołań LLM i czas wykonania na projekt"],
  ["Powtarzalność", "zgodność wyników między N uruchomieniami (np. wariancja F1)"],
]));
add(H2("Konfiguracja środowiska i modeli"));
add(G("Wersje modeli, parametry, sprzęt."));
add(H2("Analiza statystyczna"));
add(G("Test istotności dla par (np. test Wilcoxona), przedziały ufności."));

add(H1("Wyniki i dyskusja"));
add(H2("Jakość generowanych BOM"));
add(G("Tabele i wykresy F1 oraz dokładności pól dla obu wariantów, z podziałem na projekty."));
add(H2("Halucynacje i skuteczność walidacji"));
add(G("Przykłady błędów każdego wariantu."));
add(H2("Koszt i czas działania"));
add(H2("Powtarzalność wyników"));
add(H2("Analiza błędów"));
add(G("Kategoryzacja błędów: ekstrakcja, dobór, walidacja, format."));
add(H2("Dyskusja"));
add(G("Odpowiedzi na PB1–PB3, weryfikacja hipotezy H1, zagrożenia dla trafności wyników."));

add(H1("Podsumowanie i wnioski"));
add(H2("Wnioski"));
add(H2("Ograniczenia"));
add(H2("Kierunki dalszych prac"));
add(G("Np. integracja z dostępnością i cenami dystrybutorów, rozszerzenie na inne formaty CAD, analiza ryzyka komponentów pod MDR."));

add(H1("Bibliografia", false));
const refs = [
  "Lewis P., Perez E., Piktus A. et al., „Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks”, Advances in Neural Information Processing Systems (NeurIPS), vol. 33, s. 9459–9474, 2020.",
  "Wu H., He Z., Zhang X. et al., „ChatEDA: A Large Language Model Powered Autonomous Agent for EDA”, IEEE Transactions on Computer-Aided Design of Integrated Circuits and Systems, vol. 43, no. 10, 2024.",
  "Guo T. et al., „Large Language Model Based Multi-Agents: A Survey of Progress and Challenges”, Proceedings of IJCAI 2024, s. 8048–8057.",
  "Es S., James J., Espinosa-Anke L., Schockaert S., „RAGAS: Automated Evaluation of Retrieval Augmented Generation”, Proceedings of EACL 2024, s. 150–158.",
  "„A Survey of Research in Large Language Models for Electronic Design Automation”, ACM Transactions on Design Automation of Electronic Systems (TODAES), 2024.",
];
refs.forEach((r) => add(new Paragraph({ numbering: { reference: "refs", level: 0 }, alignment: AlignmentType.JUSTIFIED, spacing: { line: LINE, after: 60 }, children: [new TextRun(r)] })));
add(G("Dalsze pozycje dopisywać w tej samej numeracji; cytowanie w tekście w nawiasach kwadratowych [n], jak w pracy inżynierskiej."));

add(H1("Wykaz rysunków", false));
add(new Paragraph({ spacing: { after: 0 }, children: [new TextRun("Rys. 5.1. Architektura systemu – wariant A (100% LLM) i wariant B (hybrydowy)")] }));
add(new Paragraph({ spacing: { before: 360 }, children: [new TextRun({ text: "WYKAZ TABEL", bold: true, size: 24 })] }));
add(new Paragraph({ spacing: { after: 0 }, children: [new TextRun("Tab. 5.1. Porównanie realizacji kroków w obu wariantach")] }));
add(new Paragraph({ spacing: { after: 0 }, children: [new TextRun("Tab. 6.1. Metryki ewaluacji")] }));

add(H1("Dodatki", false));
add(new Paragraph({ spacing: { line: LINE }, children: [new TextRun({ text: "Dodatek A. Prompty i profile agentów", bold: true })] }));
add(new Paragraph({ spacing: { line: LINE }, children: [new TextRun({ text: "Dodatek B. Schemat danych BOM (JSON Schema)", bold: true })] }));
add(new Paragraph({ spacing: { line: LINE }, children: [new TextRun({ text: "Dodatek C. Repozytorium kodu i instrukcja uruchomienia", bold: true })] }));

// ---------- dokument ----------
const doc = new Document({
  creator: "Bartosz Malinowski",
  title: "Praca dyplomowa magisterska – szablon",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: BODY } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true },
        paragraph: { spacing: { before: 240, after: 360 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 20, bold: true, italics: true },
        paragraph: { spacing: { before: 360, after: 200 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 20, italics: true },
        paragraph: { spacing: { before: 240, after: 120 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: "headings", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 425, hanging: 425 } } } },
      { level: 1, format: LevelFormat.DECIMAL, text: "%1.%2.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1134, hanging: 567 } } } },
      { level: 2, format: LevelFormat.DECIMAL, text: "%1.%2.%3.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1418, hanging: 709 } } } },
    ] },
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: "refs", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "[%1]", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 567 } } } }] },
  ] },
  sections: [
    { properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1417, bottom: 1417, left: 1418, right: 1418 } } },
      children: titlePage },
    { properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1417, bottom: 1417, left: 1418, right: 1418 }, pageNumbers: { start: 2 } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ children: [PageNumber.CURRENT] })] })] }) },
      children: [...statement, ...abstracts, ...toc, ...abbrevs, ...body] },
  ],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(OUT, b); console.log("ok", OUT); });
