"""Root pytest configuration: shared fixtures live in the bomagent-testing package."""

import os

# Sample projects are on by default in local/test; the suite switches them off so tests that
# count projects, files or outbox rows stay focused. services/api/tests/test_samples.py
# turns them on explicitly (and tests the default per environment).
os.environ.setdefault("BOMAGENT_SEED_SAMPLES", "false")

pytest_plugins = ["bomagent_testing.fixtures"]
