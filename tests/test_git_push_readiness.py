"""
Regression guards for the git auto-push path.

Why this matters: `LOOKBOOK_GIT_AUTO_PUSH=true` was set for weeks while every
push failed on credentials. Nothing surfaced it — generation reported success,
the lookbook landed on disk, and the pin recorded the intended URL. The result
was nine pin destinations pointing at pages that never deployed.

Two things are pinned here:
  1. `check_push_readiness()` must correctly distinguish ready from broken, and
     give a useful hint for each failure mode (no remote, no credential,
     rejected credential, missing repo).
  2. `_run_git_cmd()` must run with GIT_TERMINAL_PROMPT=0 so a credential
     failure returns immediately instead of blocking a background task on an
     invisible prompt, and must accept a per-command timeout so a slow push is
     not killed under a local-plumbing budget.
"""
import asyncio
from pathlib import Path

import pytest

from app.services import git_publisher as gp


def _fake_runner(responses: dict[tuple, tuple[int, str, str]], calls: list):
    """
    Build a stub _run_git_cmd driven by command *prefix*.

    Prefix matching (not "is any token present") matters here: `git remote` and
    `git remote get-url origin` share the token "remote", so a substring match
    would answer both with the same canned response.
    """

    async def _runner(cmd, cwd, timeout=gp._GIT_LOCAL_TIMEOUT_S):
        calls.append({"cmd": list(cmd), "timeout": timeout})
        best, best_len = None, -1
        for key, value in responses.items():
            prefix = list(key)
            if len(prefix) > best_len and cmd[: len(prefix)] == prefix:
                best, best_len = value, len(prefix)
        return best if best is not None else (0, "", "")

    return _runner


@pytest.fixture
def repo_with_git(tmp_path, monkeypatch):
    """A lookbooks dir that looks like an initialised git repo."""
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestPushReadiness:
    def test_not_a_git_repo_is_reported_not_ready(self, tmp_path):
        r = asyncio.run(gp.check_push_readiness(tmp_path))
        assert r["ready"] is False
        assert "not a git repository" in r["message"]

    def test_missing_origin_remote_points_at_env_setting(self, repo_with_git, monkeypatch):
        monkeypatch.setattr(gp, "_run_git_cmd", _fake_runner({("remote",): (0, "", "")}, []))
        r = asyncio.run(gp.check_push_readiness(repo_with_git))
        assert r["ready"] is False
        assert "no 'origin' remote" in r["message"]
        assert "LOOKBOOK_GIT_REMOTE" in r["hint"]

    def test_missing_credential_hint_names_the_actual_fix(self, repo_with_git, monkeypatch):
        """The exact failure this whole change exists to surface."""
        calls: list = []
        responses = {
            ("remote",): (0, "origin", ""),
            ("remote", "get-url"): (0, "https://github.com/u/r.git", ""),
            ("ls-remote",): (
                128,
                "",
                "fatal: could not read Username for 'https://github.com': "
                "terminal prompts disabled",
            ),
        }
        monkeypatch.setattr(gp, "_run_git_cmd", _fake_runner(responses, calls))
        r = asyncio.run(gp.check_push_readiness(repo_with_git))
        assert r["ready"] is False
        assert r["auth_ok"] is False
        assert "gh auth setup-git" in r["hint"]
        assert "PAT" in r["hint"]

    def test_rejected_token_hint_mentions_scope(self, repo_with_git, monkeypatch):
        responses = {
            ("remote",): (0, "origin", ""),
            ("remote", "get-url"): (0, "https://github.com/u/r.git", ""),
            ("ls-remote",): (128, "", "fatal: Authentication failed for 'https://github.com/u/r.git'"),
        }
        monkeypatch.setattr(gp, "_run_git_cmd", _fake_runner(responses, []))
        r = asyncio.run(gp.check_push_readiness(repo_with_git))
        assert r["ready"] is False
        assert "scope" in r["hint"]

    def test_repo_not_found_hint(self, repo_with_git, monkeypatch):
        responses = {
            ("remote",): (0, "origin", ""),
            ("remote", "get-url"): (0, "https://github.com/u/r.git", ""),
            ("ls-remote",): (128, "", "remote: Repository not found."),
        }
        monkeypatch.setattr(gp, "_run_git_cmd", _fake_runner(responses, []))
        r = asyncio.run(gp.check_push_readiness(repo_with_git))
        assert r["ready"] is False
        assert "not found" in r["hint"].lower()

    def test_successful_probe_reports_ready(self, repo_with_git, monkeypatch):
        responses = {
            ("remote",): (0, "origin", ""),
            ("remote", "get-url"): (0, "https://github.com/u/r.git", ""),
            ("ls-remote",): (0, "abc123\trefs/heads/main", ""),
        }
        monkeypatch.setattr(gp, "_run_git_cmd", _fake_runner(responses, []))
        r = asyncio.run(gp.check_push_readiness(repo_with_git))
        assert r["ready"] is True
        assert r["auth_ok"] is True
        assert r["remote"] == "https://github.com/u/r.git"

    def test_probe_uses_the_network_timeout_not_the_local_one(self, repo_with_git, monkeypatch):
        calls: list = []
        responses = {
            ("remote",): (0, "origin", ""),
            ("remote", "get-url"): (0, "https://github.com/u/r.git", ""),
            ("ls-remote",): (0, "", ""),
        }
        monkeypatch.setattr(gp, "_run_git_cmd", _fake_runner(responses, calls))
        asyncio.run(gp.check_push_readiness(repo_with_git))
        probe = [c for c in calls if "ls-remote" in c["cmd"]]
        assert probe, "ls-remote was never invoked"
        assert probe[0]["timeout"] == gp._GIT_NETWORK_TIMEOUT_S


class TestGitRunnerHardening:
    def test_terminal_prompt_is_disabled(self, tmp_path):
        """A credential prompt must fail fast, never hang a background task."""
        captured: dict = {}

        real_exec = asyncio.create_subprocess_exec

        async def _spy(*args, **kwargs):
            captured.update(kwargs)
            return await real_exec(*args, **kwargs)

        async def _go():
            import unittest.mock as mock

            with mock.patch.object(asyncio, "create_subprocess_exec", _spy):
                return await gp._run_git_cmd(["--version"], cwd=tmp_path)

        asyncio.run(_go())
        assert captured.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"

    def test_network_budget_exceeds_local_budget(self):
        assert gp._GIT_NETWORK_TIMEOUT_S > gp._GIT_LOCAL_TIMEOUT_S
        assert gp._GIT_LOCAL_TIMEOUT_S == 30.0
        assert gp._GIT_NETWORK_TIMEOUT_S >= 120.0

    def test_timeout_is_reported_with_the_actual_budget(self, tmp_path, monkeypatch):
        class _Proc:
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def _spawn(*args, **kwargs):
            return _Proc()

        async def _timeout(coro, timeout=None):
            # Close the coroutine we were handed, otherwise it is left
            # un-awaited and Python emits a RuntimeWarning.
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise asyncio.TimeoutError()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
        monkeypatch.setattr(asyncio, "wait_for", _timeout)
        code, out, err = asyncio.run(gp._run_git_cmd(["push"], cwd=tmp_path, timeout=180.0))
        assert code == -1
        assert "180" in err
