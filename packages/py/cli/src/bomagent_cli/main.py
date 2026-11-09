"""``bomagent`` command line (ROADMAP M1/M3/M8).

bomagent parse PATH...            ParsedDesign as JSON (or a summary)
bomagent bom PATH... [--out]      deterministic BOM (parser + grouping + rules)
bomagent eval PRED REF            metrics vs a reference BOM
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from bomagent_bom.export import to_csv, to_json
from bomagent_bom.grouping import group_components
from bomagent_bom.model import BomItem, BomVersion, Requirements
from bomagent_cad import FileRef, ParseError, parse_files
from bomagent_eval import evaluate, load_reference, report_markdown
from bomagent_rules import DEFAULT_PACK, validate

app = typer.Typer(no_args_is_help=True, add_completion=False, help="BOM Agent tools")

DESIGN_SUFFIXES = {".kicad_sch", ".kicad_pro", ".kicad_pcb", ".csv", ".sch"}


def collect_files(paths: list[Path]) -> list[FileRef]:
    files: list[FileRef] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                FileRef.from_path(p)
                for p in sorted(path.iterdir())
                if p.suffix.lower() in DESIGN_SUFFIXES and p.name != "reference_bom.csv"
            )
        else:
            files.append(FileRef.from_path(path))
    return files


def _fail(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=2)


def _write(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}", err=True)


def load_requirements(path: Path | None) -> Requirements:
    if path is None:
        return Requirements()
    return Requirements.model_validate_json(path.read_text(encoding="utf-8"))


def deterministic_bom(files: list[FileRef], requirements: Requirements) -> BomVersion:
    design = parse_files(files)
    items = group_components(design)
    report = validate(items, requirements)
    return BomVersion(
        design_name=design.design_name,
        variant="deterministic",
        items=items,
        findings=report.findings,
        rule_pack=DEFAULT_PACK.id,
        rule_pack_version=DEFAULT_PACK.version,
    )


@app.command()
def parse(
    paths: Annotated[list[Path], typer.Argument(exists=True, help="files or project folder")],
    summary: Annotated[bool, typer.Option(help="print a short summary instead of JSON")] = False,
    out: Annotated[Path | None, typer.Option(help="write JSON here")] = None,
) -> None:
    """Parse design files into a ParsedDesign."""
    try:
        design = parse_files(collect_files(paths))
    except ParseError as exc:
        raise _fail(f"{exc} [{exc.code}]") from exc
    if summary:
        typer.echo(
            f"{design.design_name}: {design.source_format}, {len(design.components)} components,"
            f" {len(design.sheets)} sheet(s), confidence {design.confidence:.2f}"
        )
        for limitation in design.limitations:
            typer.echo(f"  limitation: {limitation}")
        return
    _write(design.model_dump_json(indent=2) + "\n", out)


@app.command()
def bom(
    paths: Annotated[list[Path], typer.Argument(exists=True)],
    requirements: Annotated[Path | None, typer.Option(help="Requirements JSON")] = None,
    fmt: Annotated[str, typer.Option("--format", help="csv or json")] = "csv",
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Deterministic BOM: parser + normalisation/grouping + rule pack (no LLM)."""
    try:
        result = deterministic_bom(collect_files(paths), load_requirements(requirements))
    except ParseError as exc:
        raise _fail(f"{exc} [{exc.code}]") from exc
    if fmt not in {"csv", "json"}:
        raise _fail("--format must be csv or json")
    _write(to_csv(result) if fmt == "csv" else to_json(result) + "\n", out)
    for f in result.findings:
        typer.echo(
            f"{f.severity.value:7s} {f.rule_id:28s} {' '.join(f.refdes)}: {f.message}", err=True
        )


def load_bom(path: Path) -> tuple[list[BomItem], BomVersion | None]:
    if path.suffix.lower() == ".json":
        version = BomVersion.model_validate_json(path.read_text(encoding="utf-8"))
        return version.items, version
    return load_reference(path), None


@app.command(name="eval")
def eval_cmd(
    predicted: Annotated[Path, typer.Argument(exists=True, help="BOM JSON (BomVersion) or CSV")],
    reference: Annotated[Path, typer.Argument(exists=True, help="reference BOM CSV")],
    known_mpns: Annotated[
        Path | None, typer.Option(help="file with one known MPN per line")
    ] = None,
    fmt: Annotated[str, typer.Option("--format", help="markdown or json")] = "markdown",
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Compare a BOM with a reference BOM (P/R/F1, field accuracy, hallucinations, cost)."""
    items, version = load_bom(predicted)
    known = None
    if known_mpns is not None:
        known = {ln.strip() for ln in known_mpns.read_text().splitlines() if ln.strip()}
    report = evaluate(
        version if version is not None else items,
        load_reference(reference),
        known_mpns=known,
        design=version.design_name if version else predicted.stem,
        variant=version.variant if version else "",
    )
    if fmt == "json":
        payload = report.model_dump(mode="json") | {"summary": report.summary()}
        _write(json.dumps(payload, indent=2) + "\n", out)
    else:
        _write(report_markdown(report), out)


def main() -> None:  # pragma: no cover
    app()
