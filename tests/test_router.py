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


def test_classify_routes_offdomain_asset_to_reject(fake):
    fake(FakeMessage(content="reject"))
    assert agent._classify("비트코인 살까?") == "reject"


def test_classify_routes_domain_fact_to_web(fake):
    fake(FakeMessage(content="web"))
    assert agent._classify("미국 기준금리 몇 %야?") == "web"


def test_classify_routes_etf_to_scoped(fake):
    fake(FakeMessage(content="scoped"))
    assert agent._classify("한국 ETF 섹터 비중 알려줘") == "scoped"


def test_classify_defaults_to_scoped_on_garbage(fake):
    fake(FakeMessage(content="음 잘 모르겠어요"))
    assert agent._classify("???") == "scoped"


def test_run_reject_refuses_without_calling_model_or_tools(fake):
    fake()  # 응답을 안 넣었다 — 모델을 부르면 FakeClient가 IndexError로 터진다
    ans = agent._run_reject("오늘 날씨 어때?")
    assert ans.tool_calls == []          # 근거 0회
    assert ans.grounded is False
    assert "거절" in ans.text
    assert agent.DISCLAIMER in ans.text


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


# --- 1번: retrieval grader (2차 게이트) ---
def _grade_with(monkeypatch, content):
    monkeypatch.setattr(agent, "_client",
                        lambda: FakeClient(FakeMessage(content=content)))


def test_grader_drops_irrelevant_chunk(monkeypatch):
    from etf_agent import retrieval
    _grade_with(monkeypatch, "0")  # 0번만 관련
    chunks = [{"text": "환헤지 설명"}, {"text": "무관한 금리 페이지"}]
    assert retrieval._grade("환헤지 뜻", chunks) == [chunks[0]]


def test_grader_none_returns_empty(monkeypatch):
    from etf_agent import retrieval
    _grade_with(monkeypatch, "none")  # 전부 무관 -> found:False로 이어짐
    assert retrieval._grade("미국 기준금리", [{"text": "금리-섹터 상관"}]) == []


def test_grader_keeps_all_on_malformed(monkeypatch):
    from etf_agent import retrieval
    _grade_with(monkeypatch, "잘 모르겠어요")  # 파싱 실패 -> 안전 쪽(원본 유지)
    chunks = [{"text": "a"}, {"text": "b"}]
    assert retrieval._grade("q", chunks) == chunks


# --- 2번: CRAG fallback 엣지 ---
def test_crag_falls_back_to_web_when_no_evidence():
    from etf_agent import graph
    empty = agent.Answer(text="근거 없음", tool_calls=[
        agent.ToolCall("search_concepts", {}, {"found": False})])
    assert graph._crag_fallback({"answer": empty}) == "web"


def test_crag_ends_when_evidence_present():
    from etf_agent import graph
    from langgraph.graph import END
    ok = agent.Answer(text="답", tool_calls=[
        agent.ToolCall("get_country_etfs", {}, {"found": True})])
    assert graph._crag_fallback({"answer": ok}) == END


# --- B: ask_stream 라우팅 (스트리밍) ---
def test_ask_stream_reject_emits_whole_text(fake):
    fake(FakeMessage(content="reject"))  # classify만 모델 호출, _run_reject는 호출 없음
    tokens = []
    ans = agent.ask_stream("오늘 날씨 어때?", on_token=tokens.append)
    assert "거절" in ans.text
    assert "".join(tokens) == ans.text  # 짧은 거절은 통째로 emit


def test_ask_stream_routes_scoped(monkeypatch):
    monkeypatch.setattr(agent, "_classify", lambda q: "scoped")
    sentinel = agent.Answer(text="ok", tool_calls=[agent.ToolCall("x", {}, {"found": True})])
    monkeypatch.setattr(agent, "_run_scoped", lambda q, on_token=None: sentinel)
    assert agent.ask_stream("한국 ETF", on_token=lambda t: None) is sentinel


def test_ask_stream_crag_falls_back_to_web(monkeypatch):
    monkeypatch.setattr(agent, "_classify", lambda q: "scoped")
    empty = agent.Answer(text="근거없음", tool_calls=[agent.ToolCall("x", {}, {"found": False})])
    web = agent.Answer(text="web답", tool_calls=[agent.ToolCall("web_search", {}, {"found": True})])
    monkeypatch.setattr(agent, "_run_scoped", lambda q, on_token=None: empty)
    monkeypatch.setattr(agent, "_run_web", lambda q, on_token=None: web)
    assert agent.ask_stream("한국 ETF", on_token=lambda t: None) is web
