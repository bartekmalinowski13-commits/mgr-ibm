"""Rule contract and rule-pack runner."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from bomagent_bom.model import BomItem, BomVersion, Finding, Requirements, Severity


@dataclass(frozen=True)
class RuleContext:
    requirements: Requirements = field(default_factory=Requirements)


CheckFn = Callable[[list[BomItem], RuleContext], Iterable[Finding]]


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    title: str
    check: CheckFn
    references: tuple[str, ...] = ()  # standards / sources the rule encodes


@dataclass(frozen=True)
class RulePack:
    id: str
    version: str
    rules: tuple[Rule, ...]

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)


@dataclass(frozen=True)
class ValidationReport:
    pack: str
    version: str
    findings: list[Finding]
    rules_run: list[str]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_line(self) -> dict[int, list[Finding]]:
        out: dict[int, list[Finding]] = {}
        for f in self.findings:
            if f.line is not None:
                out.setdefault(f.line, []).append(f)
        return out


def finding(
    rule: Rule | str,
    severity: Severity,
    message: str,
    item: BomItem | None = None,
    field: str | None = None,
    refdes: list[str] | None = None,
) -> Finding:
    rule_id = rule.id if isinstance(rule, Rule) else rule
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        refdes=refdes if refdes is not None else (list(item.refdes) if item else []),
        field=field,
        line=item.line if item else None,
    )


def run_pack(
    pack: RulePack,
    bom: BomVersion | list[BomItem],
    ctx: RuleContext | None = None,
    *,
    only: set[str] | None = None,
) -> ValidationReport:
    items = bom.items if isinstance(bom, BomVersion) else bom
    ctx = ctx or RuleContext()
    findings: list[Finding] = []
    ran: list[str] = []
    for rule in pack.rules:
        if only is not None and rule.id not in only:
            continue
        ran.append(rule.id)
        for f in rule.check(items, ctx):
            findings.append(
                f.model_copy(update={"rule_pack": pack.id, "rule_pack_version": pack.version})
            )
    findings.sort(key=lambda f: (f.line or 0, f.rule_id))
    return ValidationReport(pack.id, pack.version, findings, ran)
