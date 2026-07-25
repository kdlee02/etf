"""yfinance -> SQLite 캐시. `uv run python -m etf_agent.ingest`. 멱등: 재실행하면 행 교체."""
import sys
import time
from datetime import datetime, timezone

import yfinance as yf

from .db import connect
from .universe import ALL_TICKERS, COUNTRY_ETFS


def _returns(ticker: str) -> tuple[float | None, float | None]:
    """3개월/1년 수익률. 이력이 짧으면 None (크래시 금지)."""
    hist = yf.Ticker(ticker).history(period="1y")["Close"]
    if hist.empty:
        return None, None

    def pct(days: int) -> float | None:
        # ponytail: 거래일 근사(3개월=63, 1년=252). 정확한 날짜 정렬은 불필요.
        if len(hist) <= days:
            return None
        return round((hist.iloc[-1] / hist.iloc[-days - 1] - 1) * 100, 2)

    return pct(63), pct(len(hist) - 1)


def fetch(ticker: str) -> dict | None:
    """티커 하나의 프로필/보유종목/섹터비중. 커버 안 되면 None."""
    t = yf.Ticker(ticker)
    fd = t.funds_data
    holdings = fd.top_holdings
    sectors = fd.sector_weightings
    if holdings is None or holdings.empty or not sectors:
        return None
    ret_3mo, ret_1y = _returns(ticker)
    return {
        "ticker": ticker,
        "name": t.info.get("longName") or ticker,
        "category": "country" if ticker in COUNTRY_ETFS else "sector",
        "country": COUNTRY_ETFS.get(ticker),
        "ret_3mo": ret_3mo,
        "ret_1y": ret_1y,
        "holdings": [
            (ticker, symbol, row["Name"], float(row["Holding Percent"]))
            for symbol, row in holdings.iterrows()
        ],
        "sectors": [(ticker, s, float(w)) for s, w in sectors.items()],
    }


def fetch_with_retry(ticker: str, attempts: int = 3) -> dict | None:
    for i in range(attempts):
        try:
            return fetch(ticker)
        except Exception as e:
            if i == attempts - 1:
                print(f"  {ticker}: 실패 ({type(e).__name__}: {e})", file=sys.stderr)
                return None
            time.sleep(2**i)
    return None


def main() -> int:
    conn = connect()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    covered, skipped = 0, []

    for ticker in ALL_TICKERS:
        data = fetch_with_retry(ticker)
        if data is None:
            skipped.append(ticker)
            print(f"  {ticker}: 데이터 없음 — 건너뜀", file=sys.stderr)
            continue
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO etfs VALUES (?,?,?,?,?,?,?)",
                (data["ticker"], data["name"], data["category"], data["country"],
                 data["ret_3mo"], data["ret_1y"], now),
            )
            conn.execute("DELETE FROM holdings WHERE ticker=?", (ticker,))
            conn.executemany("INSERT OR REPLACE INTO holdings VALUES (?,?,?,?)", data["holdings"])
            conn.execute("DELETE FROM sector_weights WHERE ticker=?", (ticker,))
            conn.executemany("INSERT OR REPLACE INTO sector_weights VALUES (?,?,?)", data["sectors"])
        covered += 1
        print(f"  {ticker}: 보유 {len(data['holdings'])} · 섹터 {len(data['sectors'])} · 1년 {data['ret_1y']}%")
        time.sleep(0.3)  # ponytail: Yahoo 429 회피. 부족하면 attempts/backoff를 올릴 것.

    print(f"\n완료: {covered}/{len(ALL_TICKERS)} 티커" + (f" · 건너뜀 {skipped}" if skipped else ""))
    return 0 if covered else 1


if __name__ == "__main__":
    raise SystemExit(main())
