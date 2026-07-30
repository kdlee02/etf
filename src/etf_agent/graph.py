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
