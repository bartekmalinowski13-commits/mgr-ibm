"""JSON Schema of the BOM (thesis appendix B; contract for structured LLM output)."""

from __future__ import annotations

import json
from typing import Any

from bomagent_bom.model import BomItem, BomVersion


def bom_json_schema() -> dict[str, Any]:
    schema = BomVersion.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://bomagent.eu/schemas/bom/1.0.0"
    return schema


def bom_item_json_schema() -> dict[str, Any]:
    schema = BomItem.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def dump(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.stdout.write(dump(bom_json_schema()))
