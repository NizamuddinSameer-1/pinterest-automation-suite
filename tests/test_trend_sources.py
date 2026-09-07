"""Source clients return SourceSignal and never raise (fail-soft)."""
import pytest
from app.services.trend_sources import (
    SourceSignal,
    fetch_amazon_movers,
    fetch_gtrends,
    fetch_pinterest,
    fetch_shopping,
)


@pytest.mark.asyncio
async def test_shopping_parses_suggestion_payload(monkeypatch):
    import app.services.trend_sources as mod

    class _Resp:
        status_code = 200

        def json(self):
            return ["barn jacket", ["barn jacket women", "barn jacket mens"]]

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            assert params["q"] == "barn jacket"
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: _Client())
    sig = await fetch_shopping("barn jacket", "fashion")
    assert isinstance(sig, SourceSignal)
    assert sig.source == "shopping"
    assert sig.status == "fresh"
    assert sig.queries == ["barn jacket women", "barn jacket mens"]


@pytest.mark.asyncio
async def test_clients_fail_soft_on_network_error(monkeypatch):
    import app.services.trend_sources as mod

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("offline")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    for coro in (
        fetch_shopping("x", "fashion"),
        fetch_gtrends("x", "fashion"),
        fetch_amazon_movers("x", "fashion"),
        fetch_pinterest("x", "fashion"),
    ):
        sig = await coro
        assert sig.status in ("stale", "error")
        assert sig.queries == []
