"""Deterministic stand-in for a model in CI and local runs (TESTING.md: fake provider).

It reads the structured ``input`` block a runtime sends and answers the way a careful
model would on easy inputs: it picks an MPN only from the evidence candidates, groups
identical parts, reports missing data. It exists to exercise plumbing (graphs, budgets,
provenance, persistence) - **not** to produce thesis results; those use real models
through the gateway.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

from bomagent_bom.grouping import group_components
from bomagent_bom.model import Component, ParsedDesign
from bomagent_bom.packages import package_from_part_number
from bomagent_bom.values import normalize_value
from bomagent_llm.chat import ChatRequest

_BLOCK = re.compile(r'<data name="(?P<name>[a-z]+)">\n(?P<body>.*?)\n</data>', re.S)
MANUFACTURERS = {
    "yageo": "Yageo",
    "murata": "Murata",
    "samsung": "Samsung Electro-Mechanics",
    "adi": "Analog Devices",
    "ti": "Texas Instruments",
    "microchip": "Microchip",
    "nexperia": "Nexperia",
    "liteon": "Lite-On",
    "maxim": "Analog Devices",
    "molex": "Molex",
    "jst": "JST",
}


def _blocks(request: ChatRequest) -> dict[str, Any]:
    text = request.messages[-1].content
    return {m["name"]: json.loads(m["body"]) for m in _BLOCK.finditer(text)}


def _value_tokens(line: dict[str, Any]) -> list[str]:
    value = str(line.get("value", ""))
    norm = normalize_value(value, line.get("kind")) or value
    tokens = [norm.replace("µ", "u"), norm]
    if norm.endswith(" nF"):  # 100 nF is often written 0.1 µF
        with contextlib.suppress(ValueError):
            tokens.append(f"{float(norm.split()[0]) / 1000:g} µF")
    return [t for t in tokens if t]


def _mpn_select(data: dict[str, Any]) -> dict[str, Any]:
    line = data["input"]["line"]
    best: tuple[int, dict[str, Any]] | None = None
    for cand in data["input"].get("candidates", []):
        context = cand["context"]
        score = 0
        if any(t and t in context for t in _value_tokens(line)):
            score += 2
        if line.get("value") and str(line["value"]).upper() in cand["mpn"].upper():
            score += 3
        pkg = line.get("package")
        if pkg and (package_from_part_number(cand["mpn"]) == pkg or pkg in context):
            score += 1
        if score >= 2 and (best is None or score > best[0]):
            best = (score, cand)
    if best is None:
        return {
            "mpn": "",
            "manufacturer": "",
            "confidence": 0.0,
            "rationale": "no candidate in the evidence matches value and package",
        }
    cand = best[1]
    vendor = MANUFACTURERS.get(cand["document"].split("-")[0], "")
    return {
        "mpn": cand["mpn"],
        "manufacturer": vendor,
        "confidence": min(1.0, best[0] / 4),
        "rationale": f"matches: {cand['context'][:120]}",
        "citation_chunk_ids": [cand["chunk_id"]],
    }


def _extract_group(data: dict[str, Any]) -> dict[str, Any]:
    comps = [Component.model_validate(c) for c in data["input"]["components"]]
    design = ParsedDesign(design_name="x", source_format="llm", components=comps, confidence=1.0)
    return {
        "lines": [
            {
                "refdes": i.refdes,
                "quantity": i.quantity,
                "value": i.value,
                "footprint": i.footprint,
                "mpn": i.mpn,
                "manufacturer": i.manufacturer,
                "dnp": i.dnp,
            }
            for i in group_components(design)
        ]
    }


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    findings = []
    for line in data["input"]["lines"]:
        if line.get("dnp"):
            continue
        if not line.get("footprint"):
            findings.append(
                {
                    "refdes": line["refdes"],
                    "field": "footprint",
                    "severity": "error",
                    "message": "missing footprint",
                }
            )
        if not line.get("mpn"):
            findings.append(
                {
                    "refdes": line["refdes"],
                    "field": "mpn",
                    "severity": "warning",
                    "message": "missing MPN",
                }
            )
    return {"findings": findings}


def _repair(data: dict[str, Any]) -> dict[str, Any]:
    fixes = []
    for f in data["input"]["findings"]:
        if f["rule_id"] == "footprint.package_match" and f.get("line"):
            line = next(x for x in data["input"]["lines"] if x["line"] == f["line"])
            size = package_from_part_number(line.get("mpn", ""))
            if size and line.get("package"):
                fixes.append(
                    {
                        "line": f["line"],
                        "field": "footprint",
                        "new_value": line["footprint"].replace(line["package"], size),
                        "reason": "footprint size taken from the MPN",
                    }
                )
    return {"fixes": fixes}


def _compose(data: dict[str, Any]) -> dict[str, Any]:
    return {"lines": data["input"]["lines"]}


HANDLERS = {
    "mpn_select": _mpn_select,
    "extract_group": _extract_group,
    "validate": _validate,
    "repair": _repair,
    "compose": _compose,
}


def heuristic_responder(request: ChatRequest) -> dict[str, Any]:
    handler = HANDLERS.get(request.prompt_id)
    if handler is None:
        raise KeyError(f"fake provider has no behaviour for prompt {request.prompt_id!r}")
    return handler(_blocks(request))
