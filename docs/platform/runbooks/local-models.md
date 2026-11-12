# Runbook: local open-weight models on an Apple-silicon Mac (Ollama)

For learning and experiments: `bomagent run`, `bomagent experiment run` and the local demo
(`just demo`). **Not for the Fly pilot**: a Fly machine cannot reach your laptop without a
tunnel (and a tunnel would expose your machine), and local models are never served by the EU
gateway (`residency: local` entries are skipped by `bomagent_llm.gateway_config`). The
hosted/pilot path is [llm-gateway-pilot.md](llm-gateway-pilot.md). Nothing leaves your Mac.

## 1. Install and pull

```bash
brew install ollama
brew services start ollama          # or: ollama serve (foreground)
ollama pull qwen3:8b                # pick one or more, see the table
ollama run qwen3:8b "say hi"        # sanity check, exit with /bye
curl -s http://localhost:11434/v1/models | head   # OpenAI-compatible API used by the CLI
```

## 2. Enable the catalogue entry locally (no edit of models.yaml)

`models.yaml` keeps every non-fake entry at `enabled: false, verified: false`. For local
models use an override file outside the repository (or untracked):

```bash
mkdir -p ~/.config/bomagent
printf 'enable:\n  - ollama-qwen3-8b\n' > ~/.config/bomagent/catalog-override.yaml
export BOMAGENT_CATALOG_OVERRIDE=~/.config/bomagent/catalog-override.yaml
```

The override can only switch on entries with `residency: local`; naming a hosted entry
(Bedrock, Azure, Mistral) or an unknown id is an error. Disabled/unverified entries are
refused by `Catalog.get`; enabled local ones are refused when the caller passes
`allow_local=False` - the API does that unless `allow_local_models` is true (local/test
environments, or the fake provider in the pilot), so a local model can never be selected in
a gateway-backed deployment.

## 3. Run against Ollama

Ollama's OpenAI-compatible endpoint is used through the same client as the gateway; the key
is ignored by Ollama but must be non-empty:

```bash
export BOMAGENT_LLM_GATEWAY_URL=http://localhost:11434
export BOMAGENT_LLM_GATEWAY_KEY=ollama
uv run bomagent run evals/fixtures/<design-folder> --variant B --model ollama-qwen3-8b --out /tmp/bom.json
uv run bomagent experiment run <config.yaml>     # list the ollama-* ids under `models:`
```

Small models follow the JSON schema less reliably than hosted ones: expect more retries and
failed structured outputs, which is itself a useful data point for the experiment (record
the model id and Ollama version next to the results).

## 4. Sizing (Apple silicon, unified memory)

Download sizes are from the Ollama library pages (checked 2026-11-12); RAM adds roughly 2-4 GB
for the KV cache at the default context. Leave 6-8 GB for macOS and your tools.

| Catalogue id | Ollama tag | Download | Approx. RAM | 16 GB | 32 GB | 64 GB |
|---|---|---|---|---|---|---|
| `ollama-ministral-3-8b` | `ministral-3:8b` | 6.0 GB | 9 GB | yes | yes | yes |
| `ollama-qwen3-8b` | `qwen3:8b` | 5.2 GB | 8 GB | yes | yes | yes |
| `ollama-llama3-1-8b` | `llama3.1:8b` | 4.9 GB | 8 GB | yes | yes | yes |
| `ollama-qwen3-14b` | `qwen3:14b` | 9.3 GB | 12 GB | tight (close other apps) | yes | yes |
| `ollama-gpt-oss-20b` | `gpt-oss:20b` | 14 GB | 16 GB | no | yes | yes |
| `ollama-mistral-small` | `mistral-small:24b` | 14 GB | 18 GB | no | yes | yes |

Bigger variants (e.g. `gpt-oss:120b`, 65 GB) are not in the catalogue. Check the real
numbers with `ollama ps` after a first request.

## 5. Back to normal

`unset BOMAGENT_CATALOG_OVERRIDE BOMAGENT_LLM_GATEWAY_URL BOMAGENT_LLM_GATEWAY_KEY` and the
CLI uses the fake provider again (`--model fake-closed`).
