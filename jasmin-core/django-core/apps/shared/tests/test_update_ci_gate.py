"""``scripts/update.sh`` deploys only a commit CI passed.

Before it fast-forwards, update.sh asks GitHub's REST API about the commit it
is about to deploy, and the newest CI run a push of that commit started
decides. Only "success" goes on; a run still queued or running, a failed or
cancelled run, no run at all, or no usable answer — GitHub unreachable, an
error status, a body that isn't a list of runs — stops it before the checkout
moves. ``--skip-ci-check`` or ``SKIP_CI_CHECK=1`` deploys anyway, with a
warning, for an outage.

The prod host has curl but neither jq nor Python, so the script reads the JSON
with grep and awk. The first half of these tests runs the script's CI gate
under bash with curl stubbed on the PATH, answering like the API or like a
network that doesn't; the second runs the whole script against a local origin
with ``deploy.sh`` stubbed, to see a red commit stay out of the checkout.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
UPDATE_SH = REPO_ROOT / "scripts" / "update.sh"

SHA = "8c8c440ce26d4ef8341cd70900b2df649b9bbcf2"
OTHER_SHA = "f3d7cce15220a29f75c259557cc66d83d601e9eb"
GITHUB_URL = "https://github.com/birgit-seyr/jasmin.git"
RUNS_URL = (
    "https://api.github.com/repos/birgit-seyr/jasmin/actions/workflows/ci.yml/runs"
)

# Leaves the user's own git configuration out and names a committer.
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

# Runs the CI gate the way update.sh reaches it: under -euo pipefail, with the
# commit to deploy in TARGET, the override in SKIP_CI, and git answering only
# for origin's URL.
_HARNESS = """set -euo pipefail
TARGET="$1"
SKIP_CI="$2"
git() {
    if [ "$*" = "config --get remote.origin.url" ] && [ -n "$ORIGIN_URL" ]; then
        printf '%s\\n' "$ORIGIN_URL"
    else
        return 1
    fi
}
@CI_GATE@
echo "CI gate passed"
"""

# Answers like `curl -sS -w '\\n%{http_code}'`: the body, a newline and the
# HTTP status from $CURL_STUB, or, given an exit status, what curl prints when
# nothing answers. Every call appends its URL, the last argument, to urls, and
# runs on_call first when there is one.
_CURL = """#!/bin/sh
for arg; do url="$arg"; done
printf '%s\\n' "$url" >> "$CURL_STUB/urls"
if [ -x "$CURL_STUB/on_call" ]; then
    "$CURL_STUB/on_call" >&2
fi
if [ -f "$CURL_STUB/exit" ]; then
    echo "curl: (6) Could not resolve host: api.github.com" >&2
    printf '\\n000'
    exit "$(cat "$CURL_STUB/exit")"
fi
cat "$CURL_STUB/body"
printf '\\n%s' "$(cat "$CURL_STUB/code")"
"""

# Sits where deploy.sh is in the checkout and says which commit it ran at.
_DEPLOY = '#!/bin/sh\necho "deploy.sh ran at $(git rev-parse HEAD)"\n'


def ci_run(
    *,
    sha: str = SHA,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: int = 38318648730,
    event: str = "push",
) -> dict:
    """A run as the API lists it. Its title, commit message and nested objects
    carry the words the script looks for, which must not count."""
    return {
        "id": run_id,
        "name": "CI",
        "head_branch": "main",
        "head_sha": sha,
        "path": ".github/workflows/ci.yml",
        "display_title": 'say "status": "completed", {"conclusion": "success"} — ü',
        "run_number": 301,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/birgit-seyr/jasmin/actions/runs/{run_id}",
        "pull_requests": [],
        "head_commit": {
            "id": sha,
            "message": 'line one\n\t"quoted" \\ {[,:]} "event": "push"',
            "author": {"name": "bia", "email": "bia@example.com"},
        },
        "repository": {"id": 1, "full_name": "birgit-seyr/jasmin", "private": False},
        "run_attempt": 1,
    }


def listing(*runs: dict, **extra: object) -> dict:
    return {"total_count": len(runs), "workflow_runs": list(runs), **extra}


def pretty(document: object) -> str:
    """The way api.github.com sends it."""
    return json.dumps(document, indent=2, ensure_ascii=False)


def compact(document: object) -> str:
    return json.dumps(document, separators=(",", ":"))


@dataclass
class CurlStub:
    dir: Path

    @property
    def bin(self) -> Path:
        return self.dir / "bin"

    def answer(self, body: str, code: int = 200) -> None:
        (self.dir / "body").write_text(body, encoding="utf-8")
        (self.dir / "code").write_text(str(code))

    def fail(self, exit_status: int) -> None:
        (self.dir / "exit").write_text(str(exit_status))

    def on_call(self, command: str) -> None:
        hook = self.dir / "on_call"
        hook.write_text(f"#!/bin/sh\nset -e\n{command}\n")
        hook.chmod(0o755)

    @property
    def urls(self) -> list[str]:
        calls = self.dir / "urls"
        return calls.read_text().splitlines() if calls.exists() else []

    def env(self, **extra: str) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "CURL_STUB": str(self.dir),
            **extra,
        }


@pytest.fixture(scope="module")
def update_script() -> str:
    if not UPDATE_SH.is_file():
        pytest.skip("scripts/update.sh is not in this checkout")
    return UPDATE_SH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ci_gate(update_script: str) -> str:
    return update_script[
        update_script.index("# ── 3. CI gate") : update_script.index(
            "# ── 4. fast-forward"
        )
    ]


@pytest.fixture
def curl(tmp_path: Path) -> CurlStub:
    stub = CurlStub(dir=tmp_path / "curl")
    stub.bin.mkdir(parents=True)
    script = stub.bin / "curl"
    script.write_text(_CURL)
    script.chmod(0o755)
    return stub


@pytest.fixture
def run_gate(
    ci_gate: str, curl: CurlStub
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(
        *, skip: bool = False, origin_url: str = GITHUB_URL
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-c",
                _HARNESS.replace("@CI_GATE@", ci_gate),
                "bash",
                SHA,
                "1" if skip else "0",
            ],
            env=curl.env(ORIGIN_URL=origin_url),
            capture_output=True,
            encoding="utf-8",
            timeout=60,
        )

    return run


def assert_refused(result: subprocess.CompletedProcess[str], *why: str) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert "CI gate passed" not in result.stdout
    assert f"Not deploying {SHA[:7]}" in result.stderr
    for text in why:
        assert text in result.stderr


def assert_passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CI gate passed" in result.stdout


class TestVerdict:
    @pytest.mark.parametrize("dump", [pretty, compact])
    def test_a_green_run_lets_the_deploy_go_on(self, run_gate, curl, dump):
        curl.answer(dump(listing(ci_run())))

        result = run_gate()

        assert_passed(result)
        assert f"CI passed for {SHA[:7]}" in result.stdout
        assert "actions/runs/38318648730" in result.stdout

    @pytest.mark.parametrize(
        "status", ["queued", "in_progress", "waiting", "requested", "pending"]
    )
    def test_a_run_still_going_stops_it(self, run_gate, curl, status):
        curl.answer(pretty(listing(ci_run(status=status, conclusion=None))))

        result = run_gate()

        assert_refused(result, f"still {status}", "actions/runs/38318648730")
        assert "again once it is green" in result.stderr
        assert "--skip-ci-check" not in result.stderr

    @pytest.mark.parametrize(
        "conclusion",
        [
            "failure",
            "timed_out",
            "startup_failure",
            "action_required",
            "neutral",
            "skipped",
            "stale",
        ],
    )
    def test_a_run_that_did_not_pass_stops_it(self, run_gate, curl, conclusion):
        curl.answer(pretty(listing(ci_run(conclusion=conclusion))))

        result = run_gate()

        assert_refused(result, f"ended in '{conclusion}'", "actions/runs/")
        assert "--skip-ci-check" not in result.stderr

    def test_a_cancelled_run_stops_it(self, run_gate, curl):
        curl.answer(pretty(listing(ci_run(conclusion="cancelled"))))

        assert_refused(run_gate(), "was cancelled", "run this again")

    def test_no_run_stops_it(self, run_gate, curl):
        curl.answer(pretty(listing()))

        assert_refused(run_gate(), "no CI run", "--skip-ci-check")

    def test_only_a_push_run_of_this_commit_counts(self, run_gate, curl):
        curl.answer(
            pretty(
                listing(
                    ci_run(sha=OTHER_SHA, run_id=3),
                    ci_run(event="pull_request", run_id=2),
                )
            )
        )

        assert_refused(run_gate(), "no CI run")

    @pytest.mark.parametrize("newest_first", [True, False])
    def test_the_newest_run_decides(self, run_gate, curl, newest_first):
        newer, older = ci_run(conclusion="failure", run_id=7), ci_run(run_id=6)
        runs = (newer, older) if newest_first else (older, newer)
        curl.answer(pretty(listing(*runs)))

        assert_refused(run_gate(), "ended in 'failure'", "actions/runs/7")

    def test_a_newer_green_run_outvotes_an_older_red_one(self, run_gate, curl):
        curl.answer(
            pretty(listing(ci_run(conclusion="failure", run_id=6), ci_run(run_id=7)))
        )

        assert_passed(run_gate())

    def test_keys_beside_or_inside_a_run_do_not_count(self, run_gate, curl):
        running = ci_run(status="in_progress", conclusion=None)
        running["head_commit"].update(status="completed", conclusion="success")
        curl.answer(pretty(listing(running, status="completed", conclusion="success")))

        assert_refused(run_gate(), "still in_progress")


class TestNoVerdict:
    @pytest.mark.parametrize("exit_status", [6, 7, 28, 35])
    def test_no_answer_stops_it(self, run_gate, curl, exit_status):
        curl.fail(exit_status)

        result = run_gate()

        assert_refused(result, "no answer from the GitHub API", "--skip-ci-check")
        assert "Could not resolve host" in result.stderr

    @pytest.mark.parametrize(
        ("code", "body", "shown"),
        [
            (
                403,
                '{"message":"API rate limit exceeded for 203.0.113.7."}',
                "API rate limit exceeded",
            ),
            (404, '{"message":"Not Found","status":"404"}', "Not Found"),
            (502, "<html><body>Bad gateway</body></html>", "Bad gateway"),
        ],
    )
    def test_an_error_status_stops_it(self, run_gate, curl, code, body, shown):
        curl.answer(body, code=code)

        assert_refused(run_gate(), f"HTTP {code}", shown, "--skip-ci-check")

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("", id="empty"),
            pytest.param("<!DOCTYPE html><html>Unicorn!</html>", id="html"),
            pytest.param(pretty(listing(ci_run()))[:-300], id="cut-short"),
            pytest.param('{"message": "Server Error"}', id="error-object"),
            pytest.param('{"workflow_runs": null}', id="null-runs"),
            pytest.param(pretty([ci_run()]), id="bare-array"),
            pytest.param(compact(listing()) + compact(listing()), id="two-documents"),
            pytest.param(compact(listing(ci_run())) + "]", id="unbalanced"),
        ],
    )
    def test_an_answer_that_is_no_list_of_runs_stops_it(self, run_gate, curl, body):
        curl.answer(body)

        assert_refused(run_gate(), "isn't a list of CI runs", "--skip-ci-check")


class TestRequest:
    def test_it_asks_about_the_push_runs_of_exactly_this_commit(self, run_gate, curl):
        curl.answer(pretty(listing(ci_run())))

        run_gate()

        assert curl.urls == [f"{RUNS_URL}?head_sha={SHA}&event=push&per_page=100"]

    @pytest.mark.parametrize(
        "origin_url",
        [
            "https://github.com/birgit-seyr/jasmin.git",
            "https://github.com/birgit-seyr/jasmin",
            "https://github.com/birgit-seyr/jasmin/",
            "https://x-access-token:s3cr3t@github.com/birgit-seyr/jasmin.git",
            "git@github.com:birgit-seyr/jasmin.git",
            "ssh://git@github.com/birgit-seyr/jasmin.git",
            "ssh://git@github.com:22/birgit-seyr/jasmin.git",
            "github-deploy:birgit-seyr/jasmin.git",
        ],
    )
    def test_the_repository_comes_from_origin(self, run_gate, curl, origin_url):
        curl.answer(pretty(listing(ci_run())))

        result = run_gate(origin_url=origin_url)

        assert_passed(result)
        assert [url.split("?")[0] for url in curl.urls] == [RUNS_URL]
        assert "s3cr3t" not in result.stdout + result.stderr

    @pytest.mark.parametrize(
        "origin_url", ["", "/srv/git/jasmin.git", "https://github.com/jasmin.git"]
    )
    def test_an_origin_that_names_no_repository_stops_it(
        self, run_gate, curl, origin_url
    ):
        result = run_gate(origin_url=origin_url)

        assert_refused(result, "names no GitHub repository", "--skip-ci-check")
        assert curl.urls == []


class TestSkip:
    def test_the_override_skips_the_question_and_says_so(self, run_gate, curl):
        result = run_gate(skip=True)

        assert_passed(result)
        assert curl.urls == []
        assert "CI CHECK SKIPPED" in result.stderr
        assert f"https://github.com/birgit-seyr/jasmin/commit/{SHA}" in result.stderr


@dataclass
class Server:
    """A checkout like the prod host's, one commit behind origin."""

    root: Path
    deployed: str
    pushed: str
    origin: Path
    work: Path


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def server(tmp_path: Path, update_script: str) -> Server:
    """origin is the GitHub URL, which git's insteadOf fetches from a local
    repository, so the script reads the URL it reads on the host."""
    if shutil.which("git") is None:
        pytest.skip("git isn't installed here")
    origin, work, root = tmp_path / "origin.git", tmp_path / "work", tmp_path / "server"
    git(tmp_path, "init", "--quiet", "--bare", str(origin))
    git(tmp_path, "init", "--quiet", str(work))
    for repository in (origin, work):
        git(repository, "symbolic-ref", "HEAD", "refs/heads/main")
    (work / "scripts").mkdir()
    (work / "scripts" / "update.sh").write_text(update_script, encoding="utf-8")
    deploy = work / "scripts" / "deploy.sh"
    deploy.write_text(_DEPLOY)
    deploy.chmod(0o755)
    (work / "app.txt").write_text("deployed\n")
    git(work, "add", "--all")
    git(work, "commit", "--quiet", "--message", "deployed")
    git(work, "push", "--quiet", str(origin), "main")
    git(tmp_path, "clone", "--quiet", str(origin), str(root))
    git(root, "config", "remote.origin.url", GITHUB_URL)
    git(root, "config", f"url.{origin}.insteadOf", GITHUB_URL)
    (work / "app.txt").write_text("pushed\n")
    git(work, "commit", "--quiet", "--all", "--message", "pushed")
    git(work, "push", "--quiet", str(origin), "main")
    return Server(
        root=root,
        deployed=git(root, "rev-parse", "HEAD"),
        pushed=git(work, "rev-parse", "HEAD"),
        origin=origin,
        work=work,
    )


def run_update(
    server: Server, curl: CurlStub, *args: str, answer: str = "", **env: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/update.sh", *args],
        cwd=server.root,
        env=curl.env(**GIT_ENV, **env),
        input=answer,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )


class TestUpdateScript:
    def test_a_green_commit_is_checked_out_and_deployed(self, server, curl):
        curl.answer(pretty(listing(ci_run(sha=server.pushed))))

        result = run_update(server, curl)

        assert result.returncode == 0, result.stdout + result.stderr
        assert curl.urls == [
            f"{RUNS_URL}?head_sha={server.pushed}&event=push&per_page=100"
        ]
        assert git(server.root, "rev-parse", "HEAD") == server.pushed
        assert f"deploy.sh ran at {server.pushed}" in result.stdout

    def test_a_push_during_the_check_is_left_for_the_next_update(self, server, curl):
        curl.answer(pretty(listing(ci_run(sha=server.pushed))))
        curl.on_call(
            f'git -C "{server.work}" commit --quiet --allow-empty --message later\n'
            f'git -C "{server.work}" push --quiet "{server.origin}" main'
        )

        result = run_update(server, curl)

        assert result.returncode == 0, result.stdout + result.stderr
        assert git(server.work, "rev-parse", "HEAD") != server.pushed
        assert git(server.root, "rev-parse", "HEAD") == server.pushed
        assert f"deploy.sh ran at {server.pushed}" in result.stdout

    @pytest.mark.parametrize(
        "run",
        [
            pytest.param({"conclusion": "failure"}, id="failed"),
            pytest.param({"status": "in_progress", "conclusion": None}, id="running"),
        ],
    )
    def test_a_commit_ci_did_not_pass_stays_out(self, server, curl, run):
        curl.answer(pretty(listing(ci_run(sha=server.pushed, **run))))

        result = run_update(server, curl)

        assert result.returncode == 1
        assert f"Not deploying {server.pushed[:7]}" in result.stderr
        assert "deploy.sh ran" not in result.stdout
        assert git(server.root, "rev-parse", "HEAD") == server.deployed
        assert (server.root / "app.txt").read_text() == "deployed\n"

    @pytest.mark.parametrize(
        ("args", "env"),
        [
            pytest.param(("--skip-ci-check",), {}, id="flag"),
            pytest.param((), {"SKIP_CI_CHECK": "1"}, id="environment"),
        ],
    )
    def test_the_override_deploys_without_asking(self, server, curl, args, env):
        curl.answer(pretty(listing(ci_run(sha=server.pushed, conclusion="failure"))))

        result = run_update(server, curl, *args, **env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert curl.urls == []
        assert "CI CHECK SKIPPED" in result.stderr
        assert f"deploy.sh ran at {server.pushed}" in result.stdout

    @pytest.mark.parametrize("value", ["yes", "true", "2"])
    def test_the_override_takes_only_1(self, server, curl, value):
        result = run_update(server, curl, SKIP_CI_CHECK=value)

        assert result.returncode == 2
        assert "SKIP_CI_CHECK must be 1" in result.stderr
        assert git(server.root, "rev-parse", "origin/main") == server.deployed

    def test_a_redeploy_checks_the_commit_it_rebuilds(self, server, curl):
        git(server.root, "fetch", "--quiet", "origin")
        git(server.root, "merge", "--quiet", "--ff-only", "origin/main")
        curl.answer(pretty(listing(ci_run(sha=server.pushed, conclusion="failure"))))

        result = run_update(server, curl, answer="y\n")

        assert result.returncode == 1
        assert curl.urls == [
            f"{RUNS_URL}?head_sha={server.pushed}&event=push&per_page=100"
        ]
        assert "deploy.sh ran" not in result.stdout

    def test_help_names_the_override(self, server, curl):
        result = run_update(server, curl, "--help")

        assert result.returncode == 0
        assert result.stdout.startswith("update.sh — deploy the latest pushed commit")
        assert "--skip-ci-check" in result.stdout
        assert "SKIP_CI_CHECK=1" in result.stdout
        assert "=====" not in result.stdout
        assert curl.urls == []

    def test_an_unknown_argument_is_refused(self, server, curl):
        result = run_update(server, curl, "--skip-ci")

        assert result.returncode == 2
        assert "Unknown argument: --skip-ci" in result.stderr
