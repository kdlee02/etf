"""langchain FAISS 개념 검색. embed_corpus가 저장한 인덱스를 로드해 top-k 발췌를 반환한다.

RAG 검색 계층: UpstageEmbeddings로 질문 임베딩 -> langchain FAISS similarity_search_with_score.
인덱스는 정규화+내적(MAX_INNER_PRODUCT)이라 점수 = 코사인 유사도 (높을수록 유사).
검색 결과를 search_concepts 도구로 감싸 function-calling 에이전트에 노출한다.
"""
import re
from pathlib import Path

INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "faiss_concept"
# 관련도 하한(값싼 1차 게이트). 프롬프트로도 막지만 solar-pro3는 부정 규칙에 약해 코드로 강제한다.
# 재측정(69청크, 섹터/전략 추가): 정답 top1 최저 0.39(상장폐지)~0.42(모멘텀), 오프토픽 비트코인 0.27·날씨 0.18.
# 예외 누수: "미국 기준금리 몇 %"=0.374 (금리-섹터 상관 페이지와 어휘 겹침). 상한을 0.38로 올리면
# 이걸 막지만 실제 골드 0.39가 0.01 마진에 걸려 더 취약 → 0.35 유지, 이 누수는 LLM 관련성 판단(2차 게이트)에 맡긴다.
MIN_SCORE = 0.35
# top1이 이 이상이면 명백한 정답 → grader(solar ~2.7s) 건너뛴다. 누수(기준금리 0.377 등)는
# 이 아래라 계속 grade돼 차단 유지. 정답/누수가 겹치는 0.37~0.42 애매 구간만 grader에 맡긴다.
# ponytail: 유사도 기반 값싼 게이트. 코퍼스 커져 강한-정답 오탐이 생기면 이 상한을 올린다.
GRADE_BYPASS = 0.50

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


def _grade(query: str, chunks: list[dict]) -> list[dict]:
    """벡터 유사도가 통과시킨 발췌 중 질문에 실제로 관련된 것만 남긴다 (2차 게이트, CRAG).

    벡터 점수는 어휘 겹침에 속는다("미국 기준금리 몇 %"가 금리-섹터 페이지에 0.37로 걸림).
    관련성은 의미 판단이라 한 번의 배치 LLM 콜로 전체를 채점한다. 채점 실패 시 원본 유지(안전 쪽).
    """
    from .agent import MODEL, _client  # 지연 임포트: agent -> tools -> retrieval 순환 회피
    from .prompts import GRADER_INSTRUCTION
    listing = "\n".join(f"[{i}] {c['text'][:500]}" for i, c in enumerate(chunks))
    resp = _client().chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": GRADER_INSTRUCTION},
                  {"role": "user", "content": f"질문: {query}\n\n발췌:\n{listing}"}])
    body = (resp.choices[0].message.content or "").strip().lower()
    if body.startswith("none"):
        return []
    keep = {int(n) for n in re.findall(r"\d+", body) if int(n) < len(chunks)}
    return [c for i, c in enumerate(chunks) if i in keep] if keep else chunks


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
    # text 600자 캡: 모델 컨텍스트를 줄여 생성 지연 단축(원문 ~800자 → prefill 감소). 정의는 앞부분에
    # 몰려 있어 인용엔 충분. UI 근거 패널도 이 발췌를 보여준다. ponytail: 정답이 잘리면 상한을 올린다.
    chunks = [{"source": d.metadata["source"], "section": d.metadata["section"],
               "page": d.metadata["page"], "category": d.metadata["category"],
               "text": d.page_content[:600], "score": round(float(score), 3)}
              for d, score in hits[:k]]
    # top1이 충분히 강하면 grader 생략(지연 절감). 애매 구간만 LLM 2차 게이트로.
    graded = chunks if float(hits[0][1]) >= GRADE_BYPASS else _grade(query, chunks)
    if not graded:
        return {"found": False, "reason": "관련 문서를 찾지 못했습니다. (제공된 코퍼스 범위 밖)"}
    return {"found": True, "query": query, "chunks": graded}


if __name__ == "__main__":  # ponytail: 검색 계층 자체 점검 (assert, 프레임워크 없음)
    out = search_concepts("환헤지 ETF의 (H)가 무슨 뜻이야?")
    assert out["found"], out
    top = out["chunks"][0]
    assert "환헤지" in top["source"], f"기대: 환헤지 출처, 실제: {top['source']}"
    assert top["score"] >= MIN_SCORE, f"top 유사도가 너무 낮다: {top['score']}"
    off = search_concepts("비트코인 살까?")
    assert not off["found"], f"오프토픽이 통과됐다: {off}"
    # 벡터가 0.37로 통과시키던 누수(retrieval.py 주석) — 2차 게이트(_grade)가 막아야 한다
    leak = search_concepts("미국 기준금리는 지금 몇 %야?")
    assert not leak["found"], f"grader가 금리 누수를 못 막음: {leak}"
    print(f"OK — top: {top['source']} p{top['page']} (score {top['score']}) · 오프토픽·금리누수 차단 확인")
