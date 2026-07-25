"""langchain FAISS 개념 검색. embed_corpus가 저장한 인덱스를 로드해 top-k 발췌를 반환한다.

RAG 검색 계층: UpstageEmbeddings로 질문 임베딩 -> langchain FAISS similarity_search_with_score.
인덱스는 정규화+내적(MAX_INNER_PRODUCT)이라 점수 = 코사인 유사도 (높을수록 유사).
검색 결과를 search_concepts 도구로 감싸 function-calling 에이전트에 노출한다.
"""
from pathlib import Path

INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "faiss_concept"
# 관련도 하한(값싼 1차 게이트). 프롬프트로도 막지만 solar-pro3는 부정 규칙에 약해 코드로 강제한다.
# 재측정(69청크, 섹터/전략 추가): 정답 top1 최저 0.39(상장폐지)~0.42(모멘텀), 오프토픽 비트코인 0.27·날씨 0.18.
# 예외 누수: "미국 기준금리 몇 %"=0.374 (금리-섹터 상관 페이지와 어휘 겹침). 상한을 0.38로 올리면
# 이걸 막지만 실제 골드 0.39가 0.01 마진에 걸려 더 취약 → 0.35 유지, 이 누수는 LLM 관련성 판단(2차 게이트)에 맡긴다.
MIN_SCORE = 0.35

_vs = None


def _store():
    """langchain FAISS 벡터스토어를 로드해 캐시한다 (첫 호출 때 1회)."""
    global _vs
    if _vs is not None:
        return _vs
    from langchain_community.vectorstores import FAISS
    from langchain_upstage import UpstageEmbeddings

    from .agent import _load_env  # 지연 임포트: agent -> tools -> retrieval 순환 회피
    if not (INDEX_DIR / "index.faiss").exists():
        raise RuntimeError("FAISS 인덱스가 없습니다. "
                           "`uv run python -m etf_agent.embed_corpus`를 먼저 실행하세요.")
    _load_env()
    _vs = FAISS.load_local(str(INDEX_DIR), UpstageEmbeddings(model="solar-embedding-1-large"),
                           allow_dangerous_deserialization=True)  # 우리가 만든 인덱스라 안전
    return _vs


def search_ranked(query: str, k: int | None = None):
    """(Document, score) 목록을 유사도 내림차순으로. eval이 recall/MRR에 쓴다."""
    vs = _store()
    k = k or vs.index.ntotal
    return vs.similarity_search_with_score(query, k=k)


def search_concepts(query: str, k: int = 3) -> dict:
    """ETF 개념·세금·위험·섹터특성·전략 질문을 문서 코퍼스에서 검색해 근거 발췌를 반환한다.

    환헤지, 추적오차, 괴리율, 총보수(TER), 분배금, LP/AP, 해외 ETF 양도소득세,
    레버리지·인버스 위험, 상장폐지 요건 등 '용어의 뜻'이나 '제도',
    그리고 경기민감/방어 섹터·금리와 섹터 상관·듀얼 모멘텀 전략 등 '섹터 특성·전략'을
    묻는 질문에 사용한다. 개별 주식·암호화폐·시장 전망에는 사용하지 않는다.

    Args:
        query: 사용자의 질문 그대로 (예: "환헤지 ETF의 H가 무슨 뜻이야?").
        k: 반환할 발췌 수. 기본 3, 최대 8.
    """
    k = max(1, min(k, 8))
    hits = search_ranked(query, k)
    if not hits or float(hits[0][1]) < MIN_SCORE:
        return {"found": False, "reason": "관련 문서를 찾지 못했습니다. (제공된 코퍼스 범위 밖)"}
    chunks = [{"source": d.metadata["source"], "section": d.metadata["section"],
               "page": d.metadata["page"], "category": d.metadata["category"],
               "text": d.page_content, "score": round(float(score), 3)}
              for d, score in hits[:k]]
    return {"found": True, "query": query, "chunks": chunks}


if __name__ == "__main__":  # ponytail: 검색 계층 자체 점검 (assert, 프레임워크 없음)
    out = search_concepts("환헤지 ETF의 (H)가 무슨 뜻이야?")
    assert out["found"], out
    top = out["chunks"][0]
    assert "환헤지" in top["source"], f"기대: 환헤지 출처, 실제: {top['source']}"
    assert top["score"] >= MIN_SCORE, f"top 유사도가 너무 낮다: {top['score']}"
    off = search_concepts("비트코인 살까?")
    assert not off["found"], f"오프토픽이 통과됐다: {off}"
    print(f"OK — top: {top['source']} p{top['page']} (score {top['score']}) · 오프토픽 차단 확인")
