#!/bin/sh
# LLM gateway start: refuse to run when the environment points outside the EU (ADR-0006,
# CLAUDE.md rule 2), then hand over to LiteLLM with the arguments from CMD.
# The config file only references os.environ/..., so this is where those values are verified.
set -eu
PYTHONPATH=/opt/eu-guard python -m bomagent_llm.eu_guard
exec litellm "$@"
