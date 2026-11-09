"""Evaluation: BOM vs reference (P/R/F1, field accuracy, hallucinations, cost)."""

from bomagent_eval.injection import InjectedError, detection_rate, inject_errors
from bomagent_eval.metrics import EvalReport, evaluate, match_lines
from bomagent_eval.reference import load_reference, load_reference_csv
from bomagent_eval.report import comparison_markdown, report_markdown
from bomagent_eval.stats import aggregate, pairwise_agreement

__version__ = "1.0.0"
__all__ = [
    "EvalReport",
    "InjectedError",
    "aggregate",
    "comparison_markdown",
    "detection_rate",
    "evaluate",
    "inject_errors",
    "load_reference",
    "load_reference_csv",
    "match_lines",
    "pairwise_agreement",
    "report_markdown",
]
