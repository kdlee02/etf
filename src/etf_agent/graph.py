"""langgraph 라우터. classify로 질문을 나눠 scoped 도구 루프 또는 web 검색으로 보낸다.

노드는 agent의 함수(_classify/_run_scoped/_run_web)를 얇게 감싼다 — 로직은 agent에 있다.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agent import Answer, _classify, _run_reject, _run_scoped, _run_web


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


def _reject_node(state: RouterState) -> dict:
    return {"answer": _run_reject(state["question"])}


def _crag_fallback(state: RouterState) -> str:
    """스코프 경로가 근거를 하나도 못 얻으면 web으로 보정한다 (CRAG). 있으면 종료."""
    return "web" if not state["answer"].has_evidence else END


def _build():
    b = StateGraph(RouterState)
    b.add_node("classify", _classify_node)
    b.add_node("scoped", _scoped_node)
    b.add_node("web", _web_node)
    b.add_node("reject", _reject_node)
    b.add_edge(START, "classify")
    b.add_conditional_edges("classify", lambda s: s["route"],
                            {"scoped": "scoped", "web": "web", "reject": "reject"})
    b.add_conditional_edges("scoped", _crag_fallback, {"web": "web", END: END})
    b.add_edge("web", END)
    b.add_edge("reject", END)
    return b.compile()


_compiled = None


def route(question: str) -> Answer:
    global _compiled
    if _compiled is None:
        _compiled = _build()
    return _compiled.invoke({"question": question})["answer"]


if __name__ == "__main__":  # ponytail: 라우팅 자체 점검 (실 API)
    assert _classify("비트코인 살까?") == "reject"       # 범위 밖 자산 → 거절
    assert _classify("오늘 날씨 어때?") == "reject"       # 오프도메인 → 거절
    assert _classify("미국 기준금리 몇 %야?") == "web"    # 도메인 안 사실 → 웹
    assert _classify("한국 ETF 섹터 비중 알려줘") == "scoped"
    # 자연어 앱 예시: 투자 의도 말투가 섞여도 주제(국가/섹터)면 scoped여야 한다
    assert _classify("한국에 투자하는 ETF랑 주요 종목/섹터 알려줘") == "scoped"
    print("OK — classify 3-way 확인 (reject/web/scoped, 자연어 scoped 포함)")
