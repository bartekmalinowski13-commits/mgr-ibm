"""tools/deploy.sh against stubbed CLIs (nothing reaches AWS): migrations with the new image
run BEFORE the rollout (ops review I5), and the smoke step checks readiness (I6)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

AWS = r"""#!/usr/bin/env bash
echo "aws $*" >> "$CALLS"
case "$1 $2" in
  "cloudformation describe-stacks")
    if [ "${FIRST:-}" = 1 ] && [[ "$*" == *-Compute* ]] && [ ! -f "$STATE/deployed" ]; then
      echo "stack does not exist" >&2; exit 254; fi
    q="$*"; key=${q##*OutputKey, \'}; key=${key%%\'*}
    case "$key" in
      DbBootstrapTaskDefinition) echo "arn:taskdef/bootstrap:1" ;;
      MigrationTaskDefinition) echo "arn:taskdef/migrate:1" ;;
      *) echo "value-$key" ;;
    esac ;;
  "ecs describe-task-definition")
    c=migrate; [[ "$*" == *bootstrap* ]] && c=dbbootstrap
    echo "{\"family\": \"f-$c\", \"revision\": 1, \"status\": \"ACTIVE\", \"cpu\": \"256\",
      \"containerDefinitions\": [{\"name\": \"$c\",
      \"image\": \"1.dkr.ecr.eu-central-1.amazonaws.com/bomagent-migrate:OLD\"}]}" ;;
  "ecs register-task-definition")
    for a in "$@"; do case "$a" in file://*) f=${a#file://} ;; esac; done
    jq -r '.containerDefinitions[0].image' "$f" >> "$STATE/registered"
    jq -e 'has("revision") or has("status") | not' "$f" > /dev/null || exit 3
    echo "arn:taskdef/new-$(jq -r .family "$f"):2" ;;
  "ecs run-task") echo "task-1" ;;
  "ecs describe-tasks") echo "0" ;;
  "ecs list-services") printf 'svc-a\tsvc-b\n' ;;
  "ec2 describe-subnets") printf 'subnet-1\tsubnet-2\n' ;;
esac
exit 0
"""

PNPM = r"""#!/usr/bin/env bash
echo "pnpm $*" >> "$CALLS"
if [[ "$*" == *"deploy --all"* ]]; then touch "$STATE/deployed"; fi
if [[ "$*" == *"run build"* ]]; then mkdir -p apps/web/dist; fi
exit 0
"""

CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$CALLS"
if [[ "$*" == *"/v1/me"* ]]; then printf 401; exit 0; fi
if [[ "$*" == *"/v1/projects"* ]]; then cat > "$STATE/curl-stdin"; printf 200; exit 0; fi
exit 0
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    if not (shutil.which("jq") and shutil.which("bash")):
        pytest.skip("needs bash and jq")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"aws": AWS, "pnpm": PNPM, "curl": CURL}.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    work = tmp_path / "repo"
    (work / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools/deploy.sh", work / "tools/deploy.sh")
    (tmp_path / "state").mkdir()
    return tmp_path


def deploy(sandbox: Path, **extra: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    env = {
        "PATH": f"{sandbox / 'bin'}:{os.environ['PATH']}",
        "CALLS": str(sandbox / "calls"),
        "STATE": str(sandbox / "state"),
        "ENV": "dev",
        "AWS_ACCOUNT_ID": "111111111111",
        "IMAGE_REGISTRY": "1.dkr.ecr.eu-central-1.amazonaws.com",
        "IMAGE_TAG": "NEWSHA",
        "GITHUB_REPOSITORY": "o/r",
        **extra,
    }
    proc = subprocess.run(
        ["bash", "tools/deploy.sh"],
        cwd=sandbox / "repo",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = (sandbox / "calls").read_text().splitlines()
    return proc, calls


def _index(calls: list[str], needle: str) -> int:
    return next(i for i, c in enumerate(calls) if needle in c)


def test_migrations_with_the_new_image_run_before_the_rollout(sandbox):
    proc, calls = deploy(sandbox)
    assert proc.returncode == 0, proc.stderr
    first_migration = _index(calls, "ecs run-task")
    rollout = _index(calls, "deploy --all")
    assert first_migration < rollout
    assert "arn:taskdef/new-f-dbbootstrap:2" in calls[first_migration]
    registered = (sandbox / "state/registered").read_text().split()
    assert registered == [
        "1.dkr.ecr.eu-central-1.amazonaws.com/bomagent-migrate:NEWSHA",
        "1.dkr.ecr.eu-central-1.amazonaws.com/bomagent-migrate:NEWSHA",
    ]
    order = [c for c in calls if "ecs run-task" in c]
    assert "new-f-migrate" in order[1]  # bootstrap, then migrate - both before the rollout
    assert len(order) == 4  # and once more with the stack-managed definitions (no-op)


def test_first_deployment_migrates_after_creating_the_stacks(sandbox):
    proc, calls = deploy(sandbox, FIRST="1")
    assert proc.returncode == 0, proc.stderr
    assert _index(calls, "deploy --all") < _index(calls, "ecs run-task")
    assert not (sandbox / "state/registered").exists()


def test_smoke_waits_for_stable_services_and_reads_with_the_smoke_key(sandbox):
    proc, calls = deploy(sandbox, SMOKE_TENANT_API_KEY="bomk_smoke")
    assert proc.returncode == 0, proc.stderr
    assert any("ecs wait services-stable" in c and "svc-a svc-b" in c for c in calls)
    read = next(c for c in calls if "/v1/projects" in c)
    assert "bomk_smoke" not in read  # the key goes over stdin, never argv
    assert "bomk_smoke" in (sandbox / "state/curl-stdin").read_text()


def test_smoke_without_a_key_warns(sandbox):
    proc, _ = deploy(sandbox)
    assert "SMOKE_TENANT_API_KEY not set" in proc.stdout
