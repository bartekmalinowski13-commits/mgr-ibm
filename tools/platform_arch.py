# Generuje SVG architektury produkcyjnej platformy (AWS, UE, multi-tenant)
import html, sys

W, H = 1730, 970
C = {
    "ext": ("#f4f4f5", "#52525b"), "edge": ("#eef2ff", "#3730a3"), "svc": ("#ffffff", "#15212b"),
    "llm": ("#f3efff", "#6d28d9"), "det": ("#e8f5f2", "#0f766e"), "data": ("#fff6e0", "#b45309"),
    "obs": ("#ecfeff", "#0e7490"), "sec": ("#fef2f2", "#b91c1c"),
}
o = []
a = o.append
e = html.escape

def box(x, y, w, h, kind, title, lines=(), tag=None):
    f, s = C[kind]
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
    a(f'<text x="{x+12}" y="{y+24}" class="t" fill="{s}">{e(title)}</text>')
    for i, l in enumerate(lines):
        a(f'<text x="{x+12}" y="{y+43+i*15}" class="s">{e(l)}</text>')
    if tag:
        tw = 10 + 6.6 * len(tag)
        a(f'<rect x="{x+w-tw-8}" y="{y+9}" width="{tw}" height="16" rx="8" fill="{s}"/>')
        a(f'<text x="{x+w-tw/2-8}" y="{y+21}" class="tag" text-anchor="middle">{e(tag)}</text>')

def line(pts, arrow=True, dash=False, color="#334155", label=None, lx=0, ly=0, both=False):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    extra = (' stroke-dasharray="5 4"' if dash else "") + (' marker-end="url(#ah)"' if arrow else "") + (' marker-start="url(#ah)"' if both else "")
    a(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{extra}/>')
    if label:
        a(f'<text x="{lx}" y="{ly}" class="al">{e(label)}</text>')

def frame(x, y, w, h, label, color, fill="none"):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{color}" stroke-dasharray="6 5" stroke-width="1.3"/>')
    a(f'<text x="{x+14}" y="{y+h-10}" class="fl" fill="{color}">{e(label)}</text>')

a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, Arial, sans-serif">')
a('''<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#334155"/></marker>
<style>.t{font-size:13.5px;font-weight:700}.s{font-size:11.2px;fill:#334155}.tag{font-size:9.5px;font-weight:700;fill:#fff}
.al{font-size:10.5px;fill:#475569;font-style:italic}.fl{font-size:12px;font-weight:700}.h1{font-size:20px;font-weight:800;fill:#0f172a}.h2{font-size:12.5px;fill:#475569}</style></defs>''')
a(f'<rect width="{W}" height="{H}" fill="#fff"/>')
a('<text x="30" y="36" class="h1">BOM Agent – architektura produkcyjna (SaaS, multi-tenant, UE)</text>')
a('<text x="30" y="58" class="h2">Modułowe serwisy na ECS Fargate, izolacja tenantów na każdej warstwie, wszystkie wywołania LLM przez gateway z politykami UE. Szczegóły: docs/platform/ARCHITECTURE.md, docs/adr/.</text>')

# external
box(300, 78, 200, 60, "ext", "IdP klienta (SAML / OIDC)", ["Entra ID, Okta, Google"])
box(520, 78, 200, 60, "ext", "Użytkownicy organizacji", ["przeglądarka, API (klucze API)"])
box(970, 78, 250, 60, "ext", "GitHub Actions", ["CI/CD, OIDC do AWS, bez kluczy"])

frame(280, 160, 1200, 745, "AWS eu-central-1 · konto prod (AWS Organizations: dev / staging / prod · SCP: tylko regiony UE)", "#475569")
# edge
box(300, 200, 200, 62, "edge", "Amazon Cognito", ["SSO per organizacja, MFA"])
box(520, 200, 200, 62, "edge", "CloudFront + AWS WAF", ["TLS, rate limiting"])
box(740, 200, 200, 62, "edge", "S3 – SPA (apps/web)", ["React, Vite, shadcn/ui"])
box(970, 200, 250, 62, "edge", "ECR", ["obrazy podpisane (cosign) + SBOM"])
line([(400, 138), (400, 198)])
line([(620, 138), (620, 198)])
line([(1095, 138), (1095, 198)])
line([(720, 231), (738, 231)])

frame(290, 285, 1180, 478, "VPC – podsieci prywatne, VPC endpoints, egress przez allowlistę", "#15212b")
line([(560, 262), (560, 300), (470, 300), (470, 328)])
line([(360, 262), (360, 328)], dash=True, label="JWT", lx=330, ly=300)

# services
box(310, 330, 200, 112, "svc", "services/api", ["FastAPI · OpenAPI 3.1 · SSE", "moduły: tenancy, identity,", "projects, runs, bom, kb-admin,", "audit, metering"], tag="ECS")
box(530, 330, 200, 112, "det", "ingest-worker", ["parsery: KiCad, Altium, Cadence,", "IPC-2581, ODB++, PDF, DXF/DWG", "sandbox: bez sieci, read-only,", "skan malware przed parsowaniem"], tag="ECS")
box(750, 330, 200, 112, "det", "kb-indexer", ["Docling, chunking,", "embeddingi, zakres", "global / tenant"], tag="ECS")
box(970, 330, 250, 112, "llm", "agent-worker", ["wariant A: 100% LLM", "wariant B: hybryda (reguły + LLM)", "LangGraph + Claude Agent SDK", "fan-out, budżety, checkpointy"], tag="ECS")
box(1250, 330, 200, 112, "llm", "llm-gateway (LiteLLM)", ["katalog: closed / open-weight", "polityka rezydencji UE", "budżety i limity per tenant"], tag="ECS")
line([(1220, 386), (1248, 386)])
line([(850, 330), (850, 314), (1350, 314), (1350, 328)], label="embeddingi", lx=1000, ly=309)

# tenant bus
a('<rect x="310" y="460" width="910" height="30" rx="6" fill="#f8fafc" stroke="#94a3b8"/>')
a('<text x="765" y="480" class="s" text-anchor="middle">kontekst tenanta: JWT → TenantContext → SET LOCAL app.tenant_id (Postgres RLS) · prefiks S3 per tenant (ABAC) · tenant_id w każdej wiadomości</text>')
for cx in (410, 630, 850, 1095):
    line([(cx, 442), (cx, 458)], both=True)
for cx in (410, 630, 850, 1095):
    line([(cx, 490), (cx, 508)], both=True)

# data
box(310, 510, 200, 92, "data", "Amazon SQS", ["kolejki: ingest, kb, runs", "+ DLQ, autoskalowanie", "workerów po głębokości"])
box(530, 510, 200, 92, "data", "Aurora PostgreSQL 16", ["Serverless v2, pgvector", "RLS na tabelach tenanta", "silo dla planu Enterprise"])
box(750, 510, 200, 92, "data", "Amazon S3", ["pliki klientów, artefakty,", "eksporty · SSE-KMS", "CMK per tenant (Enterprise)"])
box(970, 510, 118, 92, "data", "EventBridge", ["zdarzenia", "domenowe"])
box(1102, 510, 118, 92, "data", "Audyt", ["S3 Object Lock,", "hash chain"])
line([(1088, 556), (1100, 556)])
box(1250, 510, 200, 92, "llm", "model-serving (vLLM)", ["open-weight na GPU", "ECS na EC2, opcjonalnie"])
line([(1350, 442), (1350, 508)])

# observability
box(310, 630, 200, 100, "obs", "OTel Collector (ADOT)", ["OTLP z każdego serwisu", "→ Prometheus, CloudWatch", "tenant_id w atrybutach"])
box(530, 630, 200, 100, "obs", "Prometheus + Grafana", ["Amazon Managed Service", "for Prometheus / Grafana", "SLO, alarmy → SNS"])
box(750, 630, 200, 100, "obs", "CloudWatch / X-Ray", ["logi JSON (structlog)", "bez treści plików klienta"])
box(970, 630, 250, 100, "obs", "Langfuse (self-hosted)", ["ślady LLM: prompty, koszty,", "opóźnienia – metryki do pracy"])
line([(510, 680), (528, 680)])

# security
box(300, 780, 200, 90, "sec", "AWS KMS + Secrets Mgr", ["szyfrowanie w spoczynku", "rotacja sekretów"])
box(520, 780, 200, 90, "sec", "GuardDuty", ["+ Malware Protection S3", "+ Runtime Monitoring ECS"])
box(740, 780, 200, 90, "sec", "Security Hub + Config", ["AWS FSBP, CIS", "conformance packs"])
box(960, 780, 260, 90, "sec", "CloudTrail organizacji", ["→ konto log-archive", "(Object Lock)"])
box(1240, 780, 220, 90, "sec", "AWS Backup", ["kopie do eu-west-1", "(drugi region UE)"])

# providers
a('<text x="1500" y="300" class="fl" fill="#6d28d9">Dostawcy LLM – przetwarzanie w UE</text>')
box(1500, 330, 210, 62, "llm", "Amazon Bedrock", ["profil EU: Claude, open-weight"])
box(1500, 410, 210, 62, "llm", "Azure OpenAI", ["Data Zone Standard (EU)"])
box(1500, 490, 210, 62, "llm", "Mistral (UE)", ["La Plateforme"])
line([(1450, 386), (1480, 386)], arrow=False)
line([(1480, 361), (1480, 521)], arrow=False)
for y in (361, 441, 521):
    line([(1480, y), (1498, y)])
a('<text x="1500" y="580" class="s">dev lokalnie: Ollama</text>')
a('<text x="1500" y="597" class="s">CI: fałszywy dostawca (nagrania)</text>')

# legend
ly = 925
items = [("llm", "LLM / agenci"), ("det", "przetwarzanie deterministyczne"), ("svc", "API"), ("data", "dane"), ("obs", "obserwowalność"), ("sec", "bezpieczeństwo")]
x = 30
for k, t in items:
    f, s = C[k]
    a(f'<rect x="{x}" y="{ly}" width="20" height="16" rx="4" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
    a(f'<text x="{x+28}" y="{ly+12}" class="s">{e(t)}</text>')
    x += 230
a('</svg>')
open(sys.argv[1], "w").write("\n".join(o))
