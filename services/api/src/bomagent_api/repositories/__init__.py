"""Persistence layer: the SQL of the API (ARCH-04), below ``services``.

Repositories take an open, tenant-scoped ``AsyncConnection`` (RLS does the isolation), never
open transactions themselves and hold no business rules: they return rows or ``None`` and the
services decide what that means (404, 409, quota, audit, outbox).
"""
