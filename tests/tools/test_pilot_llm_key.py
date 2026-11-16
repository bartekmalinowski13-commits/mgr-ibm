"""tools/pilot-llm-key.sh creates the app's LiteLLM virtual key without leaking a secret (SEC-08).

`fly` and `curl` are replaced by shims that record their arguments and standard input, so the
test can prove where the master key and the new virtual key did and did not travel.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "pilot-llm-key.sh"
MASTER = "sk-master-0123456789abcdef"
NEW_KEY = "sk-virtual-fedcba9876543210"

FLY_SHIM = r"""#!/usr/bin/env bash
echo "fly $*" >> "$SHIM_LOG"
case "$1 $2" in
  "secrets import") { echo "--- stdin of fly secrets import"; cat; } >> "$SHIM_LOG" ;;
  "proxy "*) exec sleep 30 ;;
esac
exit 0
"""

CURL_SHIM = r"""#!/usr/bin/env bash
echo "curl $*" >> "$SHIM_LOG"
config=""
for a in "$@"; do
  if [ "$a" = "-K" ]; then want=1
  else
    [ -n "${want:-}" ] && [ "$a" = "-" ] && config="$(cat)"
    want=""
  fi
done
[ -n "$config" ] && { echo "--- curl config on stdin"; echo "$config"; } >> "$SHIM_LOG"
prev=""
for a in "$@"; do
  if [ "$prev" = "--data-binary" ] && [ "${a#@}" != "$a" ]; then
    { echo "--- request body"; cat "${a#@}"; echo; } >> "$SHIM_LOG"
  fi
  prev="$a"
done
url="${@: -1}"
case "$url" in
  *"/v1/models") echo '{"data":[{"id":"mistral-large-eu"},{"id":"claude-sonnet-eu"}]}' ;;
  *"/key/generate") echo '{"key":"'"$SHIM_NEW_KEY"'","key_alias":"x"}' ;;
  *"/key/delete") echo '{"deleted_keys":["x"]}' ;;
  *) echo '{"status":"healthy"}' ;;
esac
"""


@pytest.fixture
def env(tmp_path):
    shims = tmp_path / "bin"
    shims.mkdir()
    for name, body in (("fly", FLY_SHIM), ("curl", CURL_SHIM)):
        path = shims / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "shim.log"
    log.write_text("")
    return {
        **os.environ,
        "PATH": f"{shims}:{os.environ['PATH']}",
        "HOME": str(home),
        "SHIM_LOG": str(log),
        "SHIM_NEW_KEY": NEW_KEY,
        "PROXY_WAIT_TRIES": "2",
    }


def run(env, *args: str, stdin: str = MASTER + "\n") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_creates_a_key_and_hands_it_straight_to_fly_without_printing_or_storing_it(env, tmp_path):
    result = run(env, "--alias", "bomagent-pilot-20261116")
    assert result.returncode == 0, result.stderr
    log = Path(env["SHIM_LOG"]).read_text()

    # the master key is only ever given to curl through its config on stdin, never as an argument
    argv_lines = [line for line in log.splitlines() if line.startswith(("fly ", "curl "))]
    assert argv_lines
    assert all(MASTER not in line for line in argv_lines)
    assert f"Bearer {MASTER}" in log.split("--- curl config on stdin")[1]

    # the new key reaches the app as a Fly secret through stdin only
    assert all(NEW_KEY not in line for line in argv_lines)
    stdin_of_fly = log.split("--- stdin of fly secrets import")[1]
    assert f"BOMAGENT_LLM_GATEWAY_KEY={NEW_KEY}" in stdin_of_fly
    assert "fly secrets import --app mgr-ibm-bomagent" in log

    # neither secret is printed, and nothing was written to the home directory
    assert MASTER not in result.stdout + result.stderr
    assert NEW_KEY not in result.stdout + result.stderr
    assert list(Path(env["HOME"]).iterdir()) == []


def test_the_key_is_limited_to_the_models_the_gateway_serves_and_has_a_budget(env):
    assert run(env, "--alias", "a", "--budget", "7", "--duration", "30d").returncode == 0
    log = Path(env["SHIM_LOG"]).read_text()
    body = json.loads(log.split("--- request body")[1].split("\n", 2)[1])
    assert body["models"] == ["mistral-large-eu", "claude-sonnet-eu"]
    assert body["max_budget"] == 7
    assert body["duration"] == "30d"
    assert body["key_alias"] == "a"


def test_an_empty_master_key_is_refused(env):
    result = run(env, "--alias", "a", stdin="\n")
    assert result.returncode != 0
    assert "master key" in (result.stdout + result.stderr).lower()
    assert "secrets import" not in Path(env["SHIM_LOG"]).read_text()


def test_deleting_an_old_key_by_alias_after_a_rotation(env):
    result = run(env, "--alias", "new", "--delete-alias", "old")
    assert result.returncode == 0, result.stderr
    log = Path(env["SHIM_LOG"]).read_text()
    assert "/key/delete" in log
    assert log.index("secrets import") < log.index("/key/delete")  # switch first, delete after


def test_delete_only_retires_a_key_without_creating_or_touching_the_app_secret(env):
    result = run(env, "--delete-only", "--delete-alias", "old")
    assert result.returncode == 0, result.stderr
    log = Path(env["SHIM_LOG"]).read_text()
    assert "/key/delete" in log
    assert "/key/generate" not in log
    assert "secrets import" not in log
    assert run(env, "--delete-only").returncode == 2  # nothing to delete: refused up front


def test_an_unknown_option_fails_before_anything_runs(env):
    result = run(env, "--nonsense")
    assert result.returncode != 0
    assert Path(env["SHIM_LOG"]).read_text() == ""
