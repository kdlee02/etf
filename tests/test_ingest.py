"""ingest 검증 게이트 단위 테스트. 네트워크 없음 — 보유종목 집합만 넣고 판정을 본다."""
from etf_agent.ingest import alt_is_same_country, category_for
from etf_agent.universe import (COUNTRY_ETF_ALTS, COUNTRY_ETFS, country_of,
                                primary_etf_for)

# EWY(한국) 실제 보유종목에서 뽑은 픽스처
KOREA = {"005930.KS", "000660.KS", "005380.KS", "000270.KS", "035420.KS"}


def test_alt_kept_when_holdings_overlap():
    """FLKR처럼 같은 국가면 대표와 보유종목이 겹친다."""
    assert alt_is_same_country({"005930.KS", "000660.KS", "051910.KS"}, KOREA)


def test_alt_rejected_when_no_overlap():
    """SPY처럼 다른 시장이면 겹치지 않는다 — 후보 목록에 있어도 저장하지 않는다."""
    assert not alt_is_same_country({"AAPL", "MSFT", "NVDA"}, KOREA)


def test_single_overlap_is_not_enough():
    """1종목은 우연일 수 있다. 글로벌 ETF가 삼성전자 하나만 담아도 한국 ETF는 아니다."""
    assert not alt_is_same_country({"005930.KS", "AAPL", "MSFT"}, KOREA)


def test_empty_holdings_rejected():
    """보유종목을 못 받아오면 판정 불가 — 통과시키지 않는다."""
    assert not alt_is_same_country(set(), KOREA)
    assert not alt_is_same_country(KOREA, set())


def test_every_alt_country_has_a_primary_anchor():
    """검증 기준이 없는 국가에 후보를 달아두면 그 후보는 영원히 저장되지 않는다."""
    for country in COUNTRY_ETF_ALTS:
        assert primary_etf_for(country), f"'{country}'에 대표 ETF가 없다"


def test_alt_tickers_do_not_collide_with_primaries():
    """후보가 대표와 겹치면 category가 덮어써진다."""
    alts = {t for ts in COUNTRY_ETF_ALTS.values() for t in ts}
    assert not (alts & set(COUNTRY_ETFS)), f"대표와 중복된 후보: {alts & set(COUNTRY_ETFS)}"


def test_country_of_resolves_both_primary_and_alt():
    assert country_of("EWY") == "한국"
    assert country_of("FLKR") == "한국"
    assert country_of("XLK") is None


def test_category_for_puts_each_ticker_in_its_own_bucket():
    """country/country_alt/sector/sector_alt 네 갈래.

    rank_countries_by_sector가 'country'만 보므로 이 분류가 틀리면 국가 순위가 오염된다.
    """
    assert category_for("EWY") == "country"        # 대표 국가
    assert category_for("FLKR") == "country_alt"   # 검증 통과한 국가 대안
    assert category_for("XLK") == "sector"         # 대표 섹터(SPDR)
    assert category_for("SMH") == "sector_alt"     # sector_etfs_ext 소속
    assert category_for("QQQ") == "country_alt"    # 미국 대안으로 먼저 잡힌다


def test_only_primary_country_category_feeds_the_ranking():
    """순위에 들어가는 건 국가당 정확히 하나여야 한다."""
    primaries = [t for t in COUNTRY_ETFS if category_for(t) == "country"]
    assert len(primaries) == len(COUNTRY_ETFS) == len(set(COUNTRY_ETFS.values()))
