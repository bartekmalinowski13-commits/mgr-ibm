"""Use cases of the API (ARCH-04), between ``routers`` and ``repositories``.

A service owns the transaction (``tenant_transaction``), the business rules (quota, state
checks, 404/409 decisions), the audit event and the outbox message of one use case. It takes
explicit collaborators (engine, object store, queues, KB) and never sees a ``Request``; the
routers translate HTTP to these calls and back.
"""
