# 📊 ETF 투자 리서치 어시스턴트

국가·섹터·산업 기준으로 ETF를 **실제 데이터**로 조회하고, 개념·세금·위험·전략 질문은 **문서 코퍼스(RAG)**로 답하는 하이브리드 에이전트. 모든 수치는 도구 호출 결과이며, 근거 없는 답변은 하지 않는다.

> 코멘토 AI SA 부트캠프 프로젝트. Upstage `solar-pro3` + function-calling + langchain FAISS RAG.

## 핵심 특징

- **근거 기반(반환각):** 답변의 모든 수치는 도구가 반환한 값만 사용. 도구를 호출하지 않으면 티커·수치를 언급하지 않는다.
- **양방향 조회:** 국가→ETF/종목/섹터, 섹터→국가 비중, 섹터→산업→대표종목.
- **RAG 인용:** 환헤지·양도세·상장폐지·듀얼 모멘텀 등 개념/전략 질문은 코퍼스에서 검색해 `(문서명 p페이지)`로 인용.
- **부정 규칙은 코드로 강제:** 모델이 프롬프트만으론 어기는 규칙(고지 누락, 오프토픽 거절, 티커 환각)을 코드로 잠금 — `_with_disclaimer`, `MIN_SCORE`, `_reground`.

## 아키텍처

```
질문 → agent.ask() ─ function-calling loop (solar-pro3)
                      ├─ 구조화 도구 (tools.py) ── SQLite 캐시 (db.py) ← yfinance
                      └─ search_concepts (retrieval.py) ── langchain FAISS ← 문서 코퍼스
                    → 가드(고지·그라운딩) → Streamlit UI (app.py: 답변 + 차트 + 근거 패널)
```

| 모듈 | 역할 |
|---|---|
| `agent.py` | function-calling 루프, 반환각 가드(`_with_disclaimer`, `_reground`) |
| `tools.py` | 조회 도구 8종 (`get_sector_weights`, `rank_countries_by_sector`, `get_sector_landscape`, `get_industry` 등) |
| `retrieval.py` | `search_concepts` — FAISS 개념 검색 + 오프토픽 컷오프(`MIN_SCORE`) |
| `db.py` / `universe.py` | SQLite 캐시 · 국가/섹터/산업 유니버스·한국어 매핑 |
| `charts.py` | Plotly 차트 + 근거 표 |
| `ingest.py` / `ingest_sectors.py` | yfinance → SQLite 수집 (멱등) |
| `embed_corpus.py` | PDF → 청킹 → Upstage 임베딩 → FAISS 인덱스 |
| `prompts.py` | 시스템 인스트럭션(역할·근거·모름·투자권유 아님) |

## 설치 & 실행

[uv](https://docs.astral.sh/uv/) 사용.

```bash
# 1. 의존성
uv sync

# 2. API 키 (.env)
echo "UPSTAGE_API_KEY=발급받은_키" > .env   # https://console.upstage.ai

# 3. 데이터 수집 (yfinance → SQLite, 멱등)
uv run python -m etf_agent.ingest
uv run python -m etf_agent.ingest_sectors

# 4. RAG 인덱스 빌드 (data/corpus/ 의 PDF 필요 — 저장소엔 미포함)
uv run python -m etf_agent.embed_corpus

# 5. 실행
uv run streamlit run app.py
```

## 테스트 & 평가

```bash
uv run pytest                        # 31 tests
uv run python eval/eval_retrieval.py # RAG 검색 평가 (recall@3 / MRR / category)
```

## 데이터 정책

- **캐시 스냅샷:** 질의 시 네트워크를 치지 않는다. `ingest*`를 일 1회 재실행해 갱신(멱등). 기준일이 7일 초과하면 UI가 경고.
- **저장소 제외:** PDF 코퍼스·SQLite 캐시·FAISS 인덱스는 `.gitignore` 처리(용량·저작권). 위 3·4단계로 재생성한다.
- **RAG 코퍼스:** 국세청/미래에셋/HKEX/금감원/신한/하나로/대신증권 등 공개 자료에서 페이지 선별. 카테고리: `tax`·`concept`·`risk`·`sector`·`strategy`.

## 다루지 않는 것

개별 주식·암호화폐·채권·부동산·시장 전망·매수/매도 판단. 데이터에 없는 질문은 "제공된 데이터에 없습니다"로 답한다. **투자 권유가 아니며 정보 제공 목적이다.**
