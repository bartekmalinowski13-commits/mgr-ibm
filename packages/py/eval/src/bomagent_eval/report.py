"""Human-readable reports (Markdown tables for the thesis, JSON for machines)."""

from __future__ import annotations

from collections.abc import Sequence

from bomagent_eval.metrics import EvalReport


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def report_markdown(report: EvalReport) -> str:
    lines = [
        f"## {report.design} - variant {report.variant or '?'}"
        + (f" ({report.model})" if report.model else ""),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Line precision / recall / F1 | {_pct(report.lines.precision)} / "
        f"{_pct(report.lines.recall)} / {_pct(report.lines.f1)} |",
        f"| Designator F1 | {_pct(report.designators.f1)} |",
    ]
    for name, score in report.fields.items():
        if score.compared:
            lines.append(
                f"| Accuracy: {name} | {_pct(score.accuracy)} ({score.correct}/{score.compared}) |"
            )
    h = report.hallucinations
    lines += [
        f"| MPN hallucination rate | {_pct(h.rate)} ({h.hallucinated}/{h.predicted_mpns}) |",
        f"| LLM calls / tokens in / out | {report.usage.llm_calls} / "
        f"{report.usage.input_tokens} / {report.usage.output_tokens} |",
        f"| Cost / wall time | {report.usage.cost_eur:.4f} EUR / "
        f"{report.usage.wall_time_s:.1f} s |",
    ]
    if report.diffs:
        lines += ["", "| RefDes | Field | Predicted | Expected |", "|---|---|---|---|"]
        lines += [
            f"| {d.refdes} | {d.field} | {d.predicted} | {d.expected} |" for d in report.diffs[:30]
        ]
    return "\n".join(lines) + "\n"


def comparison_markdown(reports: Sequence[EvalReport]) -> str:
    header = "| Design | Variant | Model | Line F1 | MPN acc. | Halluc. | Tokens | Time [s] |"
    rows = [header, "|---|---|---|---|---|---|---|---|"]
    for r in reports:
        rows.append(
            f"| {r.design} | {r.variant} | {r.model} | {_pct(r.lines.f1)} | "
            f"{_pct(r.fields['mpn'].accuracy)} | {_pct(r.hallucinations.rate)} | "
            f"{r.usage.input_tokens + r.usage.output_tokens} | {r.usage.wall_time_s:.1f} |"
        )
    return "\n".join(rows) + "\n"
