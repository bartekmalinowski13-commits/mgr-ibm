import type { Page, Route } from "@playwright/test";

/**
 * Deterministic `/v1` for the visual checks of the "fabrication drawing" screens (ADR-0019):
 * the data of the mock-ups in docs/design/direction-v1 (Holter EKG 3-kan. rev C, Nordvital).
 * No API, database or LLM is needed: every request is answered here.
 */

export const ORG = "00000000-0000-4000-8000-0000000000a1";
export const PROJECT = "00000000-0000-4000-8000-0000000000b1";
export const PROJECT_2 = "00000000-0000-4000-8000-0000000000b2";
export const PROJECT_3 = "00000000-0000-4000-8000-0000000000b3";
export const RUN_A = "00000000-0000-4000-8000-000000000142";
export const RUN_B = "00000000-0000-4000-8000-000000000143";
export const RUN_B_DONE = "00000000-0000-4000-8000-000000000141";
export const RUN_A_DONE = "00000000-0000-4000-8000-000000000140";
export const RUN_FAILED = "00000000-0000-4000-8000-000000000133";
const SUB = "dev-bartek-nordvital-example";

const MODEL = "mistral-large-eu";
const RULES = { rule_pack: "iec60601-core", rule_pack_version: "1.4.0" };

function prov(kind: "parser" | "rule" | "agent" | "user", extra: Record<string, unknown> = {}) {
  const base = { kind, rationale: "", at: "2026-11-25T14:02:00Z" };
  if (kind === "parser") return { ...base, parser: "kicad-8", ...extra };
  if (kind === "rule") return { ...base, rule_id: "mpn.passive_series", ...RULES, ...extra };
  if (kind === "agent") return { ...base, agent: "mpn_select", model_id: MODEL, ...extra };
  return { ...base, user_id: "Bartek", ...extra };
}

function item(
  line: number,
  refdes: string[],
  value: string,
  pkg: string,
  mpn: string,
  manufacturer: string,
  kind: "parser" | "rule" | "agent" | "user",
  extra: { description?: string; fields?: Record<string, string>; mpnProv?: object } = {},
) {
  return {
    line,
    refdes,
    quantity: refdes.reduce((n, r) => n + (r.includes("–") ? 9 : 1), 0),
    kind: refdes[0]?.replace(/[0-9–-].*$/, "") ?? "other",
    value,
    footprint: `Package:${pkg}`,
    package: pkg,
    manufacturer,
    mpn,
    description: extra.description ?? "",
    dnp: false,
    fields: extra.fields ?? {},
    provenance: { mpn: extra.mpnProv ?? prov(kind), value: prov("parser") },
  };
}

const BOARD = "0,0,60,40";
const at = (x: number, y: number, layer = "F.Cu", w = 5, h = 5) => ({
  "pcb.x": String(x),
  "pcb.y": String(y),
  "pcb.w": String(w),
  "pcb.h": String(h),
  "pcb.layer": layer,
  "pcb.board": BOARD,
});

const ITEMS = [
  item(
    1,
    ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C14"],
    "100 nF",
    "0402",
    "GRM155R71C104KA88D",
    "Murata",
    "rule",
  ),
  item(2, ["C10", "C11"], "10 µF", "0603", "GRM188R61A106KE69D", "Murata", "rule"),
  item(3, ["C12"], "4,7 µF", "0603", "CL10A475KO8NNNC", "Samsung", "agent"),
  item(
    4,
    ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"],
    "10 kΩ",
    "0402",
    "RC0402FR-0710KL",
    "Yageo",
    "rule",
  ),
  item(5, ["R22"], "1 MΩ", "0402", "ERJ-2RKF1004X", "Panasonic", "user"),
  item(6, ["U3"], "—", "WQFN-28", "ADS1293CISQE/NOPB", "Texas Instruments", "agent", {
    description: "3-kanałowy front-end EKG",
    fields: at(22, 18),
    mpnProv: prov("agent", {
      rationale:
        "Agent doboru dopasował symbol ADS1293 z projektu do karty katalogowej. Wariant w obudowie WQFN pasuje do footprintu na płytce.",
      citations: [
        {
          chunk_id: "c-ads1293-1",
          document_id: "d-ads1293",
          page: 1,
          scope: "global",
          quote: "Three-channel, 24-bit analog front-end for biopotential measurements.",
        },
      ],
    }),
  }),
  item(7, ["U4"], "—", "QFN-48", "NRF52832-QFAA-R", "Nordic", "agent", {
    fields: at(38, 10, "F.Cu", 6, 6),
  }),
  item(8, ["U5"], "3,3 V", "SOT-23-5", "TPS7A0233PDBVR", "Texas Instruments", "rule"),
  item(9, ["U7"], "—", "WCSP-25", "BQ25125YFPR", "Texas Instruments", "agent", {
    fields: at(48, 28, "B.Cu", 4, 4),
  }),
  item(10, ["J1"], "—", "USB-C", "USB4105-GF-A", "GCT", "parser"),
  item(11, ["L1"], "2,2 µH", "0806", "DFE201610E-2R2M=P2", "Murata", "rule"),
  item(12, ["Y1"], "32 MHz", "2016", "TSX-3225 32.0000MF20G-AC3", "Epson", "agent"),
];

const FINDINGS = [
  {
    rule_id: "iec60601.isolation",
    severity: "error",
    message: "IEC 60601: ładowarka bez separacji galwanicznej",
    refdes: ["U7"],
    line: 9,
    ...RULES,
  },
  {
    rule_id: "mpn.dielectric",
    severity: "review",
    message: "Sprawdź dielektryk: referencja ma X7R",
    refdes: ["C12"],
    line: 3,
    ...RULES,
  },
  {
    rule_id: "mpn.footprint_match",
    severity: "review",
    message: "Sprawdź: kwarc spoza listy referencyjnej",
    refdes: ["Y1"],
    line: 12,
    ...RULES,
  },
];

const USAGE_A = {
  llm_calls: 47,
  input_tokens: 160_110,
  output_tokens: 24_100,
  cost_eur: 0.17,
  wall_time_s: 118,
};
const USAGE_B = {
  llm_calls: 9,
  input_tokens: 18_930,
  output_tokens: 3_000,
  cost_eur: 0.04,
  wall_time_s: 47,
};

function run(
  id: string,
  variant: string,
  status: string,
  usage: object,
  project = PROJECT,
  created = "2026-11-25T14:01:00Z",
  error: string | null = null,
) {
  return {
    id,
    project_id: project,
    variant,
    status,
    usage,
    model_id: MODEL,
    runtime: "langgraph",
    created_at: created,
    started_at: created,
    finished_at: status === "running" ? null : "2026-11-25T14:03:40Z",
    created_by: SUB,
    error,
    kb_snapshot_id: "kb-2026-11-25-1284",
  };
}

export const RUNS = [
  run(RUN_A, "A", "running", USAGE_A),
  run(RUN_B, "B", "running", USAGE_B, PROJECT, "2026-11-25T14:01:01Z"),
  run(
    RUN_B_DONE,
    "B",
    "completed",
    { ...USAGE_B, cost_eur: 0.36, wall_time_s: 128 },
    PROJECT,
    "2026-11-24T10:00:00Z",
  ),
  run(
    RUN_A_DONE,
    "A",
    "completed",
    { ...USAGE_A, cost_eur: 1.02, wall_time_s: 351 },
    PROJECT,
    "2026-11-24T09:58:00Z",
  ),
  run(
    RUN_FAILED,
    "B",
    "failed",
    { cost_eur: 0, wall_time_s: 4 },
    PROJECT_2,
    "2026-11-20T08:00:00Z",
    "brak pliku .kicad_pcb",
  ),
];

const BOM_B = {
  run_id: RUN_B_DONE,
  version: 1,
  demo: false,
  bom: {
    schema_version: "1.0",
    design_name: "holter-c",
    variant: "B",
    items: ITEMS,
    findings: FINDINGS,
    ...RULES,
  },
};

// variant A of the same design differs on C12 and Y1 and missed the U7 finding
const BOM_A = {
  ...BOM_B,
  run_id: RUN_A_DONE,
  bom: {
    ...BOM_B.bom,
    variant: "A",
    items: ITEMS.map((i) =>
      i.refdes[0] === "C12"
        ? { ...i, mpn: "GRM188R61A475KE15D" }
        : i.refdes[0] === "R22"
          ? { ...i, value: "1 MΩ 5%" }
          : i,
    ).filter((i) => i.refdes[0] !== "Y1"),
    findings: FINDINGS.slice(1, 2),
  },
};

const TRACE_A = [{ node: "extract_group", duration_s: 62, llm_calls: 12 }];
const TRACE_B = [
  { node: "normalize_group", duration_s: 4, llm_calls: 0 },
  { node: "select_mpn", duration_s: 41, llm_calls: 9 },
];
const TRACE_DONE_B = [
  ...TRACE_B,
  { node: "validate", duration_s: 2, llm_calls: 0 },
  { node: "repair", duration_s: 3, llm_calls: 1 },
  { node: "assemble", duration_s: 1, llm_calls: 0 },
];

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

function sse(events: { event: string; data: unknown }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

export async function mockApi(page: Page, opts: { lang?: "pl" | "en" } = {}): Promise<void> {
  await page.addInitScript(
    ([sub, org, lang]) => {
      sessionStorage.setItem(
        "bomagent.session",
        JSON.stringify({
          token: "fixture",
          sub,
          email: "bartek@nordvital.example",
          name: "Bartek",
        }),
      );
      localStorage.setItem(`bomagent.org.${sub}`, JSON.stringify(org));
      localStorage.setItem("i18nextLng", lang);
    },
    [SUB, ORG, opts.lang ?? "pl"] as const,
  );
  await page.route("**/config.json", (r) => r.fulfill({ status: 404, body: "" }));
  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/v1/me")
      return json(route, {
        sub: SUB,
        email: "bartek@nordvital.example",
        name: "Bartek",
        organizations: [{ org_id: ORG, name: "Nordvital", slug: "nordvital", roles: ["owner"] }],
      });
    if (p === "/v1/usage")
      return json(route, {
        plan: "pilot",
        usage: { cost_eur: 24.8, projects: 7, members: 4, runs: 142 },
        limits: { llm_budget_eur_per_month: 40, projects: 20, members: 10 },
      });
    if (p === "/v1/models")
      return json(route, [
        {
          id: MODEL,
          provider: "mistral",
          residency: "eu",
          license_class: "closed",
          tier: "default",
        },
      ]);
    if (p === "/v1/projects")
      return json(route, {
        items: [
          {
            id: PROJECT,
            name: "Holter EKG 3-kan.",
            description: "rev C",
            is_sample: false,
            created_at: "2026-11-01T00:00:00Z",
            created_by: SUB,
          },
          {
            id: PROJECT_2,
            name: "Pulsoksymetr SP-2",
            description: "rev A",
            is_sample: false,
            created_at: "2026-10-01T00:00:00Z",
            created_by: SUB,
          },
          {
            id: PROJECT_3,
            name: "Wzmacniacz EEG-8",
            description: "rev B",
            is_sample: false,
            created_at: "2026-09-01T00:00:00Z",
            created_by: SUB,
          },
        ],
        next_cursor: null,
      });
    if (/^\/v1\/projects\/[^/]+\/files$/.test(p)) return json(route, []);
    if (p === `/v1/projects/${PROJECT}`)
      return json(route, {
        id: PROJECT,
        name: "Holter EKG 3-kan.",
        description: "rev C",
        is_sample: false,
        created_at: "2026-11-01T00:00:00Z",
        created_by: SUB,
      });
    if (p === "/v1/runs") {
      const project = url.searchParams.get("project_id");
      return json(route, {
        items: RUNS.filter((r) => !project || r.project_id === project),
        next_cursor: null,
      });
    }
    const runMatch = /^\/v1\/runs\/([^/]+)(\/.*)?$/.exec(p);
    if (runMatch) {
      const [, id, rest = ""] = runMatch;
      const r = RUNS.find((x) => x.id === id);
      if (!r) return json(route, { type: "about:blank", title: "Not found", status: 404 }, 404);
      if (rest === "") return json(route, r);
      if (rest === "/bom") return json(route, id === RUN_A_DONE ? BOM_A : { ...BOM_B, run_id: id });
      if (rest === "/trace")
        return json(route, id === RUN_A ? TRACE_A : id === RUN_B ? TRACE_B : TRACE_DONE_B);
      if (rest === "/events") {
        const step = id === RUN_A ? "extract_group" : "select_mpn";
        // the stream stays open while the run is live: the last event is not "end"
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: sse([
            {
              event: "progress",
              data: { status: "running", usage: r.usage, steps: id === RUN_A ? 2 : 3, step },
            },
          ]),
        });
      }
      if (rest === "/bom/versions")
        return json(route, [
          {
            version: 1,
            created_at: "2026-11-24T10:02:00Z",
            created_by: SUB,
            findings: 3,
            lines: 12,
            parent_version: null,
            reason: "",
          },
        ]);
      return json(route, []);
    }
    if (p.startsWith("/v1/kb")) return json(route, { items: [], next_cursor: null });
    return json(route, { items: [], next_cursor: null });
  });
}
