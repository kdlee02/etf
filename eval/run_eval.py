"""라이브 Gemini 스모크. `uv run python eval/run_eval.py [--runs N]`

CI 아님 — 네트워크와 API 쿼터가 필요하다. 판정은 **라우팅** 기준이다:
답변 문구는 실행마다 흔들리므로 '어떤 도구를 불렀나'로 본다 (숫자를 안 지어냈다는 건 증명 불가).

무료 티어는 분당 5요청이라 각 호출 사이에 쉬어간다.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_agent.agent import ask  # noqa: E402

CASES = [
    {
        "id": "ac2_country_lookup",
        "q": "한국에 투자하는 ETF랑 주요 종목/섹터 알려줘",
        "expect_tools": ["get_country_etfs"],
        "expect_text": ["EWY"],
        # 유니버스 밖 티커 = 도구를 안 부르고 기억으로 답했다는 증거
        "forbid_text": ["FKO", "KORU", "KOLD", "TIGER", "KODEX"],
    },
    {
        "id": "ac3_reverse_query",
        "q": "반도체 비중 높은 나라 순위 알려줘",
        "expect_tools": ["rank_countries_by_sector"],
        "expect_text": ["대만", "한국"],
        "forbid_text": ["XLK"],  # 섹터 ETF가 국가 순위에 끼면 category 필터 버그
    },
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
    {
        "id": "ac5_reask",
        "q": "한국",
        "expect_tools": [],  # 주제만 왔을 땐 조회하지 말고 되물어야 한다
        "expect_text": ["?"],
    },
    {
        "id": "sector_etf",
        "q": "미국 반도체에 투자하고 싶어",
        "expect_tools": ["get_sector_etf"],
        "expect_text": ["XLK"],
    },
]


def ask_with_retry(question: str, attempts: int = 3):
    """서버 과부하는 실패가 아니라 대기 신호다."""
    for i in range(attempts):
        try:
            return ask(question)
        except Exception as e:
            transient = any(s in str(e) for s in ("429", "500", "502", "503", "504", "timeout"))
            if not transient or i == attempts - 1:
                raise
            print(f"         (일시 오류 {type(e).__name__} — 재시도)", flush=True)
            time.sleep(10)
    raise RuntimeError("unreachable")


def check(case, answer) -> list[str]:
    """실패 사유 목록. 비어 있으면 통과."""
    called = [c.name for c in answer.tool_calls]
    fails = []
    expect_tools = case.get("expect_tools")
    for tool in expect_tools or []:
        if tool not in called:
            fails.append(f"도구 미호출: {tool} (호출됨: {called or '없음'})")
    if expect_tools == [] and called:
        fails.append(f"도구를 부르면 안 되는데 호출됨: {called}")
    for tool in case.get("forbid_tools", []):
        if tool in called:
            fails.append(f"부르면 안 되는 도구 호출됨: {tool}")
    if case.get("expect_no_evidence") and answer.has_evidence:
        found = [c.name for c in answer.tool_calls if (c.result or {}).get("found")]
        fails.append(f"근거 없이 답해야 하는데 실데이터가 붙음: {found}")
    for text in case.get("expect_text", []):
        if text not in answer.text:
            fails.append(f"문구 없음: {text!r}")
    for text in case.get("forbid_text", []):
        if text in answer.text:
            fails.append(f"금지 문구 등장(환각 의심): {text!r}")
    return fails


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1, help="케이스당 반복 횟수 (흔들림 측정용)")
    parser.add_argument("--sleep", type=float, default=0, help="호출 간 대기 초 (레이트 리밋 있을 때만)")
    args = parser.parse_args()

    results: dict[str, list[bool]] = {c["id"]: [] for c in CASES}
    for run in range(args.runs):
        for case in CASES:
            try:
                answer = ask_with_retry(case["q"])
                fails = check(case, answer)
            except Exception as e:
                fails = [f"예외: {type(e).__name__}: {str(e)[:60]}"]
            results[case["id"]].append(not fails)
            mark = "PASS" if not fails else "FAIL"
            # flush: 파일로 리다이렉트하면 stdout이 블록 버퍼링돼 끝날 때까지 아무것도 안 보인다.
            print(f"[{run + 1}/{args.runs}] {mark}  {case['id']}", flush=True)
            for f in fails:
                print(f"         └ {f}", flush=True)
            time.sleep(args.sleep)

    print("\n" + "=" * 50)
    total_pass = 0
    for case_id, runs in results.items():
        passed = sum(runs)
        total_pass += passed
        rate = passed / len(runs) * 100
        print(f"{passed}/{len(runs)}  ({rate:5.1f}%)  {case_id}")
    overall = total_pass / (len(CASES) * args.runs) * 100
    print(f"\n전체: {total_pass}/{len(CASES) * args.runs} ({overall:.1f}%)")
    return 0 if total_pass == len(CASES) * args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
