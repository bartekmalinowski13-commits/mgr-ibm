from __future__ import annotations

import math

import httpx
import pytest

from bomagent_llm.catalog import LicenseClass, ModelNotAllowedError, load_catalog
from bomagent_llm.embeddings import GatewayEmbeddings, HashingEmbeddings


def test_catalogue_is_eu_only_and_real_models_start_disabled():
    cat = load_catalog()
    assert {m.residency for m in cat.models} <= {"eu-region", "eu-geo", "local"}
    for m in cat.models:
        if m.provider not in {"fake"}:
            assert not (m.enabled and m.verified), f"{m.id} must be verified by a human first"
    assert {m.license_class for m in cat.models} == {LicenseClass.CLOSED, LicenseClass.OPEN_WEIGHT}


def test_get_and_enabled_filters():
    cat = load_catalog()
    assert cat.get("fake-closed").license_class == LicenseClass.CLOSED
    assert cat.get("fake-open-weight").license_class == LicenseClass.OPEN_WEIGHT
    with pytest.raises(ModelNotAllowedError, match="unverified"):
        cat.get("claude-opus-eu")
    with pytest.raises(ModelNotAllowedError, match="not in the catalogue"):
        cat.get("gpt-global")
    with pytest.raises(ModelNotAllowedError, match="local development"):
        cat.get("fake-closed", allow_local=False)
    assert [m.id for m in cat.enabled("embedding")] == ["fake-embedding"]


def test_cost():
    spec = load_catalog().models[0].model_copy(update={"cost_in_eur": 2.0, "cost_out_eur": 10.0})
    assert spec.cost(1_000_000, 100_000) == pytest.approx(3.0)


def test_catalogue_from_path(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "models:\n  - {id: x, gateway_model: x, provider: fake, license_class: closed,"
        " residency: local, enabled: true, verified: true}\n"
    )
    assert load_catalog(p).get("x").id == "x"
    p.write_text(
        "models:\n  - {id: y, gateway_model: y, provider: openai, license_class: closed,"
        " residency: us}\n"
    )
    with pytest.raises(ValueError, match="residency"):
        load_catalog(p)


async def test_hashing_embeddings_are_deterministic_normalised_and_lexical():
    emb = HashingEmbeddings(dimensions=256)
    a, b, c = await emb.embed(
        ["10 kΩ 0603 thick film resistor", "thick film chip resistor 0603 10 kΩ", "LDO regulator"]
    )
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert a == (await emb.embed(["10 kΩ 0603 thick film resistor"]))[0]

    def cos(u, v):
        return sum(x * y for x, y in zip(u, v, strict=True))

    assert cos(a, b) > cos(a, c)


async def test_gateway_embeddings_batches_and_orders():
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer k"
        calls.append(body["input"])
        data = [
            {"index": i, "embedding": [float(len(t))] * 4}
            for i, t in reversed(list(enumerate(body["input"])))
        ]
        return httpx.Response(200, json={"data": data})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gw")
    emb = GatewayEmbeddings(
        "http://gw", "k", "fake-embedding", dimensions=4, batch_size=2, client=client
    )
    vectors = await emb.embed(["a", "bb", "ccc"])
    assert calls == [["a", "bb"], ["ccc"]]
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]
    await emb.aclose()


async def test_gateway_embeddings_rejects_wrong_dimensions():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
        ),
        base_url="http://gw",
    )
    emb = GatewayEmbeddings("http://gw", "k", "m", dimensions=4, client=client)
    with pytest.raises(ValueError, match="size 4"):
        await emb.embed(["x"])
