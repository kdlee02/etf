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

ALL_TICKERS = list(COUNTRY_ETFS) + list(SECTOR_ETFS)


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


def sector_etf_for(sector_key: str) -> str | None:
    """섹터 키 -> 해당 SPDR 티커."""
    for ticker, key in SECTOR_ETFS.items():
        if key == sector_key:
            return ticker
    return None
