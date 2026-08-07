"""yfinance -> SQLite 캐시. `uv run python -m etf_agent.ingest`. 멱등: 재실행하면 행 교체."""
import sys
import time
from datetime import datetime, timezone

import yfinance as yf

from .db import connect
from .universe import (ALL_TICKERS, COUNTRY_ETFS, MIN_HOLDING_OVERLAP,
                       SECTOR_ETFS, country_of, primary_etf_for)


def category_for(ticker: str) -> str:
    """티커의 분류. rank_countries_by_sector가 'country'만 보므로 국가 순위가 이 값에 달렸다.

    country     — 국가당 대표 1종 (universe.COUNTRY_ETFS)
    country_alt — 손으로 적은 후보 중 보유종목 검증을 통과한 것
    sector      — 11 GICS 섹터 대표 SPDR
    sector_alt  — sector_etfs_ext(yf.Sector.top_etfs가 준 목록)에만 있던 것
    """
    if country := country_of(ticker):
        return "country" if ticker in COUNTRY_ETFS else "country_alt"
    return "sector" if ticker in SECTOR_ETFS else "sector_alt"


def sector_alt_tickers(conn) -> list[str]:
    """sector_etfs_ext에 이름만 있고 상세는 없던 티커들.

    검증 게이트를 걸지 않는다: 이 목록은 yf.Sector.top_etfs가 준 것이라 섹터 소속을
    yfinance가 이미 라벨했다. 보유종목 겹침을 또 요구하면 KRE(지방은행)처럼 대표와
    구성이 다른 정당한 특화 ETF만 떨어진다. 데이터를 못 받는 상품(채권·금·MLP)은
    fetch()가 None을 돌려주며 자연히 걸린다.
    """
    known = set(ALL_TICKERS)
    return sorted({r[0] for r in conn.execute("SELECT DISTINCT ticker FROM sector_etfs_ext")}
                  - known)


def alt_is_same_country(alt_holdings: set, primary_holdings: set) -> bool:
    """추가 후보가 대표 ETF와 같은 국가 익스포저인가.

    후보 목록은 손으로 적은 가설이고, 판정은 yfinance 보유종목이 한다 —
    겹치는 종목이 없으면 그 국가 ETF가 아니다(REXC "ex-China"가 이렇게 걸러진다).
    """
    if not alt_holdings or not primary_holdings:
        return False  # 못 받아왔으면 판정 불가 → 통과시키지 않는다
    return len(alt_holdings & primary_holdings) >= MIN_HOLDING_OVERLAP


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
        "category": category_for(ticker),
        "country": country_of(ticker),
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

    seen_holdings: dict[str, set] = {}  # 후보 검증에 쓸 대표 ETF 보유종목
    rejected = []

    # 대표(country/sector)를 먼저 받아야 country_alt 검증 기준이 생긴다. 순서 유지.
    tickers = ALL_TICKERS + sector_alt_tickers(conn)
    print(f"대상 {len(tickers)}종 (유니버스 {len(ALL_TICKERS)} + 섹터 관련 {len(tickers) - len(ALL_TICKERS)})")

    for ticker in tickers:
        data = fetch_with_retry(ticker)
        if data is None:
            skipped.append(ticker)
            print(f"  {ticker}: 데이터 없음 — 건너뜀", file=sys.stderr)
            continue

        symbols = {h[1] for h in data["holdings"]}
        if data["category"] == "country":
            seen_holdings[data["country"]] = symbols
        elif data["category"] == "country_alt":
            # 대표와 보유종목이 겹치는지 확인한다. 안 겹치면 후보 목록이 틀린 것이므로 저장하지 않는다.
            primary = seen_holdings.get(data["country"], set())
            if not alt_is_same_country(symbols, primary):
                rejected.append((ticker, data["country"]))
                anchor = primary_etf_for(data["country"])
                print(f"  {ticker}: {data['country']} 대표({anchor})와 보유종목이 안 겹침 — 제외",
                      file=sys.stderr)
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

    # 상세를 못 받은 ETF는 관련 목록에서도 뺀다 — 이름만 보여주고 물어보면 "없습니다"는
    # 앞뒤가 안 맞는다. 채권·금·단일종목 레버리지(GOLS·NVDL)가 여기서 정리된다.
    with conn:
        pruned = conn.execute(
            "DELETE FROM sector_etfs_ext WHERE ticker NOT IN (SELECT ticker FROM etfs)").rowcount
    if pruned:
        print(f"  관련 ETF 목록에서 {pruned}행 정리 (상세 조회 불가)")

    print(f"\n완료: {covered}/{len(tickers)} 티커"
          + (f" · 건너뜀 {skipped}" if skipped else "")
          + (f" · 검증 탈락 {[t for t, _ in rejected]}" if rejected else ""))
    return 0 if covered else 1


if __name__ == "__main__":
    raise SystemExit(main())
