"""Retrieval 실험. `uv run python eval/eval_retrieval.py [-k 3]`

에이전트가 아니라 **검색 계층만** 본다: 질문 -> solar-embedding -> FAISS top-k.
앱이 쓰는 것과 **동일한 FAISS 인덱스**(etf_agent.retrieval)를 그대로 호출한다 — eval이 곧 프로덕션.
판정: (1) recall@k — top-k 안에 정답 출처가 들어왔나, (2) MRR — 정답이 몇 등에 왔나,
(3) top-1 category 정확도. 골드셋엔 일부러 어려운 케이스(용어 구분, 위험 vs 개념 경계)를 섞었다.

LangSmith 불필요 — 40청크 검증은 이 스크립트로 끝난다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_agent import retrieval  # noqa: E402

# 골드셋: (질문, 정답 출처 후보, 기대 category). 출처는 하나라도 top-k에 들면 hit.
GOLD = [
    ("해외 상장 ETF 팔면 양도소득세 얼마 내?", ["국세청 해외주식과세", "미래에셋 해외ETF 세금"], "tax"),
    ("해외 ETF 양도세 기본공제 250만원 맞아?", ["국세청 해외주식과세", "미래에셋 해외ETF 세금"], "tax"),
    ("국내상장 해외ETF랑 해외상장 ETF 세금 뭐가 달라?", ["미래에셋 해외ETF 세금"], "tax"),
    ("연금계좌로 ETF 사면 세금 이연돼?", ["미래에셋 해외ETF 세금"], "tax"),
    ("ETF 배당받으면 종합과세 되나?", ["국세청 해외주식과세", "미래에셋 해외ETF 세금"], "tax"),
    ("환헤지 ETF의 (H) 표시가 무슨 뜻이야?", ["미래에셋 환헤지 ETF"], "concept"),
    ("환헤지 비용은 어떻게 발생해?", ["미래에셋 환헤지 ETF"], "concept"),
    ("추적오차랑 괴리율 차이가 뭐야?", ["금감원 ETF 용어", "HKEX ETF 핸드북"], "concept"),
    ("분배금이 뭐고 분배락은 뭐야?", ["금감원 ETF 용어"], "concept"),
    ("ETF 총보수(TER)는 뭘 포함해?", ["금감원 ETF 용어", "HKEX ETF 핸드북", "HKEX 용어사전"], "concept"),
    ("LP랑 AP가 ETF에서 무슨 역할이야?", ["HKEX ETF 핸드북", "HKEX 용어사전"], "concept"),
    ("레버리지 ETF 음의 복리효과가 뭐야?", ["신한 파생ETF 위험고지", "HKEX ETF 핸드북"], "risk"),
    ("인버스 ETF 오래 들고 있으면 왜 위험해?", ["신한 파생ETF 위험고지", "HKEX ETF 핸드북"], "risk"),
    ("ETF가 상장폐지되는 조건이 뭐야?", ["하나로 상장폐지 요건"], "risk"),
    ("순자산 50억 밑으로 떨어지면 상장폐지돼?", ["하나로 상장폐지 요건"], "risk"),
    # 대신 ETF투어가이드③ — 섹터 특성 + 듀얼 모멘텀 전략
    ("듀얼 모멘텀 전략이 뭐야?", ["대신 ETF투어가이드③"], "strategy"),
    ("절대 모멘텀이랑 상대 모멘텀 차이가 뭐야?", ["대신 ETF투어가이드③"], "strategy"),
    ("섹터 듀얼 모멘텀 백테스트 성과가 어때?", ["대신 ETF투어가이드③"], "strategy"),
    ("경기에 민감한 섹터는 뭐가 있어?", ["대신 ETF투어가이드③"], "sector"),
    ("금리 오르면 어떤 섹터가 강해?", ["대신 ETF투어가이드③"], "sector"),
    ("달러 강세일 때 유리한 섹터는?", ["대신 ETF투어가이드③"], "sector"),
    ("GICS는 몇 개 섹터로 나뉘어?", ["대신 ETF투어가이드③"], "sector"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=3, help="top-k")
    args = ap.parse_args()

    print(f"top-{args.k}\n" + "=" * 60)

    hits, rr_sum, cat_ok = 0, 0.0, 0
    for q, expected_sources, expected_cat in GOLD:
        ranked = retrieval.search_ranked(q)  # 앱과 동일한 langchain FAISS: (Document, score) 내림차순
        srcs = [d.metadata["source"] for d, _ in ranked]

        # recall@k + MRR (정답 출처가 처음 등장하는 순위)
        rank = next((i + 1 for i, s in enumerate(srcs) if s in expected_sources), None)
        hit = rank is not None and rank <= args.k
        hits += hit
        rr_sum += (1 / rank) if rank else 0
        top_doc, top_score = ranked[0]
        top1_cat = top_doc.metadata["category"]
        cat_ok += top1_cat == expected_cat

        mark = "✅" if hit else "❌"
        print(f"{mark} @{rank if rank else '>'+str(len(srcs))}  cat={top1_cat}{'' if top1_cat==expected_cat else '≠'+expected_cat}  "
              f"| {q}")
        print(f"     top1: [{top1_cat}] {top_doc.metadata['source']} p{top_doc.metadata['page']} ({top_score:.3f})")
        if not hit:
            print(f"     기대 출처: {expected_sources} — top-{args.k}에 없음")

    n = len(GOLD)
    print("=" * 60)
    print(f"recall@{args.k}: {hits}/{n} ({hits/n*100:.0f}%)  |  "
          f"MRR: {rr_sum/n:.3f}  |  top-1 category: {cat_ok}/{n} ({cat_ok/n*100:.0f}%)")
    return 0 if hits == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
