"""티커 유니버스 + 한국어 매핑. 커버리지는 2026-07-17 스파이크에서 43/43 확인."""

# 국가 ETF: ticker -> 한국어 국가명
COUNTRY_ETFS = {
    "EWY": "한국", "EWJ": "일본", "MCHI": "중국", "INDA": "인도", "EWT": "대만",
    "EWH": "홍콩", "EWS": "싱가포르", "EWM": "말레이시아", "THD": "태국",
    "EIDO": "인도네시아", "EPHE": "필리핀", "VNM": "베트남",
    "EWG": "독일", "EWU": "영국", "EWQ": "프랑스", "EWL": "스위스",
    "EWN": "네덜란드", "EWI": "이탈리아", "EWP": "스페인", "EWD": "스웨덴",
    "EDEN": "덴마크", "ENOR": "노르웨이", "EIRL": "아일랜드", "EPOL": "폴란드",
    "EWA": "호주", "EWC": "캐나다", "EWW": "멕시코", "EWZ": "브라질", "ECH": "칠레",
    "EIS": "이스라엘", "TUR": "터키", "EZA": "남아공",
    "SPY": "미국",
}

# 섹터 ETF (SPDR): ticker -> yfinance 섹터 키
SECTOR_ETFS = {
    "XLK": "technology", "XLF": "financial_services", "XLE": "energy",
    "XLV": "healthcare", "XLI": "industrials", "XLP": "consumer_defensive",
    "XLY": "consumer_cyclical", "XLU": "utilities", "XLB": "basic_materials",
    "XLRE": "realestate", "XLC": "communication_services",
}

# 한국어 섹터명 -> yfinance 키. 반도체/IT는 technology로 근사 (GICS 세분화 없음).
SECTOR_KO_MAP = {
    "반도체": "technology", "IT": "technology", "기술": "technology",
    "정보기술": "technology", "테크": "technology",
    "금융": "financial_services", "은행": "financial_services",
    "에너지": "energy", "석유": "energy",
    "헬스케어": "healthcare", "의료": "healthcare", "제약": "healthcare",
    "산업재": "industrials", "제조": "industrials",
    "필수소비재": "consumer_defensive", "생필품": "consumer_defensive",
    "경기소비재": "consumer_cyclical", "소비재": "consumer_cyclical",
    "유틸리티": "utilities", "공공": "utilities",
    "소재": "basic_materials", "원자재": "basic_materials",
    "부동산": "realestate", "리츠": "realestate",
    "통신": "communication_services", "미디어": "communication_services",
}

# yfinance 섹터 키 -> 한국어 표시명 (차트 라벨용).
# 키는 DB에서 검증한 실제 yfinance 값. 부동산만 realestate(언더스코어 없음)다.
SECTOR_KO_NAMES = {
    "technology": "정보기술", "financial_services": "금융", "energy": "에너지",
    "healthcare": "헬스케어", "industrials": "산업재",
    "consumer_defensive": "필수소비재", "consumer_cyclical": "경기소비재",
    "utilities": "유틸리티", "basic_materials": "소재", "realestate": "부동산",
    "communication_services": "통신서비스",
}

# 한국어 산업명 -> yfinance industry 키 목록. 섹터보다 좁은 단위.
# 키는 sector_industries 테이블의 실측 값. 한 개념이 여러 하위산업이면 리스트로 묶는다(음료=3개).
# resolve_sector와 별도 네임스페이스: "반도체 비중 높은 나라"(섹터) ≠ "반도체 종목"(산업).
INDUSTRY_KO_MAP = {
    "음료": ["beverages-non-alcoholic", "beverages-brewers", "beverages-wineries-distilleries"],
    "주류": ["beverages-brewers", "beverages-wineries-distilleries"],
    "담배": ["tobacco"],
    "식품": ["packaged-foods"], "가공식품": ["packaged-foods"],
    "제과": ["confectioners"], "그로서리": ["grocery-stores"],
    "제약": ["drug-manufacturers-general", "drug-manufacturers-specialty-generic"],
    "바이오": ["biotechnology"], "바이오테크": ["biotechnology"],
    "의료기기": ["medical-devices"], "의료보험": ["healthcare-plans"],
    "반도체": ["semiconductors"], "반도체장비": ["semiconductor-equipment-materials"],
    "소프트웨어": ["software-infrastructure", "software-application"],
    "소비자전자": ["consumer-electronics"], "전자부품": ["electronic-components"],
    "게임": ["electronic-gaming-multimedia"], "엔터": ["entertainment"], "엔터테인먼트": ["entertainment"],
    "광고": ["advertising-agencies"], "인터넷": ["internet-content-information"],
    "자동차": ["auto-manufacturers"], "자동차부품": ["auto-parts"],
    "이커머스": ["internet-retail"], "전자상거래": ["internet-retail"],
    "여행": ["travel-services"], "호텔": ["lodging"], "카지노": ["resorts-casinos", "gambling"],
    "명품": ["luxury-goods"], "의류": ["apparel-retail", "apparel-manufacturing"],
    "은행": ["banks-diversified", "banks-regional"],
    "보험": ["insurance-diversified", "insurance-life", "insurance-property-casualty"],
    "자산운용": ["asset-management"], "증권": ["capital-markets"],
    "항공우주": ["aerospace-defense"], "방산": ["aerospace-defense"],
    "항공": ["airlines"], "철도": ["railroads"], "해운": ["marine-shipping"],
    "정유": ["oil-gas-refining-marketing"], "우라늄": ["uranium"], "원자력": ["uranium"],
    "태양광": ["solar"], "재생에너지": ["utilities-renewable", "solar"],
    "화학": ["chemicals"], "리츠": ["reit-diversified", "reit-residential", "reit-retail"],
}

# 국가별 추가 ETF **후보**. 여기 적혔다고 채택되는 게 아니다 — ingest가 대표 ETF와
# 보유종목이 MIN_HOLDING_OVERLAP종목 이상 겹치는지 yfinance로 확인하고, 통과한 것만 저장한다.
# 후보는 가설이고 판정은 데이터가 한다.
#
# 손으로 적는 이유: yfinance에 국가 단위 발굴 API가 없다. yf.Search("China ETF")는 7건뿐이고
# FXI·KWEB을 안 주며, 펀드 스크리너(FundQuery)는 뮤추얼펀드만 반환한다(ETF 0건).
# COUNTRY_ETFS 33종도 같은 방식으로 손으로 고른 것이라 새로 생긴 타협이 아니다.
# ponytail: 커버리지는 best-effort. 검증에 걸리면 그 국가는 대표 1종만 남는다.
COUNTRY_ETF_ALTS = {
    "미국": ["VOO", "IVV", "VTI", "QQQ", "DIA", "IWM"],
    "중국": ["FXI", "KWEB", "ASHR", "CQQQ", "GXC", "FLCH", "MCHK"],
    "한국": ["FLKR"],
    "일본": ["FLJP", "DXJ", "BBJP", "DFJ"],
    "인도": ["INDY", "EPI", "FLIN", "SMIN", "PIN"],
    "대만": ["FLTW"],
    "브라질": ["FLBR", "EWZS"],
    "독일": ["FLGR"],
    "영국": ["FLGB"],
    "프랑스": ["FLFR"],
    "스위스": ["FLSW"],
    "캐나다": ["FLCA"],
    "호주": ["FLAU"],
    "멕시코": ["FLMX"],
    "홍콩": ["FLHK"],
    "남아공": ["FLZA"],
    "이탈리아": ["FLIY"],
    "스페인": ["FLES"],
    "싱가포르": ["FLSG"],
    "말레이시아": ["FLM"],
    "태국": ["FLTH"],
}

# 대표 ETF와 이만큼 겹쳐야 같은 국가 익스포저로 인정한다. 1은 우연히 겹칠 수 있다.
# ponytail: A주 전용(ASHR)처럼 대표와 상장지가 달라 안 겹치는 상품은 놓친다 —
# 놓치는 건 틀리는 것보다 낫다는 이 프로젝트 원칙(MIN_SCORE·reject)과 같은 선택.
MIN_HOLDING_OVERLAP = 2

ALL_TICKERS = (list(COUNTRY_ETFS) + list(SECTOR_ETFS)
               + [t for alts in COUNTRY_ETF_ALTS.values() for t in alts])


_ALT_COUNTRY = {t: ko for ko, alts in COUNTRY_ETF_ALTS.items() for t in alts}
_PRIMARY_OF = {ko: tk for tk, ko in COUNTRY_ETFS.items()}


def country_of(ticker: str) -> str | None:
    """티커가 속한 국가(한국어). 대표든 추가 후보든 같은 국가를 돌려준다."""
    return COUNTRY_ETFS.get(ticker) or _ALT_COUNTRY.get(ticker)


def primary_etf_for(country: str) -> str | None:
    """국가의 대표 ETF 티커. 추가 후보를 검증할 기준이다."""
    return _PRIMARY_OF.get(country)


def resolve_industry(name: str) -> list[str] | None:
    """한국어 산업명 -> yfinance industry 키 목록. 모르면 None."""
    return INDUSTRY_KO_MAP.get(name.strip())


def resolve_sector(name: str) -> str | None:
    """한국어/영어 섹터명 -> yfinance 섹터 키. 모르면 None."""
    key = name.strip()
    if key in SECTOR_KO_MAP:
        return SECTOR_KO_MAP[key]
    snake = key.lower().replace(" ", "_")
    return snake if snake in SECTOR_KO_NAMES else None


def _eun_neun(word: str) -> str:
    """받침 있으면 '은', 없으면 '는'. 한글이 아니면 '는'. (은행'는' 같은 문장이 사용자에게 나간다)"""
    last = word[-1:]
    if not ("가" <= last <= "힣"):
        return "는"
    return "은" if (ord(last) - 0xAC00) % 28 else "는"


def narrowed_names_in(text: str) -> list[str]:
    """문장에 등장하는 '섹터로 물으면 좁혀지는' 이름들. 긴 이름 우선(반도체장비 > 반도체)."""
    names = sorted(set(INDUSTRY_KO_MAP) & set(SECTOR_KO_MAP), key=len, reverse=True)
    return [n for n in names if n in text]


def sector_approximation(name: str) -> str | None:
    """섹터로 해석했지만 실제로는 그 섹터의 세부 산업이면 고지 문구를, 아니면 None.

    두 맵에 다 있으면 좁힘이다 — "반도체"는 섹터로 물으면 정보기술 전체로 답하고
    산업으로 물으면 semiconductors로 답한다. 이름을 나열하지 않고 교집합으로 판정하는 이유:
    반도체만 하드코딩했다가 리츠·은행·제약이 고지 없이 근사되고 있었다.
    """
    key = name.strip()
    if not (key in INDUSTRY_KO_MAP and key in SECTOR_KO_MAP):
        return None
    return narrowing_note(key, SECTOR_KO_MAP[key])


def narrowing_note(name: str, sector_key: str) -> str:
    """'이건 세부 산업이고 수치는 상위 섹터 전체 기준'이라는 고지 문구.

    상위 섹터를 인자로 받는다: 두 맵의 교집합(반도체·은행·제약·리츠)은 SECTOR_KO_MAP이
    알려주지만, '게임'처럼 산업 맵에만 있는 이름은 부모를 DB(sector_industries)에서 찾아야 한다.
    """
    parent = SECTOR_KO_NAMES.get(sector_key, sector_key)
    return (f"'{name}'{_eun_neun(name)} 별도 섹터가 아니라 {parent} 섹터의 세부 산업입니다. "
            f"아래 수치는 {parent} 섹터 전체 기준입니다.")


def sector_etf_for(sector_key: str) -> str | None:
    """섹터 키 -> 해당 SPDR 티커."""
    for ticker, key in SECTOR_ETFS.items():
        if key == sector_key:
            return ticker
    return None
