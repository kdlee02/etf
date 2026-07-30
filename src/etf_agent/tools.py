"""Upstage Solar에 노출하는 데이터 조회 함수들.

규칙: 절대 raise 하지 않는다. 데이터가 없으면 {"found": False, ...}를 돌려준다 —
예외가 나면 function-calling 루프가 깨진다.
"""
import sqlite3

from .db import connect
from .retrieval import search_concepts
from .universe import SECTOR_KO_NAMES, resolve_industry, resolve_sector, sector_etf_for

MAX_HOLDINGS = 10  # Yahoo가 상위 10개까지만 준다 (2026-07-17 확인)

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
    conn = _conn
    assert conn is not None
    return conn


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in _db().execute(sql, params).fetchall()]


def get_country_etfs(country: str) -> dict:
    """특정 국가에 투자하는 ETF 목록을 반환한다.

    Args:
        country: 한국어 국가명 (예: "한국", "일본", "대만").
    """
    rows = _rows(
        "SELECT ticker, name, country, ret_3mo, ret_1y, updated_at FROM etfs"
        " WHERE category = ? AND country = ?",
        ("country", country.strip()),
    )
    if not rows:
        return {"found": False, "reason": f"'{country}' 국가의 ETF는 제공된 데이터에 없습니다."}
    return {"found": True, "country": country, "etfs": rows}


def get_top_holdings(ticker: str, n: int = MAX_HOLDINGS) -> dict:
    """ETF의 주요 보유 종목을 비중 순으로 반환한다. 최대 10개.

    Args:
        ticker: ETF 티커 (예: "EWY").
        n: 반환할 종목 수. 최대 10.
    """
    n = max(1, min(n, MAX_HOLDINGS))
    rows = _rows(
        "SELECT symbol, name, weight FROM holdings WHERE ticker = ?"
        " ORDER BY weight DESC LIMIT ?",
        (ticker.strip().upper(), n),
    )
    if not rows:
        return {"found": False, "reason": f"'{ticker}'의 보유 종목은 제공된 데이터에 없습니다."}
    return {"found": True, "ticker": ticker.upper(), "holdings": rows,
            "note": "야후 파이낸스는 상위 10개 종목만 제공합니다."}


def get_sector_weights(ticker: str) -> dict:
    """ETF의 섹터별 비중을 반환한다.

    Args:
        ticker: ETF 티커 (예: "EWY").
    """
    rows = _rows(
        "SELECT sector, weight FROM sector_weights WHERE ticker = ? ORDER BY weight DESC",
        (ticker.strip().upper(),),
    )
    if not rows:
        return {"found": False, "reason": f"'{ticker}'의 섹터 비중은 제공된 데이터에 없습니다."}
    for r in rows:
        r["sector_ko"] = SECTOR_KO_NAMES.get(r["sector"], r["sector"])
    return {"found": True, "ticker": ticker.upper(), "sectors": rows}


def rank_countries_by_sector(sector: str, top_n: int = 10) -> dict:
    """특정 섹터 비중이 높은 국가를 순위로 반환한다 (역방향 조회).

    Args:
        sector: 한국어 섹터명 (예: "반도체", "금융", "에너지").
        top_n: 반환할 국가 수.
    """
    key = resolve_sector(sector)
    if key is None:
        return {"found": False,
                "reason": f"'{sector}' 섹터는 제공된 데이터에 없습니다. 지원 섹터: {', '.join(SECTOR_KO_NAMES.values())}"}
    # category='country' 필터 필수: 섹터 ETF(XLK)는 technology 99%라 순위를 독식한다.
    rows = _rows(
        "SELECT e.ticker, e.country, s.weight FROM sector_weights s"
        " JOIN etfs e USING(ticker)"
        " WHERE s.sector = ? AND e.category = ?"
        " ORDER BY s.weight DESC LIMIT ?",
        (key, "country", max(1, top_n)),
    )
    if not rows:
        return {"found": False, "reason": f"'{sector}' 섹터 비중 데이터가 없습니다."}
    result = {"found": True, "sector": sector, "sector_key": key,
              "sector_ko": SECTOR_KO_NAMES.get(key, key), "ranking": rows}
    if sector in ("반도체",):
        result["approximation_note"] = "반도체 단독 데이터가 없어 기술(정보기술) 섹터 기준으로 근사했습니다."
    return result


def get_sector_etf(sector: str) -> dict:
    """특정 섹터에 투자하는 미국 SPDR 섹터 ETF를 반환한다.

    Args:
        sector: 한국어 섹터명 (예: "반도체", "금융").
    """
    key = resolve_sector(sector)
    if key is None:
        return {"found": False,
                "reason": f"'{sector}' 섹터는 제공된 데이터에 없습니다. 지원 섹터: {', '.join(SECTOR_KO_NAMES.values())}"}
    ticker = sector_etf_for(key)
    rows = _rows("SELECT ticker, name, ret_3mo, ret_1y, updated_at FROM etfs WHERE ticker = ?",
                 (ticker,)) if ticker else []
    if not rows:
        return {"found": False, "reason": f"'{sector}' 섹터 ETF는 제공된 데이터에 없습니다."}
    # 같은 섹터의 다른 ETF들(yf.Sector.top_etfs 캐시). 대표 SPDR은 etf에 이미 있으니 제외.
    related = _rows("SELECT ticker, name FROM sector_etfs_ext WHERE sector_key = ? AND ticker != ?",
                    (key, rows[0]["ticker"]))
    result = {"found": True, "sector": sector, "sector_ko": SECTOR_KO_NAMES.get(key, key),
              "etf": rows[0], "related_etfs": related}
    if sector in ("반도체",):
        result["approximation_note"] = "반도체 전용 ETF는 없어 기술 섹터 ETF(XLK)로 근사했습니다."
    return result


def get_etf_profile(ticker: str) -> dict:
    """ETF의 이름, 분류, 국가, 수익률을 반환한다.

    Args:
        ticker: ETF 티커 (예: "EWY").
    """
    rows = _rows(
        "SELECT ticker, name, category, country, ret_3mo, ret_1y, updated_at FROM etfs WHERE ticker = ?",
        (ticker.strip().upper(),),
    )
    if not rows:
        return {"found": False, "reason": f"'{ticker}' ETF는 제공된 데이터에 없습니다."}
    return {"found": True, **rows[0]}


def get_sector_landscape(sector: str) -> dict:
    """섹터를 구성하는 세부 산업(industry)과 각 산업의 대표 종목을 반환한다.

    "반도체 섹터는 무슨 산업들로 이뤄졌어?", "기술 섹터 세부 산업이랑 대표 종목?" 같은
    시장 전체 섹터 구조 질문에 쓴다. 특정 ETF의 보유 구성(get_top_holdings)과는 다르다.

    Args:
        sector: 한국어 섹터명 (예: "기술", "금융", "헬스케어").
    """
    key = resolve_sector(sector)
    if key is None:
        return {"found": False,
                "reason": f"'{sector}' 섹터는 제공된 데이터에 없습니다. 지원 섹터: {', '.join(SECTOR_KO_NAMES.values())}"}
    industries = _rows(
        "SELECT industry_key, industry_name, weight FROM sector_industries"
        " WHERE sector_key = ? ORDER BY weight DESC", (key,))
    if not industries:
        return {"found": False, "reason": f"'{sector}' 섹터의 산업 데이터가 없습니다. ingest_sectors 실행이 필요합니다."}
    for ind in industries:
        ind["top_companies"] = _rows(
            "SELECT symbol, name, weight FROM industry_companies"
            " WHERE industry_key = ? ORDER BY weight DESC", (ind["industry_key"],))
    result = {"found": True, "sector": sector,
              "sector_ko": SECTOR_KO_NAMES.get(key, key), "industries": industries,
              "note": "시장 전체 섹터 기준(시총가중)이며, 특정 ETF의 보유 구성이 아닙니다."}
    if sector in ("반도체",):
        result["approximation_note"] = "'반도체'는 기술 섹터 전체로 조회했습니다. 세부 산업의 'Semiconductors'를 보세요."
    return result


def get_industry(industry: str) -> dict:
    """특정 산업(industry)의 대표 종목과 소속 섹터를 반환한다. 섹터보다 좁은 단위.

    "음료 시장 투자", "제약 종목", "반도체 산업 대표주"처럼 산업 단위 질문에 쓴다.
    섹터 전체 구조(어떤 산업들로 이뤄졌나)는 get_sector_landscape를 쓴다.
    한 산업 개념이 여러 하위산업으로 나뉘면(예: 음료=무알콜/맥주/주류) 모두 반환한다.

    Args:
        industry: 한국어 산업명 (예: "음료", "제약", "반도체", "자동차").
    """
    keys = resolve_industry(industry)
    if not keys:
        return {"found": False,
                "reason": f"'{industry}' 산업은 제공된 데이터에 없습니다. 섹터 단위(예: 필수소비재, 헬스케어)로 물어보실 수 있습니다."}
    groups, sector_keys = [], []
    for key in keys:
        meta = _rows("SELECT sector_key, industry_name, weight FROM sector_industries WHERE industry_key = ?", (key,))
        if not meta:
            continue
        companies = _rows(
            "SELECT symbol, name, weight FROM industry_companies WHERE industry_key = ? ORDER BY weight DESC",
            (key,))
        groups.append({"industry_name": meta[0]["industry_name"],
                       "sector_ko": SECTOR_KO_NAMES.get(meta[0]["sector_key"], meta[0]["sector_key"]),
                       "weight_in_sector": meta[0]["weight"], "top_companies": companies})
        if meta[0]["sector_key"] not in sector_keys:
            sector_keys.append(meta[0]["sector_key"])
    if not groups:
        return {"found": False, "reason": f"'{industry}' 산업 데이터가 없습니다. ingest_sectors 실행이 필요합니다."}
    # 산업 전용 ETF는 yfinance에 없다 -> 소속 섹터 ETF를 라벨 달아 제시한다.
    sector_etfs = []
    for sk in sector_keys:
        for e in _rows("SELECT ticker, name FROM sector_etfs_ext WHERE sector_key = ?", (sk,)):
            sector_etfs.append({**e, "sector_ko": SECTOR_KO_NAMES.get(sk, sk)})
    return {"found": True, "industry": industry, "groups": groups, "sector_etfs": sector_etfs,
            "note": "시장 전체 기준(시총가중)이며 특정 ETF 보유가 아닙니다. "
                    "ETF는 산업 전용이 아니라 이 산업이 속한 섹터 ETF입니다."}


TOOLS = [get_country_etfs, get_top_holdings, get_sector_weights,
         rank_countries_by_sector, get_sector_etf, get_etf_profile,
         search_concepts, get_sector_landscape, get_industry]
