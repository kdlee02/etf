"""Tavily 웹검색. tools.py 규칙대로 절대 raise 하지 않는다.

transitive `requests` 대신 stdlib urllib 사용 (신규/전이 의존성 회피).
"""
import json
import os
import ssl
import urllib.request

import certifi

_ENDPOINT = "https://api.tavily.com/search"
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _load_env() -> None:
    from .agent import _load_env as _le  # 지연 임포트: 순환 회피
    _le()


def web_search(query: str) -> dict:
    """오프토픽 질문을 웹에서 검색해 상위 결과를 반환한다.

    Args:
        query: 사용자 질문 그대로.
    """
    _load_env()
    key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVILEY_API_KEY")  # 올바른 철자 우선, 기존 오타 폴백
    if not key:
        return {"found": False, "reason": "TAVILY_API_KEY가 없습니다."}
    body = json.dumps({"api_key": key, "query": query,
                       "max_results": 5, "search_depth": "basic"}).encode()
    req = urllib.request.Request(_ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
    except (OSError, ValueError) as e:
        return {"found": False, "reason": f"웹검색 실패: {type(e).__name__}"}
    if not isinstance(data, dict):
        return {"found": False, "reason": "웹검색 응답 형식 오류"}
    results = [{"title": r.get("title", ""), "url": r.get("url", ""),
                "content": r.get("content", "")}
               for r in data.get("results", [])]
    if not results:
        return {"found": False, "reason": "웹검색 결과 없음"}
    return {"found": True, "query": query, "results": results}
