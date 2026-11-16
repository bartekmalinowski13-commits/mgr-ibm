// k6 load scenarios for the local compose stack with the fake LLM (OPS-09).
//
//   just up-core && k6 run tests/load/bomagent.js
//   k6 run -e BASE_URL=http://localhost:8000 -e PROFILE=load tests/load/bomagent.js
//
// Local mock IdP only (BOMAGENT_AUTH_MODE=local); the script talks to BASE_URL and nothing else.
// The thresholds are PLACEHOLDERS until a first measured run (docs/platform/runbooks/capacity-k6.md).
// PROFILE=smoke (default) is a few seconds of traffic for checking the script; PROFILE=load
// is the longer profile for the nightly run.
import { check, sleep } from "k6";
import http from "k6/http";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const PROFILE = __ENV.PROFILE || "smoke";
const FIXTURE = "../../evals/fixtures/kicad/ecg-frontend/";
const FILES = [
  "ecg-frontend.kicad_pro",
  "ecg-frontend.kicad_sch",
  "afe.kicad_sch",
  "power.kicad_sch",
];
const BLOBS = FILES.map((name) => ({ name, data: open(FIXTURE + name, "b") }));

const p =
  PROFILE === "load"
    ? { dur: "5m", readRate: 50, uploadRate: 2, runRate: 1, vus: 50 }
    : { dur: "10s", readRate: 5, uploadRate: 1, runRate: 1, vus: 10 };

const scenario = (exec, rate) => ({
  executor: "constant-arrival-rate",
  exec,
  rate,
  timeUnit: "1s",
  duration: p.dur,
  preAllocatedVUs: p.vus,
  maxVUs: p.vus * 2,
});

export const options = {
  scenarios: {
    bom_read: scenario("bomRead", p.readRate),
    upload: scenario("upload", p.uploadRate),
    run_and_sse: scenario("runAndSse", p.runRate),
  },
  // placeholders - tighten after measuring
  thresholds: {
    "http_req_failed{kind:read}": ["rate<0.01"],
    "http_req_duration{kind:read}": ["p(95)<1000"],
    "http_req_duration{kind:upload}": ["p(95)<5000"],
    "http_req_duration{kind:run_create}": ["p(95)<2000"],
    checks: ["rate>0.99"],
  },
};

const auth = (token, org, extra = {}, tags = {}) => ({
  headers: Object.assign({ Authorization: `Bearer ${token}`, "X-Org-Id": org }, extra),
  tags,
});
const jsonHeaders = { "Content-Type": "application/json" };

function uploadAll(token, org, projectId) {
  for (const b of BLOBS) {
    const r = http.post(
      `${BASE}/v1/projects/${projectId}/files`,
      { file: http.file(b.data, b.name) },
      auth(token, org, {}, { kind: "upload" }),
    );
    check(r, { "file accepted": (x) => x.status === 201 });
  }
}

function waitFor(url, token, org, done, seconds) {
  for (let i = 0; i < seconds * 4; i++) {
    const r = http.get(url, auth(token, org));
    if (r.status === 200 && done(r.json())) return true;
    sleep(0.25);
  }
  return false;
}

function newProject(token, org, name) {
  const r = http.post(
    `${BASE}/v1/projects`,
    JSON.stringify({ name }),
    auth(token, org, jsonHeaders),
  );
  check(r, { "project created": (x) => x.status === 201 });
  return r.json("id");
}

export function setup() {
  const tag = Date.now().toString(36);
  const t = http.post(
    `${BASE}/v1/dev/token`,
    JSON.stringify({ sub: `dev-k6-${tag}`, email: `k6-${tag}@load.example`, name: "k6" }),
    { headers: jsonHeaders },
  );
  check(t, { "mock IdP token": (x) => x.status === 200 });
  const token = t.json("access_token");
  const o = http.post(
    `${BASE}/v1/organizations`,
    JSON.stringify({ name: `k6 ${tag}`, slug: `k6-${tag}` }),
    { headers: Object.assign({ Authorization: `Bearer ${token}` }, jsonHeaders) },
  );
  check(o, { "organisation created": (x) => x.status === 201 });
  const org = o.json("id");

  const project = newProject(token, org, "k6 baseline");
  uploadAll(token, org, project);
  const parsed = waitFor(
    `${BASE}/v1/projects/${project}/files`,
    token,
    org,
    (files) => files.length === BLOBS.length && files.every((f) => f.status === "parsed"),
    120,
  );
  const run = http.post(
    `${BASE}/v1/runs`,
    JSON.stringify({ project_id: project, variant: "B" }),
    auth(token, org, jsonHeaders),
  );
  const runId = run.json("id");
  const finished =
    parsed &&
    waitFor(
      `${BASE}/v1/runs/${runId}`,
      token,
      org,
      (r) => r.status === "completed" || r.status === "failed",
      120,
    );
  check(null, { "baseline run finished": () => finished === true });
  return { token, org, project, runId };
}

export function bomRead(d) {
  const r = http.get(`${BASE}/v1/runs/${d.runId}/bom`, auth(d.token, d.org, {}, { kind: "read" }));
  check(r, { "bom 200": (x) => x.status === 200 });
}

export function upload(d) {
  const project = newProject(d.token, d.org, `k6 upload ${__VU}-${__ITER}`);
  uploadAll(d.token, d.org, project);
}

export function runAndSse(d) {
  const r = http.post(
    `${BASE}/v1/runs`,
    JSON.stringify({ project_id: d.project, variant: "B" }),
    auth(
      d.token,
      d.org,
      Object.assign({ "Idempotency-Key": `k6-${__VU}-${__ITER}-${Date.now()}` }, jsonHeaders),
      { kind: "run_create" },
    ),
  );
  if (!check(r, { "run accepted": (x) => x.status === 202 })) return;
  // the stream ends when the run does; k6 buffers the body, so this is time to completion
  const sse = http.get(`${BASE}/v1/runs/${r.json("id")}/events`, {
    ...auth(d.token, d.org, {}, { kind: "sse" }),
    timeout: "120s",
  });
  check(sse, {
    "sse 200": (x) => x.status === 200,
    "sse delivered events": (x) => String(x.body).includes("data:"),
  });
}
