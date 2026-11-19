"""``bomagent`` command line (ROADMAP M1/M3/M8).

bomagent parse PATH...            ParsedDesign as JSON (or a summary)
bomagent bom PATH... [--out]      deterministic BOM (parser + grouping + rules)
bomagent eval PRED REF            metrics vs a reference BOM
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

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


def build_chat(model_id: str, cassettes: Path | None) -> Any:
    """Fake provider for ``fake-*`` models; recorded responses only (replay, no gateway) for
    any other model when ``cassettes`` is given - a missing recording raises
    ``CassetteMissError`` instead of falling back to a heuristic answer; otherwise the LLM
    gateway from the environment (``BOMAGENT_LLM_GATEWAY_URL`` / ``BOMAGENT_LLM_GATEWAY_KEY``).
    """
    import os

    from bomagent_agents.fake_responder import heuristic_responder
    from bomagent_llm import chat as chat_mod
    from bomagent_llm.catalog import load_catalog

    spec = load_catalog().get(model_id)
    if spec.provider == "fake":
        return chat_mod.FakeChat(heuristic_responder, cassettes)
    if cassettes is not None:
        if not (cassettes / spec.id).is_dir():
            raise _fail(f"no cassettes for {spec.id} under {cassettes}; record them first")
        # the real ModelSpec stays in the request, so the cache keys match the recording
        return chat_mod.FakeChat(None, cassettes / spec.id)
    url, key = (
        os.environ.get("BOMAGENT_LLM_GATEWAY_URL"),
        os.environ.get("BOMAGENT_LLM_GATEWAY_KEY"),
    )
    if not url or not key:
        raise _fail("set BOMAGENT_LLM_GATEWAY_URL and BOMAGENT_LLM_GATEWAY_KEY for real models")
    return chat_mod.GatewayChat(url, key)


def _execute(
    paths: list[Path],
    *,
    variant: str,
    runtime: str | None,
    model: str,
    kb_dir: Path,
    requirements: Path | None,
    reference: Path | None,
    chat: Any,
    out: Path | None,
    min_f1: float | None = None,
    max_hallucination_rate: float | None = None,
) -> None:
    import asyncio

    from bomagent_agents.contracts import RunConfig, RunInput
    from bomagent_agents.registry import context_factory, runtime_for
    from bomagent_agents.retrieval import InMemoryRetriever

    if variant not in {"A", "B"}:
        raise _fail("--variant must be A or B")
    if (min_f1 is not None or max_hallucination_rate is not None) and reference is None:
        raise _fail("regression thresholds need --reference")
    try:
        design = parse_files(collect_files(paths))
    except ParseError as exc:
        raise _fail(f"{exc} [{exc.code}]") from exc

    async def go() -> Any:
        retriever = await InMemoryRetriever.from_directory(kb_dir)
        rt = runtime_for(variant, context_factory(chat, retriever), runtime=runtime)
        result = await rt.run(
            RunInput(
                design=design,
                requirements=load_requirements(requirements),
                config=RunConfig(variant=variant, model_id=model),  # type: ignore[arg-type]
            )
        )
        return result, await retriever.known_mpns()

    from bomagent_llm.chat import CassetteMissError

    try:
        result, known = asyncio.run(go())
    except CassetteMissError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(
        f"{result.runtime}: {result.status}, {len(result.bom.items)} lines, "
        f"{result.usage.llm_calls} LLM calls, {result.usage.input_tokens}+"
        f"{result.usage.output_tokens} tokens, {result.usage.wall_time_s:.2f} s",
        err=True,
    )
    if out is not None:
        out.write_text(to_json(result.bom) + "\n", encoding="utf-8")
    if reference is not None:
        report = evaluate(
            result.bom,
            load_reference(reference),
            known_mpns=known,
            design_mpns={c.field("MPN") for c in design.components} - {""},
            design=design.design_name,
            variant=variant,
            model=model,
        )
        sys.stdout.write(report_markdown(report))
        summary = report.summary()
        failures = []
        if min_f1 is not None and summary["line_f1"] < min_f1:
            failures.append(f"line_f1 {summary['line_f1']:.3f} < {min_f1:.3f}")
        rate = summary["attempted_mpn_hallucination_rate"]
        if max_hallucination_rate is not None and rate > max_hallucination_rate:
            failures.append(
                f"attempted_mpn_hallucination_rate {rate:.3f} > {max_hallucination_rate:.3f}"
            )
        if failures:
            typer.echo("REGRESSION: " + "; ".join(failures), err=True)
            raise typer.Exit(code=1)


@app.command()
def run(
    paths: Annotated[list[Path], typer.Argument(exists=True, help="design files or folder")],
    variant: Annotated[str, typer.Option(help="A (LLM only) or B (hybrid)")] = "B",
    runtime: Annotated[
        str | None, typer.Option(help="langgraph_a|langgraph_b|claude_agent_sdk_a")
    ] = None,
    model: Annotated[str, typer.Option(help="model id from the catalogue")] = "fake-closed",
    kb_dir: Annotated[Path, typer.Option(help="datasheets for retrieval")] = Path(
        "evals/fixtures/datasheets"
    ),
    requirements: Annotated[Path | None, typer.Option(help="Requirements JSON")] = None,
    reference: Annotated[Path | None, typer.Option(help="reference BOM CSV to score")] = None,
    cassettes: Annotated[Path | None, typer.Option(help="recorded responses")] = None,
    out: Annotated[Path | None, typer.Option(help="write BomVersion JSON here")] = None,
    min_f1: Annotated[
        float | None, typer.Option(help="exit 1 when line F1 is below this (needs --reference)")
    ] = None,
    max_hallucination_rate: Annotated[
        float | None,
        typer.Option(help="exit 1 when the attempted MPN hallucination rate exceeds this"),
    ] = None,
) -> None:
    """Run variant A or B on a design (fake provider by default; no keys needed)."""
    _execute(
        paths,
        variant=variant,
        runtime=runtime,
        model=model,
        kb_dir=kb_dir,
        requirements=requirements,
        reference=reference,
        chat=build_chat(model, cassettes),
        out=out,
        min_f1=min_f1,
        max_hallucination_rate=max_hallucination_rate,
    )


@app.command()
def record(
    paths: Annotated[list[Path], typer.Argument(exists=True, help="design files or folder")],
    variant: Annotated[str, typer.Option(help="A (LLM only) or B (hybrid)")] = "B",
    runtime: Annotated[str | None, typer.Option(help="runtime override")] = None,
    model: Annotated[str, typer.Option(help="model id from the catalogue")] = "fake-closed",
    kb_dir: Annotated[Path, typer.Option(help="datasheets for retrieval")] = Path(
        "evals/fixtures/datasheets"
    ),
    requirements: Annotated[Path | None, typer.Option(help="Requirements JSON")] = None,
    cassettes: Annotated[
        Path, typer.Option(help="cassette root; files go to <root>/<model>/")
    ] = Path("tests/cassettes"),
) -> None:
    """Run like ``run`` and store every model response + usage as a cassette for replay.

    Real models need the gateway env vars (owner-run only; never in PR CI). Replay with
    ``bomagent run --cassettes <root>``."""
    from bomagent_llm.chat import RecordingChat

    recorder = RecordingChat(build_chat(model, None), cassettes)
    _execute(
        paths,
        variant=variant,
        runtime=runtime,
        model=model,
        kb_dir=kb_dir,
        requirements=requirements,
        reference=None,
        chat=recorder,
        out=None,
    )
    typer.echo(f"recorded {len(recorder.recorded)} cassette(s) under {cassettes / model}", err=True)


def _register_subcommands() -> None:
    from bomagent_cli.experiment import experiment_app

    app.add_typer(experiment_app, name="experiment")


_register_subcommands()


def main() -> None:  # pragma: no cover
    app()
