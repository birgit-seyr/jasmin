"""The deploy scripts read ``.env`` through ``envval``, and a missing key reads
as empty.

``deploy.sh`` and ``validate_gateway_config.sh`` run under
``set -euo pipefail``. A server's ``.env`` lacks every key added after it was
written: ``APP_DB_USER`` and ``APP_DB_PASSWORD`` arrive only with the move to
the app's own database role. ``envval`` answers such a key with an empty value,
as it does an empty one, so the script goes on to its default or its warning.
Were grep's "no match" to fail the read, set -e would end the script at the
assignment without a word.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = REPO_ROOT / "scripts"
DEPLOY_SH = SCRIPTS / "deploy.sh"

ENVVAL_DEFINITION = re.compile(r"^envval\(\).*$", re.MULTILINE)

# Runs a script's envval the way the script does, under -euo pipefail with
# ENV_FILE set, and prints each key's value in brackets.
_HARNESS = """set -euo pipefail
ENV_FILE="$1"
shift
@ENVVAL@
for key; do
    value="$(envval "$key")"
    printf '[%s]\\n' "$value"
done
"""


def scripts_with_envval() -> list[Path]:
    if not SCRIPTS.is_dir():
        return []
    return sorted(
        path
        for path in SCRIPTS.glob("*.sh")
        if ENVVAL_DEFINITION.search(path.read_text(encoding="utf-8"))
    )


@pytest.mark.parametrize("script", scripts_with_envval(), ids=lambda path: path.name)
def test_a_missing_key_reads_as_empty(script: Path, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EMPTY=\nURL=postgres://user:secret@host/db?sslmode=require\n"
        "TWICE=first\nTWICE=second\n",
        encoding="utf-8",
    )
    match = ENVVAL_DEFINITION.search(script.read_text(encoding="utf-8"))
    assert match is not None

    result = subprocess.run(
        [
            "bash",
            "-c",
            _HARNESS.replace("@ENVVAL@", match.group(0)),
            "bash",
            str(env_file),
            "MISSING",
            "EMPTY",
            "URL",
            "TWICE",
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "[]",
        "[]",
        "[postgres://user:secret@host/db?sslmode=require]",
        "[first]",
    ]


def test_deploy_goes_on_with_an_env_that_names_no_app_role(tmp_path: Path) -> None:
    """A server's .env from before the app's own role: deploy.sh warns that the
    app logs in as the superuser and goes on with its checks."""
    if not DEPLOY_SH.is_file():
        pytest.skip("scripts/deploy.sh is not in this checkout")
    script = DEPLOY_SH.read_text(encoding="utf-8")
    required = re.search(r'^REQUIRED="([^"]*)"', script, re.MULTILINE)
    assert required is not None
    root = tmp_path / "server"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "deploy.sh").write_text(script, encoding="utf-8")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    values = dict.fromkeys(required.group(1).replace("\\", " ").split(), "x")
    values["COMPOSE_PROJECT_NAME"] = "jasmin-platform"
    (root / ".env").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n")
    docker.chmod(0o755)

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"],
        cwd=root,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )

    assert "the app logs in as the database superuser" in result.stdout
    # The check after the .env's: this server has no Linode credentials file.
    assert result.returncode == 1
    assert "certbots/linode.ini missing" in result.stderr
