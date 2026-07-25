"""섹터 -> 세부 industry -> 대표 종목을 yf.Sector/yf.Industry에서 긁어 캐시한다.

`uv run python -m etf_agent.ingest_sectors`. 멱등: 재실행 시 테이블을 비우고 다시 채운다.
앱 전체가 캐시-오프라인 원칙이라(→ ingest.py) 여기도 하루 1회 수집해 SQLite에 저장한다.
질의 때 네트워크를 치지 않으므로 발표 중 네트워크 사고에 안전하다.
"""
import time

import yfinance as yf

from .db import connect
from .universe import SECTOR_ETFS

TOP_N = 5  # industry별 대표 종목 수


def _yf_key(sector_key: str) -> str:
    """유니버스의 섹터 키 -> yf.Sector 키. 부동산만 realestate->real-estate 예외."""
    return "real-estate" if sector_key == "realestate" else sector_key.replace("_", "-")


def fetch_sector(sector_key: str) -> tuple[list, list, list]:
    """(industry행들, 종목행들, ETF행들). 실패한 industry는 건너뛴다 — raise 하지 않는다."""
    ind_rows, comp_rows = [], []
    s = yf.Sector(_yf_key(sector_key))
    for ikey, r in s.industries.iterrows():
        ind_rows.append((sector_key, ikey, r["name"], float(r["market weight"])))
        try:
            tc = yf.Industry(ikey).top_companies
        except Exception:
            continue  # 일부 industry는 top_companies가 404/빈값
        if tc is None or tc.empty:
            continue
        for sym, cr in tc.head(TOP_N).iterrows():
            comp_rows.append((ikey, sym, cr["name"], float(cr["market weight"])))
    etf_rows = [(sector_key, tk, nm) for tk, nm in (s.top_etfs or {}).items()]
    return ind_rows, comp_rows, etf_rows


def main() -> int:
    all_ind, all_comp, all_etf = [], [], []
    for sector_key in dict.fromkeys(SECTOR_ETFS.values()):  # 11개 (중복 제거, 순서 유지)
        ind_rows, comp_rows, etf_rows = fetch_sector(sector_key)
        all_ind += ind_rows
        all_comp += comp_rows
        all_etf += etf_rows
        print(f"  {sector_key}: industry {len(ind_rows)} · 종목 {len(comp_rows)} · ETF {len(etf_rows)}")
        time.sleep(0.3)  # yahoo rate-limit 예의
    conn = connect()
    with conn:
        conn.execute("DELETE FROM sector_industries")
        conn.execute("DELETE FROM industry_companies")
        conn.execute("DELETE FROM sector_etfs_ext")
        conn.executemany("INSERT OR REPLACE INTO sector_industries VALUES (?,?,?,?)", all_ind)
        conn.executemany("INSERT OR REPLACE INTO industry_companies VALUES (?,?,?,?)", all_comp)
        conn.executemany("INSERT OR REPLACE INTO sector_etfs_ext VALUES (?,?,?)", all_etf)
    print(f"완료: industry {len(all_ind)} · 종목 {len(all_comp)} · ETF {len(all_etf)} 저장")
    return 0 if all_ind else 1


if __name__ == "__main__":
    raise SystemExit(main())
