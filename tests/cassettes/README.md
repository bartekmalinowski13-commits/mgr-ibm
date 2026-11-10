# Cassettes of the fake LLM provider

Recorded `ChatResponse` bodies named `<sha256 of the request>.json` (see `bomagent_llm.fake.request_key`).
Record with `bomagent run ... --record tests/cassettes` against a real model through the gateway; CI only replays.
