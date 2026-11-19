"""SQLAlchemy Core definitions of the tables the repositories query.

They are *query metadata only* (the schema is owned by ``bomagent_migrations``; nothing here
creates or alters a table). Using them gives column names that are checked when a statement
is built instead of when it runs, and removes the need for f-string column lists.
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
_TS = DateTime(timezone=True)

tenants = Table(
    "tenants",
    metadata,
    Column("id", Uuid),
    Column("slug", Text),
    Column("name", Text),
    Column("plan", Text),
    schema="tenancy",
)
memberships = Table(
    "memberships",
    metadata,
    Column("tenant_id", Uuid),
    Column("user_sub", Text),
    Column("email", Text),
    Column("display_name", Text),
    Column("roles", ARRAY(Text)),
    Column("status", Text),
    Column("created_at", _TS),
    schema="tenancy",
)
invitations = Table(
    "invitations",
    metadata,
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("email", Text),
    Column("roles", ARRAY(Text)),
    Column("token_hash", Text),
    Column("status", Text),
    Column("invited_by", Text),
    Column("accepted_by", Text),
    Column("created_at", _TS),
    Column("expires_at", _TS),
    Column("accepted_at", _TS),
    schema="tenancy",
)
projects = Table(
    "projects",
    metadata,
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("name", Text),
    Column("description", Text),
    Column("sample_key", Text),
    Column("created_by", Text),
    Column("created_at", _TS),
    schema="projects",
)
files = Table(
    "files",
    metadata,
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("project_id", Uuid),
    Column("name", Text),
    Column("object_key", Text),
    Column("sha256", Text),
    Column("size_bytes", BigInteger),
    Column("status", Text),
    Column("detected_format", Text),
    Column("summary", JSONB),
    Column("created_by", Text),
    Column("created_at", _TS),
    schema="projects",
)
runs = Table(
    "runs",
    metadata,
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("project_id", Uuid),
    Column("variant", Text),
    Column("runtime", Text),
    Column("model_id", Text),
    Column("status", Text),
    Column("requirements", JSONB),
    Column("kb_snapshot_id", Text),
    Column("usage", JSONB),
    Column("trace", JSONB),
    Column("error", Text),
    Column("created_by", Text),
    Column("created_at", _TS),
    Column("started_at", _TS),
    Column("finished_at", _TS),
    schema="runs",
)
bom_versions = Table(
    "versions",
    metadata,
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("run_id", Uuid),
    Column("version", Integer),
    Column("parent_id", Uuid),
    Column("content", JSONB),
    Column("reason", Text),
    Column("created_by", Text),
    Column("created_at", _TS),
    schema="bom",
)
kb_documents = Table(
    "documents",
    metadata,
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("scope", Text),
    Column("title", Text),
    Column("kind", Text),
    Column("manufacturer", Text),
    Column("status", Text),
    Column("error", Text),
    Column("size_bytes", BigInteger),
    Column("sha256", Text),
    Column("superseded_at", _TS),
    Column("created_at", _TS),
    Column("indexed_at", _TS),
    schema="kb",
)
kb_chunks = Table(
    "chunks",
    metadata,
    Column("id", Uuid),
    Column("document_id", Uuid),
    schema="kb",
)
