"""tools.py 단위 테스트. 라이브 네트워크 없이 임시 SQLite에 픽스처를 넣고 돌린다."""
import pytest

from etf_agent import tools
from etf_agent.db import connect
from etf_agent.universe import SECTOR_ETFS, SECTOR_KO_MAP, SECTOR_KO_NAMES

# 실제 yfinance 값에서 뽑은 픽스처 (2026-07-17 인제스트 기준)
ETFS = [
    ("EWY", "iShares MSCI South Korea ETF", "country", "한국", 12.3, 128.62, "2026-07-17T00:00:00+00:00"),
    ("EWT", "iShares MSCI Taiwan ETF", "country", "대만", 9.1, 76.13, "2026-07-17T00:00:00+00:00"),
    ("EWZ", "iShares MSCI Brazil ETF", "country", "브라질", 4.0, 33.32, "2026-07-17T00:00:00+00:00"),
    ("XLK", "Technology Select Sector SPDR", "sector", None, 8.0, 36.71, "2026-07-17T00:00:00+00:00"),
]
SECTORS = [
    ("EWY", "technology", 0.613), ("EWY", "financial_services", 0.12),
    ("EWT", "technology", 0.745), ("EWZ", "technology", 0.004),
    ("XLK", "technology", 0.991),  # 필터가 없으면 순위를 독식하는 놈
]
HOLDINGS = [("EWY", f"{i:06d}.KS", f"종목{i}", 0.3 - i * 0.02) for i in range(12)]


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    conn = connect(tmp_path / "test.db")
    with conn:
        conn.executemany("INSERT INTO etfs VALUES (?,?,?,?,?,?,?)", ETFS)
        conn.executemany("INSERT INTO sector_weights VALUES (?,?,?)", SECTORS)
        conn.executemany("INSERT INTO holdings VALUES (?,?,?,?)", HOLDINGS)
    monkeypatch.setattr(tools, "_conn", conn)
    return conn


def test_rank_countries_by_sector_excludes_sector_etfs():
    """XLK(technology 99%)가 국가 순위에 끼면 안 된다 — category='country' 필터 검증."""
    result = tools.rank_countries_by_sector("반도체")
    assert result["found"]
    tickers = [r["ticker"] for r in result["ranking"]]
    assert "XLK" not in tickers
    assert tickers == ["EWT", "EWY", "EWZ"]  # 내림차순
    assert "근사" in result["approximation_note"]


def test_rank_countries_by_sector_respects_top_n():
    assert len(tools.rank_countries_by_sector("반도체", top_n=2)["ranking"]) == 2


def test_rank_countries_by_sector_unknown_sector_not_found():
    result = tools.rank_countries_by_sector("우주항공")
    assert result["found"] is False
    assert "제공된 데이터에 없습니다" in result["reason"]


def test_get_top_holdings_clamps_to_yahoo_limit():
    """DB에 12개가 있어도 Yahoo 상한(10)을 넘겨 약속하지 않는다."""
    assert len(tools.get_top_holdings("EWY", n=50)["holdings"]) == tools.MAX_HOLDINGS
    assert len(tools.get_top_holdings("EWY", n=3)["holdings"]) == 3


def test_get_top_holdings_orders_by_weight_desc():
    weights = [h["weight"] for h in tools.get_top_holdings("EWY")["holdings"]]
    assert weights == sorted(weights, reverse=True)


def test_unknown_ticker_returns_not_found_instead_of_raising():
    """툴은 raise 하지 않는다 — 예외는 function-calling 루프를 깬다."""
    for result in (tools.get_top_holdings("NOPE"), tools.get_sector_weights("NOPE"),
                   tools.get_etf_profile("NOPE"), tools.get_country_etfs("아틀란티스")):
        assert result["found"] is False
        assert "제공된 데이터에 없습니다" in result["reason"]


def test_empty_ticker_returns_not_found():
    assert tools.get_top_holdings("")["found"] is False


def test_get_country_etfs_finds_korea():
    result = tools.get_country_etfs("한국")
    assert result["found"]
    assert [e["ticker"] for e in result["etfs"]] == ["EWY"]


def test_get_sector_weights_adds_korean_names():
    sectors = tools.get_sector_weights("EWY")["sectors"]
    assert sectors[0]["sector_ko"] == "정보기술"
    assert sectors[0]["weight"] == 0.613


def test_get_sector_etf_maps_semiconductor_to_xlk():
    result = tools.get_sector_etf("반도체")
    assert result["found"]
    assert result["etf"]["ticker"] == "XLK"
    assert "근사" in result["approximation_note"]


def test_sector_key_mappings_are_consistent():
    """세 매핑이 같은 yfinance 키를 써야 한다. (realestate vs real_estate로 한 번 깨졌다.)"""
    assert set(SECTOR_ETFS.values()) <= set(SECTOR_KO_NAMES)
    assert set(SECTOR_KO_MAP.values()) <= set(SECTOR_KO_NAMES)


def test_sector_keys_match_ingested_data():
    """yfinance가 실제로 주는 키와 매핑이 맞는지. 인제스트된 DB가 있을 때만."""
    from etf_agent.db import DB_PATH

    if not DB_PATH.exists():
        pytest.skip("인제스트된 DB 없음")
    live = connect(DB_PATH)
    keys = {r[0] for r in live.execute("SELECT DISTINCT sector FROM sector_weights")}
    assert keys <= set(SECTOR_KO_NAMES), f"한국어 이름 없는 섹터 키: {keys - set(SECTOR_KO_NAMES)}"


def test_get_etf_profile_returns_returns():
    result = tools.get_etf_profile("ewy")  # 소문자도 받는다
    assert result["found"]
    assert result["ret_1y"] == 128.62
    assert result["updated_at"].startswith("2026-07-17")
