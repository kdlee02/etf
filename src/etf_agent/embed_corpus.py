"""PDF 코퍼스 -> 청킹 -> UpstageEmbeddings -> langchain FAISS 인덱스(data/faiss_concept).

`uv run python -m etf_agent.embed_corpus`. 멱등: 재실행하면 인덱스를 덮어쓴다.

langchain RAG 파이프라인: 문서 로드(pdfplumber) -> 분할(RecursiveCharacterTextSplitter)
-> 임베딩(UpstageEmbeddings) -> 벡터스토어(FAISS.from_documents) -> 디스크 저장(save_local).
페이지 선별(MANIFEST)과 contextual 헤더는 검색 품질이라 유지 — 표가 반토막 나지 않게 페이지 단위,
긴 페이지만 splitter가 쪼갠다. 헤더 "[출처 · 섹션]"은 분할 후에도 각 조각에 붙인다.
"""
import re
from pathlib import Path

import pdfplumber
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_upstage import UpstageEmbeddings

from .agent import _load_env

CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus"
INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "faiss_concept"
EMBED_MODEL = "solar-embedding-1-large"  # UpstageEmbeddings가 passage/query 변형을 자동 처리

# (파일, 사용할 페이지(1-based), category, 출처 표기). 페이지 선별은 실측으로 확정됨.
MANIFEST = [
    ("국세청_해외주식과세_22p.pdf", [5, 6, 8, 9, 15, 17], "tax", "국세청 해외주식과세"),
    ("미래에셋_해외ETF세금_국내외비교_4p.pdf", [1, 2, 3, 4], "tax", "미래에셋 해외ETF 세금"),
    ("미래에셋_환헤지ETF_8p.pdf", [2, 3, 4], "concept", "미래에셋 환헤지 ETF"),
    ("HKEX_ETF핸드북_KR_54p.pdf",
     [7, 8, 9, 13, 14, 15, 16, 21, 25, 26, 31, 32, 33, 34, 35, 37], "concept", "HKEX ETF 핸드북"),
    ("HKEX_ETF핸드북_KR_54p.pdf", [27], "risk", "HKEX ETF 핸드북"),      # 레버리지·인버스
    ("HKEX_ETF핸드북_KR_54p.pdf", [49, 50, 51], "concept", "HKEX 용어사전"),
    ("금감원_ETF용어_6p.pdf", [3, 4, 5], "concept", "금감원 ETF 용어"),
    ("신한_파생ETF위험고지서_5p.pdf", [3, 4, 5], "risk", "신한 파생ETF 위험고지"),
    ("하나로_일괄신고서_상장폐지요건_63p.pdf", [11], "risk", "하나로 상장폐지 요건"),
    # 대신 ETF Tour Guide ③. 티커 리스트(p13-14,25-35)·백테스트 상세 17장(p40-56)·시점 스냅샷(p59-60) 제외.
    ("대신_ETF투어가이드3_섹터모멘텀_61p.pdf",
     [12, 15, 16, 18, 19, 21, 22, 24], "sector", "대신 ETF투어가이드③"),   # GICS·섹터 경기/금리/달러 민감도
    ("대신_ETF투어가이드3_섹터모멘텀_61p.pdf",
     [38, 39, 57, 58], "strategy", "대신 ETF투어가이드③"),                  # 듀얼 모멘텀 정의·방법론·백테스트 요약
]

# 긴 페이지만 쪼갠다. 대부분 페이지는 이보다 짧아 통째로 남는다(표 보존).
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000, chunk_overlap=150, length_function=len,
    separators=["\n\n", "\n", " ", ""])


def _section(page_text: str) -> str:
    """페이지 첫 의미 있는 줄 = 섹션명. 인용에 쓴다."""
    for line in page_text.splitlines():
        line = line.strip()
        if len(line) >= 4 and not line.isdigit():
            return re.sub(r"\s+", " ", line)[:40]
    return ""


def build_documents() -> list[Document]:
    docs = []
    for fname, pages, category, source in MANIFEST:
        with pdfplumber.open(CORPUS / fname) as pdf:
            for pno in pages:
                text = (pdf.pages[pno - 1].extract_text() or "").strip()
                if not text:
                    continue
                section = _section(text)
                header = f"[{source} · {section}]"  # contextual: 조각이 자기 출처·섹션을 알게
                meta = {"source": source, "section": section, "page": pno, "category": category}
                for piece in _splitter.split_text(text):
                    docs.append(Document(page_content=f"{header}\n{piece}", metadata=meta))
    return docs


def main() -> int:
    _load_env()  # UPSTAGE_API_KEY
    docs = build_documents()
    print(f"청크 {len(docs)}개 생성 — 임베딩·인덱싱 중…")
    embeddings = UpstageEmbeddings(model=EMBED_MODEL)
    # UpstageEmbeddings는 단위벡터를 돌려주므로 내적 = 코사인 유사도. 점수 체계가 기존과 일치(0.35 하한 유효).
    vs = FAISS.from_documents(docs, embeddings, distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)
    vs.save_local(str(INDEX_DIR))
    by_cat: dict[str, int] = {}
    for d in docs:
        by_cat[d.metadata["category"]] = by_cat.get(d.metadata["category"], 0) + 1
    print(f"완료: {len(docs)}청크 -> {INDEX_DIR} 저장 · 카테고리별 {by_cat}")
    return 0 if docs else 1


if __name__ == "__main__":
    raise SystemExit(main())
