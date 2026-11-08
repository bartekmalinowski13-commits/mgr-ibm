# Generuje SVG architektury systemu (wariant A: 100% LLM, wariant B: hybrydowy)
import html, sys

W, H = 1500, 900
LLM = ("#f3efff", "#6d28d9", "LLM")
DET = ("#e8f5f2", "#0f766e", "DET")
DAT = ("#fff6e0", "#b45309", "DANE")
EVL = ("#eef2ff", "#1e3a8a", "EVAL")

out = []
def a(s): out.append(s)
def esc(s): return html.escape(s)

def box(x, y, w, h, kind, title, lines, tag=True):
    fill, stroke, lab = kind
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
    if tag:
        tw = 8 + 7 * len(lab)
        a(f'<rect x="{x+w-tw-8}" y="{y+8}" width="{tw}" height="17" rx="8.5" fill="{stroke}"/>')
        a(f'<text x="{x+w-tw/2-8}" y="{y+20.5}" class="tag" text-anchor="middle">{lab}</text>')
    a(f'<text x="{x+12}" y="{y+42}" class="bt" fill="{stroke}">{esc(title)}</text>')
    for i, l in enumerate(lines):
        a(f'<text x="{x+12}" y="{y+62+i*16}" class="bs">{esc(l)}</text>')

def arrow(pts, label=None, lx=None, ly=None, dash=False, color="#334155"):
    d = "M" + " L".join(f"{px},{py}" for px, py in pts)
    da = ' stroke-dasharray="5 4"' if dash else ""
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.6"{da} marker-end="url(#ah)"/>')
    if label:
        a(f'<text x="{lx}" y="{ly}" class="al" text-anchor="middle">{esc(label)}</text>')

a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, Arial, sans-serif">')
a('''<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#334155"/></marker>
<style>.bt{font-size:14px;font-weight:700}.bs{font-size:11.5px;fill:#334155}.tag{font-size:10px;font-weight:700;fill:#fff;letter-spacing:.04em}
.lt{font-size:15px;font-weight:700;fill:#0f172a;paint-order:stroke;stroke:#f7fbfa;stroke-width:6px}.ls{font-size:12px;fill:#475569;paint-order:stroke;stroke:#f7fbfa;stroke-width:6px}.al{font-size:11px;fill:#475569;font-style:italic}
.h1{font-size:20px;font-weight:800;fill:#0f172a}.h2{font-size:12.5px;fill:#475569}</style></defs>''')
a(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
a('<text x="30" y="42" class="h1">Architektura systemu generowania BOM — porównanie wariantów</text>')
a('<text x="30" y="64" class="h2">Wspólne wejście, wspólna baza wiedzy i wspólna ewaluacja; warianty różnią się wyłącznie sposobem realizacji kroków przetwarzania.</text>')

# Input
box(30, 330, 220, 180, DAT, "Projekt urządzenia", ["schemat i PCB KiCad", "(.kicad_sch, .kicad_pcb,", " netlista)", "+ wymagania urządzenia", "  (klasa, zasilanie, sensory)"])
arrow([(250, 380), (272, 380), (272, 215), (308, 215)])
arrow([(250, 460), (272, 460), (272, 605), (308, 605)])

# Lanes
a('<rect x="290" y="88" width="880" height="272" rx="14" fill="#faf8ff" stroke="#c4b5fd" stroke-dasharray="6 5"/>')
a('<text x="308" y="114" class="lt">Wariant A — system wieloagentowy 100% LLM</text>')
a('<text x="308" y="134" class="ls">Każdy krok wykonuje agent LLM; deterministyczne są tylko narzędzia odczytu plików, wywoływane przez agenta.</text>')
a('<rect x="290" y="480" width="880" height="320" rx="14" fill="#f7fbfa" stroke="#99d5c9" stroke-dasharray="6 5"/>')
a('<text x="308" y="506" class="lt">Wariant B — system hybrydowy (LLM + komponenty deterministyczne)</text>')
a('<text x="308" y="526" class="ls">Parsowanie, normalizacja, walidacja i składanie BOM są regułowe; LLM tylko tam, gdzie potrzebna jest interpretacja.</text>')

BW, G, X0 = 152, 22, 308
xs = [X0 + i * (BW + G) for i in range(5)]
ya, yb = 160, 550
A = [("Orkiestrator", ["planuje zadanie,", "deleguje do agentów,", "scala wyniki"]),
     ("Agent ekstrakcji", ["czyta CAD przez", "narzędzia (tool calls),", "wypisuje komponenty"]),
     ("Agent doboru", ["mapuje wartości na", "MPN / producenta", "z użyciem RAG"]),
     ("Agent walidacji", ["sprawdza spójność", "parametrów i obudów", "(ocena LLM)"]),
     ("Agent kompozycji", ["grupuje pozycje,", "liczy ilości,", "formatuje BOM"])]
for x, (t, l) in zip(xs, A):
    box(x, ya, BW, 112, LLM, t, l)
for i in range(4):
    arrow([(xs[i] + BW, ya + 56), (xs[i + 1] - 2, ya + 56)])
# feedback A
fx1, fx2 = xs[3] + BW / 2, xs[2] + BW / 2 + 40
arrow([(fx1, ya + 112), (fx1, 330), (fx2, 330), (fx2, ya + 114)], "odrzucenie → ponowny dobór", (fx1 + fx2) / 2, 348, dash=True)

B = [(DET, "Parser CAD", ["odczyt netlisty i", "pól symboli (ref,", "wartość, footprint)"]),
     (DET, "Normalizacja", ["jednostki, wartości,", "grupowanie i", "liczenie ilości"]),
     (LLM, "Agent doboru", ["tylko pozycje", "nierozstrzygnięte", "regułami; RAG"]),
     (DET, "Walidator regułowy", ["schemat JSON, zakresy,", "footprint ↔ obudowa,", "checklista IEC 60601"]),
     (DET, "Generator BOM", ["składanie pozycji,", "eksport CSV / JSON,", "raport walidacji"])]
for x, (k, t, l) in zip(xs, B):
    box(x, yb, BW, 112, k, t, l)
for i in range(4):
    lab = "OK" if i == 3 else None
    arrow([(xs[i] + BW, yb + 56), (xs[i + 1] - 2, yb + 56)], lab, (xs[i] + BW + xs[i + 1]) / 2, yb + 48)
# repair agent below validator
rx = xs[3]
box(rx - 2, 697, BW + 4, 88, LLM, "Agent naprawy", ["koryguje pozycje", "odrzucone przez reguły"])
a(f'<text x="{rx-58}" y="{740}" class="al" text-anchor="middle">maks. N iteracji</text>')
arrow([(rx + 50, yb + 112), (rx + 50, 695)], "błąd", rx + 30, 685)
arrow([(rx + 102, 697), (rx + 102, yb + 114)], "poprawka", rx + 130, 685)

# KB band
a('<rect x="290" y="378" width="880" height="84" rx="12" fill="#fff6e0" stroke="#b45309" stroke-width="1.6"/>')
a('<text x="308" y="406" class="bt" fill="#b45309">Wspólna baza wiedzy (RAG)</text>')
a('<text x="308" y="426" class="bs">datasheety komponentów elektronicznych i sensorów biomedycznych · chunking · embeddingi + metadane (MPN, parametry)</text>')
a('<text x="308" y="444" class="bs">wyszukiwanie hybrydowe (wektorowe + słowa kluczowe) · ten sam indeks i ten sam model embeddingów dla obu wariantów</text>')
kx = xs[2] + BW / 2 - 30
arrow([(kx, 378), (kx, ya + 114)], dash=True, color="#b45309")
a(f'<path d="M{kx},462 L{kx},486" stroke="#b45309" stroke-width="1.6" stroke-dasharray="5 4"/>')
arrow([(kx, 534), (kx, yb - 2)], dash=True, color="#b45309")

# outputs
box(1210, 180, 260, 76, DAT, "BOM — wariant A", ["CSV / JSON + log rozumowania"], tag=False)
box(1210, 572, 260, 76, DAT, "BOM — wariant B", ["CSV / JSON + raport walidacji"], tag=False)
arrow([(xs[4] + BW, ya + 56), (1208, 218)])
arrow([(xs[4] + BW, yb + 56), (1208, 610)])
box(1210, 315, 260, 210, EVL, "Moduł ewaluacji", ["porównanie z BOM referencyjnym:", "• precision / recall pozycji", "• poprawność pól (MPN, ilość,", "   wartość, footprint)", "• odsetek halucynacji MPN", "• koszt: tokeny, czas, wywołania", "• powtarzalność (N uruchomień)"])
arrow([(1340, 256), (1340, 313)])
arrow([(1340, 572), (1340, 527)])

# legend
ly = 838
a(f'<text x="30" y="{ly+14}" class="lt">Legenda</text>')
items = [(LLM, "krok realizowany przez agenta LLM"), (DET, "komponent deterministyczny (kod, reguły)"),
         (DAT, "dane wejściowe / wyjściowe / baza wiedzy"), (EVL, "ewaluacja eksperymentu")]
lx = 130
for (fill, stroke, lab), txt in items:
    a(f'<rect x="{lx}" y="{ly}" width="22" height="18" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
    a(f'<text x="{lx+30}" y="{ly+14}" class="bs">{esc(txt)}</text>')
    lx += 330
a('<path d="M1235,878 L1275,878" stroke="#334155" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#ah)"/>')
a('<text x="1285" y="882" class="bs">zapytanie do RAG / pętla zwrotna</text>')
a('<text x="308" y="506" class="lt">Wariant B — system hybrydowy (LLM + komponenty deterministyczne)</text>')
a('<text x="308" y="526" class="ls">Parsowanie, normalizacja, walidacja i składanie BOM są regułowe; LLM tylko tam, gdzie potrzebna jest interpretacja.</text>')
a('</svg>')
open(sys.argv[1], "w").write("\n".join(out))
