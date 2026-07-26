"""chunk_size·overlap·k 파라미터 스윕. `uv run python eval/sweep.py`

eval_retrieval의 GOLD셋을 그대로 재활용해, 청킹 파라미터를 바꿔가며
recall@k / MRR / top-1 category 정확도가 어떻게 달라지는지 표로 뽑는다.

프로덕션 인덱스(data/faiss_concept)는 건드리지 않는다 — 조합마다 in-memory FAISS를
새로 빌드한다. 임베딩 API를 조합 수만큼 호출하니 (청크 임베딩 + 질문 22개) 네트워크/키가 필요하다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_community.vectorstores import FAISS  # noqa: E402
from langchain_community.vectorstores.utils import DistanceStrategy  # noqa: E402
from langchain_upstage import UpstageEmbeddings  # noqa: E402

from etf_agent.agent import _load_env  # noqa: E402
from etf_agent.embed_corpus import EMBED_MODEL, build_documents  # noqa: E402

from eval_retrieval import GOLD  # noqa: E402  같은 폴더, 골드셋 재활용

# (chunk_size, overlap). 1000/150이 현재 프로덕션 값 — 나머지와 비교한다.
CHUNK_CONFIGS = [(400, 100), (700, 150), (1000, 150), (1500, 200)]
KS = [1, 3, 5]
DEPTH = 20  # MRR/recall 계산용 랭킹 깊이


def rank_of(vs, query, expected_sources):
    """정답 출처가 처음 등장하는 순위(1-based). 없으면 None."""
    ranked = vs.similarity_search_with_score(query, k=min(DEPTH, vs.index.ntotal))
    srcs = [d.metadata["source"] for d, _ in ranked]
    top1_cat = ranked[0][0].metadata["category"]
    rank = next((i + 1 for i, s in enumerate(srcs) if s in expected_sources), None)
    return rank, top1_cat


def evaluate(vs):
    ranks, cat_ok = [], 0
    for q, expected_sources, expected_cat in GOLD:
        rank, top1_cat = rank_of(vs, q, expected_sources)
        ranks.append(rank)
        cat_ok += top1_cat == expected_cat
    return ranks, cat_ok


def recall_at(ranks, k):
    return sum(1 for r in ranks if r and r <= k)


def mrr(ranks):
    return sum((1 / r) for r in ranks if r) / len(ranks)


def main() -> int:
    _load_env()
    emb = UpstageEmbeddings(model=EMBED_MODEL)
    n = len(GOLD)
    header = f"{'chunk/ovl':>11} {'#chunks':>8} " + " ".join(f"R@{k}".rjust(7) for k in KS) + f" {'MRR':>7} {'cat@1':>7}"
    print(header)
    print("=" * len(header))
    for cs, ov in CHUNK_CONFIGS:
        docs = build_documents(chunk_size=cs, chunk_overlap=ov)
        vs = FAISS.from_documents(docs, emb, distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)
        ranks, cat_ok = evaluate(vs)
        cells = " ".join(f"{recall_at(ranks, k)}/{n}".rjust(7) for k in KS)
        tag = f"{cs}/{ov}"
        star = " *" if (cs, ov) == (1000, 150) else ""
        print(f"{tag:>11} {len(docs):>8} {cells} {mrr(ranks):>7.3f} {f'{cat_ok}/{n}':>7}{star}")
    print("\n* = 현재 프로덕션 값. R@k=recall@k, cat@1=top-1 category 정확도.")
    return 0


if __name__ == "__main__":
    # ponytail: 지표 계산 자체 점검 (임베딩 없이)
    assert recall_at([1, 2, None, 5], 3) == 2
    assert abs(mrr([1, 2, None]) - (1 + 0.5) / 3) < 1e-9
    raise SystemExit(main())
