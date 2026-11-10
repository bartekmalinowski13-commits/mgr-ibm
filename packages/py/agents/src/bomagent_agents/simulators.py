"""Deterministic simulators of a competent model, one per prompt (fake LLM provider).

Used by the fake LLM server in the local stack and CI, by tests and by ``bomagent run``
offline. They read only what a real model would see - the rendered messages and tool
results - and answer with schema-valid JSON. They are **not** a model and their output is
never research data: thesis experiments run on real models through the gateway.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bomagent_agents.schemas import (
    ExtractedComponent,
    ExtractedComponents,
    GroupedBom,
    GroupedLine,
    PartSelection,
    Plan,
    RepairResult,
    ValidationIssue,
    ValidationVerdict,
)
from bomagent_bom.grouping import (
    DESCRIPTION_FIELDS,
    MANUFACTURER_FIELDS,
    MPN_FIELDS,
    group_components,
)
from bomagent_bom.model import Component, ParsedDesign
from bomagent_bom.packages import package_from_part_number, package_from_text
from bomagent_bom.refdes import natural_key
from bomagent_bom.values import normalize_value
from bomagent_llm.chat import ChatRequest, ChatResponse, ToolCall

_DATA = re.compile(r"<data>\n(.*?)\n</data>", re.DOTALL)
_EXCERPT = re.compile(r'<excerpt id="([^"]+)" source="([^"]*)">\n(.*?)\n</excerpt>', re.DOTALL)
_MPN_ENTRY = re.compile(
    r"(?<![A-Za-z0-9])([A-Z0-9][A-Z0-9\-+/#.()]{4,38}[A-Z0-9)+#]):\s*(.*?)(?=\s+[A-Z0-9][A-Z0-9\-+/#.()]{4,38}[A-Z0-9)+#]:|$)",
    re.DOTALL,
)
_MPN_PAREN = re.compile(
    r"(?<![A-Za-z0-9])([A-Z0-9][A-Z0-9\-+/#.]{4,38}[A-Z0-9])\s*\(([^)]{1,80})\)"
)
_QTY = re.compile(r"(\d+(?:[.,]\d+)?\s*[pnuµμmkKMG]?\s*(?:Ω|ohm|F|H|Hz))", re.IGNORECASE)


def _user_text(req: ChatRequest) -> str:
    return next((m.content or "" for m in req.messages if m.role == "user"), "")


def _data_blocks(req: ChatRequest) -> list[Any]:
    out: list[Any] = []
    for raw in _DATA.findall(_user_text(req)):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            out.append(raw)
    return out


def _reply(model: Any) -> ChatResponse:
    return ChatResponse(content=model.model_dump_json())


def _plan(req: ChatRequest) -> ChatResponse:
    return _reply(
        Plan(
            steps=["extract components", "group lines", "select parts", "validate", "compose"],
            notes="check patient-connected circuits and supply against the requirements",
        )
    )


def _extract(req: ChatRequest) -> ChatResponse:
    results = [json.loads(m.content or "{}") for m in req.messages if m.role == "tool"]
    pages = [r for r in results if "components" in r]
    if not pages or pages[-1].get("next_offset") is not None:
        offset = pages[-1]["next_offset"] if pages else 0
        call = ToolCall(
            id=f"call_{len(pages)}",
            name="list_components",
            arguments={"offset": offset, "limit": 50},
        )
        return ChatResponse(tool_calls=[call], finish_reason="tool_calls")
    comps: list[ExtractedComponent] = []
    for page in pages:
        for c in page["components"]:
            if not c.get("in_bom", True) or str(c["refdes"]).startswith("#"):
                continue
            comp = Component(
                refdes=c["refdes"],
                value=c.get("value", ""),
                footprint=c.get("footprint", ""),
                fields=c.get("fields", {}),
            )
            comps.append(
                ExtractedComponent(
                    refdes=comp.refdes,
                    value=comp.value,
                    footprint=comp.footprint,
                    mpn=comp.field(*MPN_FIELDS),
                    manufacturer=comp.field(*MANUFACTURER_FIELDS),
                    description=comp.field(*DESCRIPTION_FIELDS),
                    dnp=bool(c.get("dnp", False)),
                )
            )
    return _reply(ExtractedComponents(components=comps))


def _group(req: ChatRequest) -> ChatResponse:
    raw = _data_blocks(req)[0]
    comps = [
        Component(
            refdes=c["refdes"],
            value=c.get("value", ""),
            footprint=c.get("footprint", ""),
            fields={
                "MPN": c.get("mpn", ""),
                "Manufacturer": c.get("manufacturer", ""),
                "Description": c.get("description", ""),
            },
            dnp=c.get("dnp", False),
        )
        for c in raw
    ]
    design = ParsedDesign(
        design_name="sim", source_format="agent", components=comps, confidence=1.0
    )
    lines = [
        GroupedLine(
            refdes=list(i.refdes),
            quantity=i.quantity,
            kind=i.kind,
            value=i.value,
            value_normalized=i.value_normalized,
            footprint=i.footprint,
            package=i.package,
            mpn=i.mpn,
            manufacturer=i.manufacturer,
            description=i.description,
            dnp=i.dnp,
        )
        for i in group_components(design)
    ]
    return _reply(GroupedBom(lines=lines))


def _manufacturer(title: str, content: str) -> str:
    head = content.strip().splitlines()[0] if content.strip() else ""
    m = re.match(r"#*\s*([A-Z][A-Za-z\-&]+(?: [A-Z][a-z]+)?)", head)
    if m and m.group(1).lower() not in {"ordering", "features"}:
        return m.group(1).split()[0]
    return title.split("-", maxsplit=1)[0].capitalize()


def candidates(excerpts: list[tuple[str, str, str]]) -> list[tuple[str, str, str, str]]:
    """(chunk_id, manufacturer, mpn, description) from 'MPN: description' entries."""
    out = []
    for cid, title, content in excerpts:
        body = " ".join(content.split())
        found = [(m, d) for m, d in _MPN_ENTRY.findall(body) if "(" not in m]
        found += _MPN_PAREN.findall(body)
        for mpn, desc in found:
            if sum(ch.isdigit() for ch in mpn) >= 2:
                out.append((cid, _manufacturer(title, content), mpn.rstrip("."), desc.strip()))
    return out


def _matches(line: dict[str, Any], desc: str, mpn: str = "") -> bool:
    kind = line.get("kind")
    target = line.get("value_normalized") or normalize_value(str(line.get("value", "")), kind)
    if target:
        found = {normalize_value(q, kind) for q in _QTY.findall(desc)} - {None}
        if target not in found:
            return False
    elif (
        str(line.get("value", "")).strip()
        and str(line["value"]).strip().casefold() not in desc.casefold()
    ):
        return False
    pkg = line.get("package")
    other = package_from_text(desc) or package_from_part_number(mpn)
    return not (pkg and other and pkg != other)


def _pick(
    line: dict[str, Any], excerpts: list[tuple[str, str, str]], exclude: set[str]
) -> tuple[str, str, str, str] | None:
    for cand in candidates(excerpts):
        if cand[2] in exclude:
            continue
        if _matches(line, cand[3], cand[2]):
            return cand
    return None


def _select(req: ChatRequest) -> ChatResponse:
    line = _data_blocks(req)[0]
    excerpts = _EXCERPT.findall(_user_text(req))
    cand = _pick(line, excerpts, set())
    if cand is None:
        return _reply(PartSelection(confidence=0.0, rationale="no matching part in the excerpts"))
    cid, mfr, mpn, desc = cand
    return _reply(
        PartSelection(
            mpn=mpn,
            manufacturer=mfr,
            description=desc[:120],
            confidence=0.9,
            cited_chunks=[cid],
            rationale=f"value and package match: {desc[:80]}",
        )
    )


def _validate(req: ChatRequest) -> ChatResponse:
    lines = _data_blocks(req)[0]
    seen: dict[str, int] = {}
    issues: list[ValidationIssue] = []
    for ln in lines:
        for r in ln["refdes"]:
            seen[r] = seen.get(r, 0) + 1
        if not ln.get("mpn") and not ln.get("dnp"):
            issues.append(
                ValidationIssue(
                    refdes=ln["refdes"],
                    field="mpn",
                    severity="warning",
                    message="no manufacturer part number",
                )
            )
        if ln.get("quantity") and ln["quantity"] != len(ln["refdes"]):
            issues.append(
                ValidationIssue(
                    refdes=ln["refdes"],
                    field="quantity",
                    severity="error",
                    message="quantity differs from designator count",
                )
            )
    for r, n in seen.items():
        if n > 1:
            issues.append(
                ValidationIssue(
                    refdes=[r],
                    field="refdes",
                    severity="error",
                    message=f"{r} appears on {n} lines",
                )
            )
    return _reply(ValidationVerdict(issues=issues))


def _compose(req: ChatRequest) -> ChatResponse:
    lines = _data_blocks(req)[0]
    out = [GroupedLine.model_validate(ln) for ln in lines]
    out.sort(key=lambda ln: natural_key(ln.refdes[0]))
    return _reply(GroupedBom(lines=out))


def _repair(req: ChatRequest) -> ChatResponse:
    blocks = _data_blocks(req)
    line = blocks[0]
    excerpts = _EXCERPT.findall(_user_text(req))
    cand = _pick(line, excerpts, {str(line.get("mpn", ""))})
    if cand is None:
        return _reply(RepairResult(give_up=True, rationale="no listed part satisfies the rules"))
    cid, mfr, mpn, _desc = cand
    return _reply(
        RepairResult(
            mpn=mpn,
            manufacturer=mfr,
            cited_chunks=[cid],
            rationale="replaced with a catalogue part matching value and package",
        )
    )


def _single_agent(
    req: ChatRequest,
) -> ChatResponse:  # pragma: no cover - SDK adapter uses its own loop
    return _reply(GroupedBom(lines=[]))


SIMULATORS = {
    "orchestrator": _plan,
    "extract_components": _extract,
    "group_lines": _group,
    "select_part": _select,
    "validate_bom": _validate,
    "compose_bom": _compose,
    "repair_line": _repair,
    "single_agent_bom": _single_agent,
}


def simulate(request: ChatRequest) -> ChatResponse:
    prompt_id = request.metadata.get("prompt_id", "")
    fn = SIMULATORS.get(prompt_id)
    if fn is None:
        return ChatResponse(content=json.dumps({"error": f"no simulator for {prompt_id!r}"}))
    return fn(request)
