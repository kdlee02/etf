"""라우터 분류 평가. `uv run python eval/eval_router.py [--runs N]`

에이전트가 아니라 **분류기만** 본다: 질문 -> _classify -> scoped/web/reject.
앱이 쓰는 것과 동일한 agent._classify를 그대로 호출한다 — eval이 곧 프로덕션
(eval_retrieval.py가 검색 계층에 대해 하는 것과 같은 원칙).

CI 아님 — _classify가 LLM 콜이라 네트워크와 API 쿼터가 필요하다.

지표 셋 중 **false-reject가 1급**이다: 답할 수 있는 질문을 거절하면 사용자는 기능이
없다고 판단하고 떠난다. scoped<->web 오분류는 CRAG 폴백이 사후 보정하므로 덜 아프다
(scoped로 잘못 가도 근거 0건이면 web으로 넘어간다). 그래서 셋을 같은 무게로 보지 않는다.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_agent import agent  # noqa: E402

ROUTES = ("scoped", "web", "reject")

# 골드셋: (질문, 기대 경로). 경계 케이스를 일부러 섞었다 —
# 투자 의도 말투인데 scoped, 도메인 안인데 코퍼스 밖이라 web, ETF처럼 보이지만 개별종목이라 reject.
GOLD = [
    # --- scoped: 구조화 도구로 답할 수 있다 ---
    ("한국 ETF 섹터 비중 알려줘", "scoped"),
    ("대만에 투자하는 ETF 뭐가 있어?", "scoped"),
    ("반도체 비중 높은 나라 순위 알려줘", "scoped"),
    ("EWY 상위 보유종목 알려줘", "scoped"),
    ("헬스케어 섹터 대표 ETF가 뭐야?", "scoped"),
    # 투자 의도 말투가 섞여도 주제(국가/섹터)면 scoped다 — d541d89에서 한 번 오라우팅됐던 형태
    ("한국에 투자하고 싶은데 주요 종목이랑 섹터 알려줘", "scoped"),
    ("중국 시장에 들어가려는데 어떤 ETF 보면 돼?", "scoped"),
    # --- scoped: RAG 코퍼스로 답할 수 있다 (개념·세금·위험·전략) ---
    ("환헤지 ETF의 (H)가 무슨 뜻이야?", "scoped"),
    ("해외 상장 ETF 양도소득세 얼마 내?", "scoped"),
    ("레버리지 ETF 음의 복리효과가 뭐야?", "scoped"),
    ("ETF 상장폐지 요건이 뭐야?", "scoped"),
    ("듀얼 모멘텀 전략 설명해줘", "scoped"),
    ("추적오차랑 괴리율 차이가 뭐야?", "scoped"),
    # --- web: ETF·투자 도메인 안이지만 도구·코퍼스에 없는 사실 ---
    ("미국 기준금리 몇 %야?", "web"),
    ("어제 S&P500 종가 얼마야?", "web"),
    ("올해 미국 CPI 발표치가 어떻게 나왔어?", "web"),
    ("최근 한국은행 금리 결정 어떻게 됐어?", "web"),
    ("달러 환율 지금 얼마야?", "web"),
    # --- reject: 범위 밖 ---
    ("비트코인 살까?", "reject"),
    ("이더리움 전망 어때?", "reject"),
    ("삼성전자 지금 사도 될까?", "reject"),
    ("테슬라 주가 오를까?", "reject"),
    ("오늘 날씨 어때?", "reject"),
    ("파이썬 리스트 정렬하는 법 알려줘", "reject"),
    ("강남 아파트 살까 말까?", "reject"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1, help="문항당 반복 횟수 (흔들림 측정용)")
    args = ap.parse_args()

    # confusion[(기대, 실제)] = 횟수
    confusion: Counter = Counter()
    misses: list[tuple[str, str, str]] = []

    print(f"라우터 골드셋 {len(GOLD)}문항 × {args.runs}회\n" + "=" * 62, flush=True)
    for run in range(args.runs):
        for question, expected in GOLD:
            try:
                actual = agent._classify(question)
            except Exception as e:  # 분류 실패도 오분류로 센다 (조용히 넘기면 지표가 거짓말한다)
                actual = f"ERROR:{type(e).__name__}"
            confusion[(expected, actual)] += 1
            if actual != expected:
                misses.append((question, expected, actual))
                print(f"✗ {expected:>6} → {actual:<6}  {question}", flush=True)

    n = len(GOLD) * args.runs
    correct = sum(c for (exp, act), c in confusion.items() if exp == act)

    # false-reject: 답할 수 있는 질문(scoped/web)을 reject로 보낸 비율 — 가장 아픈 오류
    answerable = sum(c for (exp, _), c in confusion.items() if exp != "reject")
    false_rejects = sum(c for (exp, act), c in confusion.items()
                        if exp != "reject" and act == "reject")
    # false-accept: 거절해야 할 질문을 통과시킨 비율 (범위 밖인데 도구/웹을 태운다)
    rejectable = sum(c for (exp, _), c in confusion.items() if exp == "reject")
    false_accepts = sum(c for (exp, act), c in confusion.items()
                        if exp == "reject" and act != "reject")

    print("=" * 62)
    print(f"정확도: {correct}/{n} ({correct / n * 100:.1f}%)")
    print(f"false-reject: {false_rejects}/{answerable} "
          f"({false_rejects / answerable * 100:.1f}%)  ← 답할 수 있는데 거절 (1급 지표)")
    print(f"false-accept: {false_accepts}/{rejectable} "
          f"({false_accepts / rejectable * 100:.1f}%)  ← 범위 밖인데 통과")

    print("\n혼동행렬 (행=기대, 열=실제)")
    seen_actual = sorted({act for _, act in confusion}, key=lambda r: (r not in ROUTES, r))
    print(f"{'':>8}" + "".join(f"{a:>9}" for a in seen_actual))
    for exp in ROUTES:
        row = "".join(f"{confusion[(exp, act)]:>9}" for act in seen_actual)
        print(f"{exp:>8}{row}")

    if misses:
        print(f"\n오분류 {len(misses)}건 — scoped↔web은 CRAG가 보정하지만 reject 오류는 사용자가 막힌다.")
    return 0 if correct == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
