"""
The deployer must never hand back a URL for a page that was never deployed.

`deploy_article_to_vercel` used to return `public_url` on every failure path —
HTTP error, exception, ERROR deployment state, and even when no token existed
and the git push had failed. The caller (`output_service.record_generation_outputs`)
could not tell that apart from a real deploy, so it overwrote the pin's
`destination_url` with a URL that 404s. Pins shipped to Pinterest pointing at
pages nobody had published.

These tests lock in the new contract: a URL is returned only when a deploy path
actually succeeded, otherwise VercelDeployError.
"""

import asyncio

import httpx
import pytest

from app.services import vercel_publisher as vp


class _StubSettings:
    """Only the attributes deploy_article_to_vercel actually reads."""

    bridge_domain = "lookbooks.test"
    vercel_api_token = ""          # overridden per test
    vercel_project_name = "pinterest-lookbooks"
    vercel_team_id = None
    lookbook_git_auto_push = True  # else the function returns a local URL early


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, post_resp, poll_resp):
        self._post_resp = post_resp
        self._poll_resp = poll_resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        return self._post_resp

    async def get(self, url, headers=None):
        return self._poll_resp


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def deploy_env(monkeypatch):
    """Patch every external touchpoint; return a dict to configure per test."""
    state = {"git_pushed": False, "git_status": "push_failed"}

    async def _git_push(slug, repo_dir=None, commit_msg=None):
        return {"status": state["git_status"], "pushed": state["git_pushed"]}

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(vp, "settings", _StubSettings())
    monkeypatch.setattr(vp, "commit_and_push_lookbook", _git_push)
    monkeypatch.setattr(vp, "generate_catalog_index", _noop)
    monkeypatch.setattr(vp, "_gather_lookbook_payload", lambda: [])

    def client_factory(post_resp, poll_resp=None):
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda *a, **kw: _FakeClient(post_resp, poll_resp or _Resp(200, {"readyState": "READY"})),
        )

    state["client_factory"] = client_factory
    return state


def test_no_token_and_git_push_failed_raises(deploy_env):
    """The classic 404 pin: nothing was deployed anywhere."""
    deploy_env["git_pushed"] = False
    with pytest.raises(vp.VercelDeployError):
        _run(vp.deploy_article_to_vercel("slug-a", "<html/>", "job-1"))


def test_no_token_but_git_pushed_returns_url(deploy_env):
    """Vercel's Git integration will build it, so the URL is honest."""
    deploy_env["git_pushed"] = True
    deploy_env["git_status"] = "pushed"
    url = _run(vp.deploy_article_to_vercel("slug-a", "<html/>", "job-1"))
    assert url == "https://lookbooks.test/slug-a.html"


def test_rest_http_error_raises_when_git_not_pushed(deploy_env):
    deploy_env["git_pushed"] = False
    vp.settings.vercel_api_token = "tok"
    deploy_env["client_factory"](_Resp(403, {}, "forbidden"))
    with pytest.raises(vp.VercelDeployError):
        _run(vp.deploy_article_to_vercel("slug-a", "<html/>", "job-1"))


def test_rest_http_error_falls_back_to_successful_git_push(deploy_env):
    deploy_env["git_pushed"] = True
    deploy_env["git_status"] = "pushed"
    vp.settings.vercel_api_token = "tok"
    deploy_env["client_factory"](_Resp(403, {}, "forbidden"))
    url = _run(vp.deploy_article_to_vercel("slug-a", "<html/>", "job-1"))
    assert url == "https://lookbooks.test/slug-a.html"


def test_deployment_error_state_raises(deploy_env):
    """Vercel accepted the deployment, then it failed to build."""
    deploy_env["git_pushed"] = False
    vp.settings.vercel_api_token = "tok"
    deploy_env["client_factory"](
        _Resp(200, {"id": "dpl_1"}),
        poll_resp=_Resp(200, {"readyState": "ERROR"}),
    )
    with pytest.raises(vp.VercelDeployError):
        _run(vp.deploy_article_to_vercel("slug-a", "<html/>", "job-1"))


def test_ready_deployment_returns_url(deploy_env):
    deploy_env["git_pushed"] = False
    vp.settings.vercel_api_token = "tok"
    deploy_env["client_factory"](
        _Resp(200, {"id": "dpl_1"}),
        poll_resp=_Resp(200, {"readyState": "READY"}),
    )
    url = _run(vp.deploy_article_to_vercel("slug-a", "<html/>", "job-1"))
    assert url == "https://lookbooks.test/slug-a.html"
