"""Daily audit chain anchors in write-once storage (audit SEC-04, ADR-0011)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from bomagent_common.audit import ChainAnchor
from bomagent_common.audit_anchor import (
    AnchorSink,
    FileAnchorSink,
    S3AnchorSink,
    anchor_key,
    parse_anchor,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
DAY = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)


def test_key_layout_is_per_tenant_and_per_day():
    assert anchor_key(TENANT, DAY) == f"audit-anchors/{TENANT}/2026-11-16.json"


def test_parse_anchor_accepts_only_well_formed_documents():
    good = json.dumps({"tenant": str(TENANT), "seq": 7, "hash": "ab" * 32, "at": "x"}).encode()
    assert parse_anchor(good, TENANT) == ChainAnchor(7, "ab" * 32)
    for bad in (
        b"not json",
        json.dumps(
            {"tenant": str(uuid.uuid4()), "seq": 7, "hash": "ab" * 32}
        ).encode(),  # other tenant
        json.dumps({"tenant": str(TENANT), "seq": "7", "hash": "ab" * 32}).encode(),
        json.dumps({"tenant": str(TENANT), "seq": 7}).encode(),
        json.dumps([1, 2]).encode(),
    ):
        assert parse_anchor(bad, TENANT) is None


async def _contract(sink: AnchorSink) -> None:
    key = anchor_key(TENANT, DAY)
    assert await sink.write_once(key, b'{"first": true}') is True
    assert await sink.write_once(key, b'{"second": true}') is False  # never overwritten
    assert await sink.read(key) == b'{"first": true}'
    other = anchor_key(TENANT, datetime(2026, 11, 17, tzinfo=UTC))
    await sink.write_once(other, b"{}")
    elsewhere = anchor_key(uuid.uuid4(), DAY)
    await sink.write_once(elsewhere, b"{}")
    listed = await sink.list(f"audit-anchors/{TENANT}/")
    assert listed == [key, other]  # only this tenant, oldest first


async def test_file_sink_contract(tmp_path):
    await _contract(FileAnchorSink(tmp_path))


async def test_file_sink_refuses_path_traversal(tmp_path):
    sink = FileAnchorSink(tmp_path)
    for bad in ("../x.json", "/etc/passwd", "audit-anchors/../../x"):
        with pytest.raises(ValueError, match="not an anchor key"):
            await sink.write_once(bad, b"x")


async def test_s3_sink_contract_with_moto(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="eu-central-1").create_bucket(
            Bucket="anchors", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
        )
        await _contract(S3AnchorSink("anchors", region="eu-central-1"))
