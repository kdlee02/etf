"""web_search 단위 테스트 — 네트워크 없음(urlopen mock)."""
import json
import urllib.error

import etf_agent.websearch as ws


class FakeResp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_web_search_parses_results(monkeypatch):
    monkeypatch.setenv("TAVILEY_API_KEY", "x")
    monkeypatch.setattr(ws, "_load_env", lambda: None)
    monkeypatch.setattr(ws.urllib.request, "urlopen",
                        lambda *a, **k: FakeResp({"results": [
                            {"title": "t", "url": "u", "content": "c"}]}))
    out = ws.web_search("비트코인 시세")
    assert out["found"] is True
    assert out["results"][0]["url"] == "u"


def test_web_search_never_raises_on_error(monkeypatch):
    monkeypatch.setenv("TAVILEY_API_KEY", "x")
    monkeypatch.setattr(ws, "_load_env", lambda: None)

    def boom(*a, **k):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(ws.urllib.request, "urlopen", boom)
    out = ws.web_search("아무거나")
    assert out["found"] is False


def test_web_search_soft_fails_without_key(monkeypatch):
    monkeypatch.setattr(ws, "_load_env", lambda: None)
    monkeypatch.delenv("TAVILEY_API_KEY", raising=False)
    out = ws.web_search("아무거나")
    assert out["found"] is False


def test_web_search_soft_fails_on_non_dict_body(monkeypatch):
    monkeypatch.setenv("TAVILEY_API_KEY", "x")
    monkeypatch.setattr(ws, "_load_env", lambda: None)
    monkeypatch.setattr(ws.urllib.request, "urlopen",
                        lambda *a, **k: FakeResp(["not", "a", "dict"]))
    out = ws.web_search("아무거나")
    assert out["found"] is False


def test_web_search_passes_certifi_ssl_context(monkeypatch):
    import ssl
    monkeypatch.setenv("TAVILEY_API_KEY", "x")
    monkeypatch.setattr(ws, "_load_env", lambda: None)
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["context"] = context
        return FakeResp({"results": [{"title": "t", "url": "u", "content": "c"}]})

    monkeypatch.setattr(ws.urllib.request, "urlopen", fake_urlopen)
    out = ws.web_search("q")
    assert isinstance(captured["context"], ssl.SSLContext)
    assert out["found"] is True
