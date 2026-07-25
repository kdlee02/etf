"""_ungrounded_tickers 단위 테스트. 도구에 없는 티커(환각)를 잡는지만 본다 — 네트워크 없음."""
from etf_agent.agent import ToolCall, _ungrounded_tickers


def test_hallucinated_etf_ticker_flagged():
    # 도구는 KO/PEP만 반환했는데 답변이 VDC/KXI를 지어냄 -> 잡아야 한다
    trace = [ToolCall("get_industry", {"industry": "음료"},
                      {"found": True, "groups": [{"top_companies": [
                          {"symbol": "KO"}, {"symbol": "PEP"}]}]})]
    text = "음료는 KO, PEP가 대표입니다. 관련 ETF로 VDC, KXI가 있습니다."
    assert _ungrounded_tickers(text, trace) == {"VDC", "KXI"}


def test_grounded_tickers_pass():
    trace = [ToolCall("get_etf_profile", {"ticker": "EWY"},
                      {"found": True, "ticker": "EWY", "holdings": [{"symbol": "005930.KS"}]})]
    # EWY는 도구 결과에 있음, ETF/TER은 스톱리스트 -> 아무것도 안 잡혀야 함
    assert _ungrounded_tickers("EWY ETF의 TER은 낮습니다.", trace) == set()
