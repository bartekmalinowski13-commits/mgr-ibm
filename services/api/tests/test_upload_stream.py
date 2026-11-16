"""Uploads are measured and hashed in chunks: the API never holds the whole file (SEC-13)."""

from __future__ import annotations

import hashlib
import io

import pytest
from starlette.datastructures import UploadFile

from bomagent_api.routers.projects import MAX_UPLOAD, measure_upload
from bomagent_common.problems import ProblemError


def _upload(data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename="a.bin")


async def test_measure_returns_size_and_sha256_and_rewinds():
    data = b"hello world" * 1000
    up = _upload(data)
    size, digest = await measure_upload(up, limit=10_000_000)
    assert size == len(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert await up.read() == data  # rewound for the store


async def test_measure_reads_in_bounded_chunks():
    reads: list[int] = []

    class Spy(io.BytesIO):
        def read(self, n: int | None = -1) -> bytes:
            reads.append(-1 if n is None else n)
            return super().read(n)

    up = UploadFile(Spy(b"x" * 5_000_000), filename="a.bin")
    await measure_upload(up, limit=10_000_000)
    assert reads
    assert all(0 < n <= 1024 * 1024 for n in reads)


async def test_measure_refuses_files_over_the_limit_without_reading_everything():
    consumed = 0

    class Spy(io.BytesIO):
        def read(self, n: int | None = -1) -> bytes:
            nonlocal consumed
            chunk = super().read(n)
            consumed += len(chunk)
            return chunk

    up = UploadFile(Spy(b"x" * 10_000_000), filename="a.bin")
    with pytest.raises(ProblemError) as err:
        await measure_upload(up, limit=2_000_000)
    assert err.value.problem.status == 413
    assert err.value.problem.type.endswith("/file-too-large")
    assert consumed <= 2_000_000 + 1024 * 1024  # stopped within one chunk of the limit


async def test_limit_is_inclusive():
    up = _upload(b"x" * 100)
    assert (await measure_upload(up, limit=100))[0] == 100
    with pytest.raises(ProblemError):
        await measure_upload(_upload(b"x" * 101), limit=100)


def test_the_documented_limit_is_unchanged():
    assert MAX_UPLOAD == 64 * 1024 * 1024
