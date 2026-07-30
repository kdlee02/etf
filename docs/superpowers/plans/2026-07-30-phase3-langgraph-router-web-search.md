# Phase 3 — langgraph 라우터 + Tavily 웹검색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자 질문을 langgraph 라우터로 분류해, 스코프 내는 기존 tool 루프로, 스코프 밖은 Tavily 웹검색으로 답한다.

**Architecture:** 새 `graph.py`가 `classify → [scoped_agent | web_agent]` StateGraph를 구성한다. `agent.py`의 기존 tool 루프는 `_run_scoped()`로 추출해 노드로 재사용하고, `ask()` 시그니처는 유지해 `app.py`·eval을 안 건드린다. 오프토픽은 tool 루프에 진입하지 않아 기존 `ac4` 증상(무관 도구 poke)이 사라진다.

**Tech Stack:** Python 3.11–3.13, langgraph, openai(호환 Solar), langchain FAISS(기존), stdlib urllib(Tavily REST), pytest.

## Global Constraints

- Python: `uv` only. `uv run` / `uv add`. pip·conda 금지.
- 도구/검색 함수는 **절대 raise 하지 않는다.** 실패 시 `{"found": False, "reason": ...}` 반환.
- 컴플라이언스: 모든 답변 끝에 `투자 권유가 아닙니다.` — 코드(`_with_disclaimer`)로 보장.
- 새 의존성 최소화: Tavily는 이미 lock된 것으로 처리하되 **transitive `requests` 대신 stdlib `urllib`** 사용. langgraph만 신규 추가.
- API 키 이름은 `.env`의 `TAVILEY_API_KEY`(철자 그대로).
- 모델 상수: `MODEL = "solar-pro3"`, temperature 0.
- 테스트는 라이브 Solar 없이 `FakeClient`(OpenAI 응답 모양 흉내)로. 네트워크 호출은 monkeypatch.

---

### Task 1: langgraph 의존성 추가

**Files:**
- Modify: `pyproject.toml` (dependencies)

**Interfaces:**
- Produces: `langgraph` import 가능.

- [ ] **Step 1: 의존성 추가**

Run: `uv add langgraph`

- [ ] **Step 2: import 확인**

Run: `uv run python -c "from langgraph.graph import StateGraph, START, END; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: langgraph 의존성 추가 (Phase 3 라우터)"
```

---

### Task 2: websearch.py — Tavily REST 래퍼

**Files:**
- Create: `src/etf_agent/websearch.py`
- Test: `tests/test_websearch.py`

**Interfaces:**
- Produces: `web_search(query: str) -> dict`
  - 성공: `{"found": True, "query": str, "results": [{"title": str, "url": str, "content": str}, ...]}`
  - 실패/무결과/키없음: `{"found": False, "reason": str}`
  - **절대 raise 하지 않는다.**

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_websearch.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_websearch.py -v`
Expected: FAIL — `ModuleNotFoundError: etf_agent.websearch`

- [ ] **Step 3: websearch.py 구현**

`src/etf_agent/websearch.py`:
```python
"""Tavily 웹검색. tools.py 규칙대로 절대 raise 하지 않는다.

transitive `requests` 대신 stdlib urllib 사용 (신규/전이 의존성 회피).
"""
import json
import os
import urllib.error
import urllib.request

_ENDPOINT = "https://api.tavily.com/search"


def _load_env() -> None:
    from .agent import _load_env as _le  # 지연 임포트: 순환 회피
    _le()


def web_search(query: str) -> dict:
    """오프토픽 질문을 웹에서 검색해 상위 결과를 반환한다.

    Args:
        query: 사용자 질문 그대로.
    """
    _load_env()
    key = os.environ.get("TAVILEY_API_KEY")
    if not key:
        return {"found": False, "reason": "TAVILEY_API_KEY가 없습니다."}
    body = json.dumps({"api_key": key, "query": query,
                       "max_results": 5, "search_depth": "basic"}).encode()
    req = urllib.request.Request(_ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"found": False, "reason": f"웹검색 실패: {type(e).__name__}"}
    results = [{"title": r.get("title", ""), "url": r.get("url", ""),
                "content": r.get("content", "")}
               for r in data.get("results", [])]
    if not results:
        return {"found": False, "reason": "웹검색 결과 없음"}
    return {"found": True, "query": query, "results": results}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_websearch.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/etf_agent/websearch.py tests/test_websearch.py
git commit -m "feat: Tavily 웹검색 래퍼 (urllib, raise 안 함)"
```

---

### Task 3: agent.py 리팩터 — tool 루프를 함수로 추출 (동작 불변)

기존 `ask()`의 본문을 `_run_scoped()`/`_run_ungrounded()`로 쪼갠다. **동작은 완전히 동일** — 기존 테스트가 수정 없이 통과해야 한다. `_bare_topic` 단락(short-circuit)을 `ask()` 최상단으로 올려, 이후 그래프가 붙어도 되묻기가 모델 호출 없이 끝나도록 한다.

**Files:**
- Modify: `src/etf_agent/agent.py:161-213` (`ask` 함수 전체)

**Interfaces:**
- Produces:
  - `_run_scoped(question: str) -> Answer` — 기존 tool 루프(단, bare_topic 제외).
  - `_run_ungrounded(question: str) -> Answer` — 도구 없는 단일 콜.
  - `ask(question: str, grounded: bool = True) -> Answer` — bare_topic 단락 후 `_run_scoped` 위임.

- [ ] **Step 1: 기존 테스트가 지금 통과하는지 기준선 확인**

Run: `uv run pytest tests/test_agent.py -v`
Expected: PASS (모두)

- [ ] **Step 2: `ask` 함수를 세 함수로 교체**

`src/etf_agent/agent.py`의 `def ask(...)`(현 161–213행) 전체를 아래로 교체:
```python
def _run_ungrounded(question: str) -> Answer:
    """도구 없이 답한다 — 일반 LLM 비교용(환각 시연)."""
    client = _client()
    messages = [{"role": "system", "content": UNGROUNDED_INSTRUCTION},
                {"role": "user", "content": question}]
    response = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
    return Answer(text=_with_disclaimer(response.choices[0].message.content or ""),
                  grounded=False)


def _run_scoped(question: str) -> Answer:
    """스코프 내 질문을 function-calling tool 루프로 답한다. (bare_topic은 ask에서 걸러진다.)"""
    client = _client()
    registry = {fn.__name__: fn for fn in TOOLS}
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": question},
    ]
    trace: list[ToolCall] = []
    schemas = [_schema(fn) for fn in TOOLS]
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=schemas,
            tool_choice="auto", parallel_tool_calls=True, temperature=0,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            text = _reground(message.content or "답변을 생성하지 못했습니다.", trace, client, messages)
            return Answer(text=_with_disclaimer(text), tool_calls=trace)

        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = registry.get(call.function.name)
            if fn is None:
                result = {"found": False, "reason": f"알 수 없는 도구: {call.function.name}"}
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"found": False, "reason": f"잘못된 인자: {e}"}
            trace.append(ToolCall(call.function.name, args, result))
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "name": call.function.name,
                             "content": json.dumps(result, ensure_ascii=False)})

    final = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
    text = _reground(final.choices[0].message.content or "답변을 생성하지 못했습니다.", trace, client, messages)
    return Answer(text=_with_disclaimer(text), tool_calls=trace)


def ask(question: str, grounded: bool = True) -> Answer:
    """질문에 답한다. grounded=False면 도구 없이 — 일반 LLM 비교용(환각 시연)."""
    if not grounded:
        return _run_ungrounded(question)
    if reask := _bare_topic(question):
        return Answer(text=_with_disclaimer(reask))  # 도구 없이 되묻는다 — 근거도 없다
    return _run_scoped(question)
```

- [ ] **Step 3: 기존 테스트 전부 통과 확인 (동작 불변 검증)**

Run: `uv run pytest tests/test_agent.py -v`
Expected: PASS (모두 — 수정 전과 동일)

- [ ] **Step 4: Commit**

```bash
git add src/etf_agent/agent.py
git commit -m "refactor: ask()를 _run_scoped/_run_ungrounded로 분리 (동작 불변)"
```

---

### Task 4: 분류기 + 웹 답변 노드 (agent.py + prompts.py)

**Files:**
- Modify: `src/etf_agent/prompts.py` (끝에 상수 2개 추가)
- Modify: `src/etf_agent/agent.py` (`_classify`, `_run_web` 추가)
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `web_search` (Task 2), `_client`/`_with_disclaimer`/`ToolCall`/`Answer`/`MODEL`.
- Produces:
  - `_classify(question: str) -> str` — `"web"` 또는 `"scoped"`(기본값).
  - `_run_web(question: str) -> Answer` — 웹 결과 기반 답변, `tool_calls=[ToolCall("web_search", ...)]`.
  - `ROUTER_INSTRUCTION`, `WEB_INSTRUCTION` (prompts.py).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_router.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_router.py -v`
Expected: FAIL — `AttributeError: module 'etf_agent.agent' has no attribute '_classify'`

- [ ] **Step 3: prompts.py에 상수 추가**

`src/etf_agent/prompts.py` 끝에 추가:
```python
# 라우터 분류기: 질문을 scoped(기존 도구) vs web(웹검색) 한 단어로 분류. 닫힌 선택지.
ROUTER_INSTRUCTION = """사용자 질문을 두 경로 중 하나로 분류하세요. 라벨 한 단어만 출력합니다.

- scoped: ETF, 국가·섹터 투자, ETF 개념·용어·세금·위험·전략에 관한 질문.
  예) "한국 ETF 섹터 비중", "환헤지가 뭐야", "해외 ETF 양도세", "반도체 비중 높은 나라"
- web: 그 외 전부 — 개별 주식, 암호화폐, 채권, 부동산, 시장 전망, 매수/매도 판단,
  시사·일반 상식. 예) "비트코인 살까?", "미국 기준금리 몇 %", "오늘 환율"

'scoped' 또는 'web', 이 한 단어만 출력하세요. 다른 말은 붙이지 마세요."""

# 웹 답변 작문: 검색 결과만 근거, 사실만, 매수/매도 조언 금지. 고지는 코드가 붙인다.
WEB_INSTRUCTION = """당신은 ETF 리서치 어시스턴트입니다. 아래 웹 검색 결과만 근거로
사용자 질문에 사실만 간결하게 답하세요.

- 검색 결과에 있는 내용만 쓰고, 없는 수치나 종목을 지어내지 마세요.
- 매수/매도 조언이나 "사세요/파세요" 같은 투자 판단은 하지 마세요. 사실만 전달합니다.
- 근거로 삼은 문장 끝에 출처를 (출처: URL) 형식으로 붙이세요.
- 한국어로 짧게."""
```

- [ ] **Step 4: agent.py에 `_classify`, `_run_web` 추가**

`src/etf_agent/agent.py` import 문에 `WEB_INSTRUCTION`, `ROUTER_INSTRUCTION`을 추가하고
(`from .prompts import SYSTEM_INSTRUCTION, UNGROUNDED_INSTRUCTION` → 넷 다 import),
`_run_scoped` 아래에 추가:
```python
def _classify(question: str) -> str:
    """질문을 'scoped' 또는 'web'으로 분류. 애매하면 scoped(안전 쪽 = 기존 동작 유지)."""
    client = _client()
    resp = client.chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": ROUTER_INSTRUCTION},
                  {"role": "user", "content": question}])
    label = (resp.choices[0].message.content or "").strip().lower()
    return "web" if "web" in label else "scoped"


def _run_web(question: str) -> Answer:
    """오프토픽 질문을 웹검색 결과로 답한다. 사실만 + 고지, 매수/매도 조언 금지."""
    from .websearch import web_search  # 지연 임포트: 순환 회피
    hits = web_search(question)
    trace = [ToolCall("web_search", {"query": question}, hits)]
    if not hits.get("found"):
        text = "제공된 데이터에 없어 웹에서 찾아봤지만 신뢰할 만한 결과를 얻지 못했습니다."
        return Answer(text=_with_disclaimer(text), tool_calls=trace)
    client = _client()
    ctx = json.dumps(hits["results"], ensure_ascii=False)
    resp = client.chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": WEB_INSTRUCTION},
                  {"role": "user", "content": f"질문: {question}\n\n웹 검색 결과:\n{ctx}"}])
    body = resp.choices[0].message.content or "검색 결과를 정리하지 못했습니다."
    text = f"🔎 웹에서 검색한 결과입니다.\n\n{body}"
    return Answer(text=_with_disclaimer(text), tool_calls=trace)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_router.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/etf_agent/agent.py src/etf_agent/prompts.py tests/test_router.py
git commit -m "feat: 라우터 분류기 _classify + 웹 답변 노드 _run_web"
```

---

### Task 5: graph.py — StateGraph 배선 + ask() 위임

**Files:**
- Create: `src/etf_agent/graph.py`
- Modify: `src/etf_agent/agent.py` (`ask` 마지막 줄: `_run_scoped` → `route`)
- Modify: `tests/test_agent.py` (스코프 경로 테스트에 classify 응답 prepend)

**Interfaces:**
- Consumes: `agent._classify`, `agent._run_scoped`, `agent._run_web` (Task 3·4).
- Produces: `route(question: str) -> Answer` — 컴파일된 그래프를 invoke.

- [ ] **Step 1: graph.py 구현**

`src/etf_agent/graph.py`:
```python
"""langgraph 라우터. classify로 질문을 나눠 scoped 도구 루프 또는 web 검색으로 보낸다.

노드는 agent의 함수(_classify/_run_scoped/_run_web)를 얇게 감싼다 — 로직은 agent에 있다.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agent import Answer, _classify, _run_scoped, _run_web


class RouterState(TypedDict, total=False):
    question: str
    route: str
    answer: Answer


def _classify_node(state: RouterState) -> dict:
    return {"route": _classify(state["question"])}


def _scoped_node(state: RouterState) -> dict:
    return {"answer": _run_scoped(state["question"])}


def _web_node(state: RouterState) -> dict:
    return {"answer": _run_web(state["question"])}


def _build():
    b = StateGraph(RouterState)
    b.add_node("classify", _classify_node)
    b.add_node("scoped", _scoped_node)
    b.add_node("web", _web_node)
    b.add_edge(START, "classify")
    b.add_conditional_edges("classify", lambda s: s["route"],
                            {"scoped": "scoped", "web": "web"})
    b.add_edge("scoped", END)
    b.add_edge("web", END)
    return b.compile()


_compiled = None


def route(question: str) -> Answer:
    global _compiled
    if _compiled is None:
        _compiled = _build()
    return _compiled.invoke({"question": question})["answer"]


if __name__ == "__main__":  # ponytail: 라우팅 자체 점검 (실 API 2콜)
    assert _classify("비트코인 살까?") == "web"
    assert _classify("한국 ETF 섹터 비중 알려줘") == "scoped"
    print("OK — classify 라우팅 확인 (web/scoped)")
```

- [ ] **Step 2: ask()가 그래프로 위임하도록 변경**

`src/etf_agent/agent.py`의 `ask` 마지막 줄 `return _run_scoped(question)`을 교체:
```python
    from .graph import route  # 지연 임포트: agent <-> graph 순환 회피
    return route(question)
```

- [ ] **Step 3: 기존 test_agent.py의 스코프 경로 테스트에 classify 응답 prepend**

이유: 이제 `ask()`가 scoped 경로에서 먼저 `_classify`를 호출한다. FakeClient 큐의 맨 앞에 분류기 응답(`FakeMessage(content="scoped")`)을 넣어야 한다. **아래 6개 테스트**의 `fake(...)` 호출에서, 첫 인자로 `FakeMessage(content="scoped")`를 추가한다:

- `test_tool_calls_are_paired_by_id`
- `test_tool_results_are_sent_back_with_matching_id`
- `test_no_tool_calls_returns_empty_trace`
- `test_unknown_tool_name_does_not_crash`
- `test_bad_arguments_do_not_crash`
- `test_malformed_json_arguments_do_not_crash`

예시(`test_tool_calls_are_paired_by_id`):
```python
    fake(
        FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
        FakeMessage(tool_calls=[tool_call("c1", "get_top_holdings", {"ticker": "EWY"}),
                                tool_call("c2", "get_sector_weights", {"ticker": "EWY"})]),
        FakeMessage(content="완료"),
    )
```

**건드리지 말 것:** `test_bare_topic_reasks_without_calling_the_model`(bare_topic이 그래프 전에 단락되어 모델 미호출 — 그대로 통과), `test_ungrounded_mode_sends_no_tools`(grounded=False, 그래프 우회), `_bare_topic`/`_ungrounded_tickers` 직접 호출 테스트.

- [ ] **Step 4: 단위 테스트 전부 통과 확인**

Run: `uv run pytest tests/test_agent.py tests/test_router.py tests/test_websearch.py tests/test_grounding.py -v`
Expected: PASS (모두)

- [ ] **Step 5: 라우팅 self-check (실 API)**

Run: `uv run python -m etf_agent.graph`
Expected: `OK — classify 라우팅 확인 (web/scoped)`

- [ ] **Step 6: Commit**

```bash
git add src/etf_agent/graph.py src/etf_agent/agent.py tests/test_agent.py
git commit -m "feat: langgraph 라우터 배선 + ask() 위임"
```

---

### Task 6: 증거 패널(charts) + eval ac4 재작성

**Files:**
- Modify: `src/etf_agent/charts.py` (`chart_for`에 web_search 분기)
- Modify: `eval/run_eval.py` (`check`에 forbid_tools + ac4 케이스 교체)

**Interfaces:**
- Consumes: `ToolCall(name="web_search", result={"found":True,"results":[...]})`.
- Produces: 증거 패널 우측에 웹 출처 표.

- [ ] **Step 1: charts.py에 web_search 분기 추가**

`src/etf_agent/charts.py`의 `chart_for` 끝, 마지막 `return None, None` 바로 위에 추가:
```python
    if call.name == "web_search":
        return None, [{"제목": r.get("title", ""), "출처": r.get("url", "")}
                      for r in result.get("results", [])]
```
(found:false web_search는 함수 상단의 not-found 가드에서 이미 `None, None`으로 조기 반환되므로 `result["results"]`는 안전하다.)

- [ ] **Step 2: eval check()에 forbid_tools 규칙 추가**

`eval/run_eval.py`의 `check` 함수, `expect_tools == []` 블록 다음에 추가:
```python
    for tool in case.get("forbid_tools", []):
        if tool in called:
            fails.append(f"부르면 안 되는 도구 호출됨: {tool}")
```

- [ ] **Step 3: ac4 케이스를 웹 라우팅 기준으로 교체**

`eval/run_eval.py`의 `ac4_out_of_corpus` 케이스(현 33–41행) 전체를 교체:
```python
    {
        # Phase 3: 오프토픽은 web으로 라우팅된다. 무관한 ETF 도구를 찌르지 않고,
        # 사실만 + 고지로 답하며, 매수/매도 조언은 하지 않는다.
        "id": "ac4_out_of_scope_web",
        "q": "비트코인 살까?",
        "expect_tools": ["web_search"],
        "forbid_tools": ["get_sector_weights", "get_sector_etf", "get_country_etfs",
                         "rank_countries_by_sector", "get_top_holdings"],
        "expect_text": ["웹", "투자 권유가 아닙니다"],
        "forbid_text": ["매수하세요", "사시는 것을 추천", "파세요"],
    },
```

- [ ] **Step 4: 기존 단위 테스트 회귀 확인**

Run: `uv run pytest -v`
Expected: PASS (모두 — charts/eval 변경은 단위 테스트에 영향 없음)

- [ ] **Step 5: Commit**

```bash
git add src/etf_agent/charts.py eval/run_eval.py
git commit -m "feat: 웹검색 출처 패널 + ac4 eval 웹 라우팅 기준으로 재작성"
```

---

### Task 7: 전체 검증

**Files:** 없음(검증 전용). 실패 시 해당 Task로 돌아가 수정.

- [ ] **Step 1: 전체 단위 테스트**

Run: `uv run pytest -v`
Expected: PASS (모두)

- [ ] **Step 2: 검색 계층 self-check (회귀)**

Run: `uv run python -m etf_agent.retrieval`
Expected: `OK — top: ... · 오프토픽 차단 확인`

- [ ] **Step 3: 라우팅 self-check**

Run: `uv run python -m etf_agent.graph`
Expected: `OK — classify 라우팅 확인 (web/scoped)`

- [ ] **Step 4: 라이브 스모크 — 오프토픽 웹 라우팅**

Run: `uv run python -m etf_agent.agent "비트코인 지금 얼마야?"`
Expected: `web_search` 호출 표시 + `🔎 웹에서 검색한 결과입니다` + `투자 권유가 아닙니다.`, 무관 ETF 도구 없음.

- [ ] **Step 5: 라이브 스모크 — 스코프 내 회귀**

Run: `uv run python -m etf_agent.agent "한국에 투자하는 ETF랑 주요 종목/섹터 알려줘"`
Expected: `get_country_etfs` 등 도구 호출 + EWY 등장 (기존 동작 유지).

- [ ] **Step 6: (선택) 전체 eval**

Run: `uv run python -m eval.run_eval`
Expected: 전 케이스 PASS (특히 `ac4_out_of_scope_web`).

- [ ] **Step 7: 최종 커밋(수정분 있으면)**

```bash
git add -A && git commit -m "test: Phase 3 전체 검증 통과"
```

---

## 검증 후 (플랜 밖, 유저 확인용)

- `docs/superpowers/specs/2026-07-30-phase3-...-design.md`의 "남은 할 일"·"알려진 제약"을 완료로 갱신할지, 메모리 `etf-agent-build-plan.md`를 Phase 3 완료로 업데이트할지 유저와 확인.
- `/code-review` (correctness) 1회 권장 — 새 surface이므로.
