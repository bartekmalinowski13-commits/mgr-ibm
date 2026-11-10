from __future__ import annotations

import httpx

from bomagent_agents.fake_server import create_app
from bomagent_agents.prompts import load_prompt
from bomagent_llm.catalog import load_catalog
from bomagent_llm.chat import ChatRequest, GatewayChat, Message
from bomagent_llm.embeddings import GatewayEmbeddings


async def test_gateway_clients_work_against_fake_server():
    transport = httpx.ASGITransport(app=create_app())
    client = httpx.AsyncClient(transport=transport, base_url="http://fake")
    assert (await client.get("/healthz")).json()["status"] == "ok"
    chat = GatewayChat("http://fake", "k", client=client)
    request = ChatRequest(
        prompt_id="validate",
        prompt_version="1",
        model=load_catalog().get("fake-closed"),
        messages=[
            Message("system", load_prompt("validate").text),
            Message(
                "user",
                '<data name="input">\n'
                '{"lines": [{"refdes": ["R1"], '
                '"footprint": "", "mpn": ""}]}\n'
                "</data>",
            ),
        ],
        schema_name="ValidationOut",
        json_schema={},
        metadata={},  # prompt identified by its text
    )
    result = await chat.complete(request)
    assert {f["field"] for f in result.data["findings"]} == {"footprint", "mpn"}
    assert result.usage.input_tokens > 0
    emb = GatewayEmbeddings("http://fake", "k", "fake-embedding", client=client)
    (vec,) = await emb.embed(["10k resistor"])
    assert len(vec) == 1024
