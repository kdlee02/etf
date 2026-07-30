"""라우터 분류기 + 웹 답변 노드 단위 테스트 (FakeClient, 네트워크 없음)."""
import json
from types import SimpleNamespace as NS

import pytest

from etf_agent import agent
import etf_agent.websearch as ws


class FakeMessage:
    def __init__(self, content=None):
        self.content = content


class FakeClient:
    def __init__(self, *messages):
        self._queue = list(messages)
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        return NS(choices=[NS(message=self._queue.pop(0))])


@pytest.fixture
def fake(monkeypatch):
    def install(*messages):
        monkeypatch.setattr(agent, "_client", lambda: FakeClient(*messages))
    return install


def test_classify_routes_offtopic_to_web(fake):
    fake(FakeMessage(content="web"))
    assert agent._classify("비트코인 살까?") == "web"


def test_classify_routes_etf_to_scoped(fake):
    fake(FakeMessage(content="scoped"))
    assert agent._classify("한국 ETF 섹터 비중 알려줘") == "scoped"


def test_classify_defaults_to_scoped_on_garbage(fake):
    fake(FakeMessage(content="음 잘 모르겠어요"))
    assert agent._classify("???") == "scoped"


def test_run_web_composes_and_disclaims(fake, monkeypatch):
    monkeypatch.setattr(ws, "web_search",
                        lambda q: {"found": True, "query": q,
                                   "results": [{"title": "t", "url": "u", "content": "c"}]})
    fake(FakeMessage(content="사실 요약입니다."))
    ans = agent._run_web("비트코인 시세")
    assert "웹에서 검색" in ans.text
    assert "투자 권유가 아닙니다" in ans.text
    assert ans.tool_calls[0].name == "web_search"
    assert ans.tool_calls[0].result["found"] is True


def test_run_web_soft_fails_when_search_empty(monkeypatch):
    monkeypatch.setattr(ws, "web_search", lambda q: {"found": False, "reason": "x"})
    ans = agent._run_web("비트코인")  # 모델 호출 없음(조기 반환)
    assert "투자 권유가 아닙니다" in ans.text
    assert ans.tool_calls[0].result["found"] is False
