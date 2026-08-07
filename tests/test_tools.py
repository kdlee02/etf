"""tools.py 단위 테스트. 라이브 네트워크 없이 임시 SQLite에 픽스처를 넣고 돌린다."""
import pytest

from etf_agent import tools
from etf_agent.db import connect
from etf_agent.universe import (SECTOR_ETFS, SECTOR_KO_MAP, SECTOR_KO_NAMES,
                                sector_approximation)

# 실제 yfinance 값에서 뽑은 픽스처 (2026-07-17 인제스트 기준)
ETFS = [
    ("EWY", "iShares MSCI South Korea ETF", "country", "한국", 12.3, 128.62, "2026-07-17T00:00:00+00:00"),
    ("EWT", "iShares MSCI Taiwan ETF", "country", "대만", 9.1, 76.13, "2026-07-17T00:00:00+00:00"),
    ("EWZ", "iShares MSCI Brazil ETF", "country", "브라질", 4.0, 33.32, "2026-07-17T00:00:00+00:00"),
    ("XLK", "Technology Select Sector SPDR", "sector", None, 8.0, 36.71, "2026-07-17T00:00:00+00:00"),
    ("XLC", "Communication Services Select SPDR", "sector", None, 6.0, 21.0, "2026-07-17T00:00:00+00:00"),
    # 검증을 통과한 추가 후보 — 같은 국가, 순위 집계에는 안 들어간다
    ("FLKR", "Franklin FTSE South Korea ETF", "country_alt", "한국", 11.0, 120.0, "2026-07-17T00:00:00+00:00"),
]
SECTORS = [
    ("EWY", "technology", 0.613), ("EWY", "financial_services", 0.12),
    ("EWT", "technology", 0.745), ("EWZ", "technology", 0.004),
    ("XLK", "technology", 0.991),  # 필터가 없으면 순위를 독식하는 놈
    ("FLKR", "technology", 0.60),  # 한국이 순위에 두 번 나오면 안 된다
    ("EWY", "communication_services", 0.08), ("EWT", "communication_services", 0.03),
]
HOLDINGS = [("EWY", f"{i:06d}.KS", f"종목{i}", 0.3 - i * 0.02) for i in range(12)]
# 게임은 GICS에서 통신서비스 소속이다 — 모델은 기술로 넘겨짚는다
INDUSTRIES = [
    ("communication_services", "electronic-gaming-multimedia", "Electronic Gaming & Multimedia", 0.017),
    ("communication_services", "internet-content-information", "Internet Content & Information", 0.741),
    ("technology", "semiconductors", "Semiconductors", 0.383),
]
IND_COMPANIES = [("electronic-gaming-multimedia", "EA", "Electronic Arts", 0.4),
                 ("semiconductors", "NVDA", "NVIDIA", 0.43)]


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    conn = connect(tmp_path / "test.db")
    with conn:
        conn.executemany("INSERT INTO etfs VALUES (?,?,?,?,?,?,?)", ETFS)
        conn.executemany("INSERT INTO sector_weights VALUES (?,?,?)", SECTORS)
        conn.executemany("INSERT INTO holdings VALUES (?,?,?,?)", HOLDINGS)
        conn.executemany("INSERT INTO sector_industries VALUES (?,?,?,?)", INDUSTRIES)
        conn.executemany("INSERT INTO industry_companies VALUES (?,?,?,?)", IND_COMPANIES)
    monkeypatch.setattr(tools, "_conn", conn)
    return conn


def test_rank_countries_by_sector_excludes_sector_etfs():
    """XLK(technology 99%)가 국가 순위에 끼면 안 된다 — category='country' 필터 검증."""
    result = tools.rank_countries_by_sector("반도체")
    assert result["found"]
    tickers = [r["ticker"] for r in result["ranking"]]
    assert "XLK" not in tickers
    assert tickers == ["EWT", "EWY", "EWZ"]  # 내림차순
    assert "정보기술" in result["approximation_note"]  # 어느 섹터로 답했는지 밝혀야 한다


def test_get_country_etfs_returns_alternatives_with_primary_first():
    """'한국에 투자하고 싶어'에 선택지를 준다 — 대표 하나만 주면 뭘 살지 못 고른다."""
    result = tools.get_country_etfs("한국")
    assert result["found"]
    tickers = [e["ticker"] for e in result["etfs"]]
    assert tickers == ["EWY", "FLKR"]  # 대표가 먼저


def test_alternatives_do_not_pollute_country_ranking():
    """FLKR이 순위에 끼면 한국이 두 번 나온다 — category='country' 필터가 막아야 한다."""
    tickers = [r["ticker"] for r in tools.rank_countries_by_sector("기술")["ranking"]]
    assert "FLKR" not in tickers
    assert tickers.count("EWY") == 1


def test_rank_countries_by_sector_respects_top_n():
    assert len(tools.rank_countries_by_sector("반도체", top_n=2)["ranking"]) == 2


def test_narrowed_sector_names_all_get_approximation_note():
    """섹터로 해석했지만 실제로는 세부 산업인 이름은 전부 고지해야 한다.

    반도체만 하드코딩돼 있어 리츠·은행·제약이 조용히 근사되던 버그.
    """
    for name in ("반도체", "은행", "제약", "리츠"):
        note = sector_approximation(name)
        assert note, f"'{name}'은 섹터 좁힘인데 고지가 없다"
        assert name in note and SECTOR_KO_NAMES[SECTOR_KO_MAP[name]] in note
    # 조사: 받침 유무에 따라 은/는. 사용자에게 그대로 나가는 문장이다.
    assert "'은행'은" in sector_approximation("은행")
    assert "'반도체'는" in sector_approximation("반도체")


def test_true_sector_names_get_no_note():
    """정식 섹터명(동의어 포함)은 근사가 아니므로 고지를 붙이지 않는다."""
    for name in ("기술", "정보기술", "금융", "헬스케어", "부동산", "에너지"):
        assert sector_approximation(name) is None, f"'{name}'에 불필요한 고지가 붙었다"


def test_rank_countries_by_sector_notes_bank_narrowing():
    """'은행'은 금융 섹터 전체 비중으로 답하므로 그 사실을 알려야 한다."""
    result = tools.rank_countries_by_sector("은행")
    assert result["found"]
    assert "금융" in result["approximation_note"]


def test_industry_name_resolves_to_its_real_parent_sector():
    """'게임'은 통신서비스다. 섹터 도구에 산업명이 와도 기술로 넘겨짚으면 안 된다.

    실측 버그: get_sector_landscape('게임')이 실패하면서 지원 섹터 목록을 주면
    모델이 목록 첫 항목(정보기술)을 골라 재호출해, 질문과 무관한 차트를 그렸다.
    """
    result = tools.get_sector_landscape("게임")
    assert result["found"], result.get("reason")
    assert result["sector_ko"] == "통신서비스"
    assert "게임" in result["approximation_note"]
    assert "통신서비스" in result["approximation_note"]


def test_industry_name_works_across_all_three_sector_tools():
    """세 도구가 같은 resolve 경로를 쓰므로 동작이 일치해야 한다."""
    for fn in (tools.get_sector_landscape, tools.rank_countries_by_sector, tools.get_sector_etf):
        result = fn("게임")
        assert result["found"], f"{fn.__name__}('게임') 실패: {result.get('reason')}"
        assert "통신서비스" in result["approximation_note"], fn.__name__


def test_unknown_name_does_not_hand_the_model_a_sector_list():
    """모르는 이름엔 고를 목록을 주지 않는다 — 목록이 있으면 모델이 임의로 집는다."""
    result = tools.get_sector_landscape("블록체인")
    assert result["found"] is False
    assert "정보기술, 금융" not in result["reason"]  # 나열 금지
    assert "임의로" in result["reason"]              # 넘겨짚지 말라고 명시


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
    """한국어 국가명으로 찾는다. 개수는 유니버스에 달렸으니 대표가 들어있는지만 본다."""
    result = tools.get_country_etfs("한국")
    assert result["found"]
    assert "EWY" in [e["ticker"] for e in result["etfs"]]
    assert all(e["country"] == "한국" for e in result["etfs"])


def test_get_sector_weights_adds_korean_names():
    sectors = tools.get_sector_weights("EWY")["sectors"]
    assert sectors[0]["sector_ko"] == "정보기술"
    assert sectors[0]["weight"] == 0.613


def test_get_sector_etf_maps_semiconductor_to_xlk():
    result = tools.get_sector_etf("반도체")
    assert result["found"]
    assert result["etf"]["ticker"] == "XLK"
    assert "정보기술" in result["approximation_note"]  # 어느 섹터로 답했는지 밝혀야 한다


def test_sector_etf_note_does_not_claim_dedicated_etf_is_absent():
    """'반도체 전용 ETF는 없다'고 단정하면 안 된다 — SMH·SOXX가 실재한다.

    옛 문구가 이렇게 단정했고, 같은 응답의 related_etfs에 SMH/SOXX가 들어 있어 자기모순이었다.
    """
    note = tools.get_sector_etf("반도체")["approximation_note"]
    assert "없어" not in note and "없습니다" not in note


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
