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

## RAG 코퍼스 출처

전부 공개 자료에서 **관련 페이지만 선별**해 인덱싱한다(표가 반토막 나지 않게 페이지 단위, 긴 페이지만 분할). 선별 목록은 [`embed_corpus.py`](src/etf_agent/embed_corpus.py)의 `MANIFEST`에 코드로 고정.

| 출처 | 기관 | 카테고리 | 다루는 내용 |
|---|---|---|---|
| 해외주식 양도소득세 안내 | 국세청 | `tax` | 해외 상장 ETF 양도세·기본공제·종합과세 |
| 해외 ETF 세금 국내외 비교 | 미래에셋증권 | `tax` | 국내상장 해외ETF vs 해외상장 ETF, 연금계좌 과세이연 |
| 환헤지 ETF 가이드 | 미래에셋증권 | `concept` | `(H)` 표시 의미, 환헤지 비용 발생 구조 |
| ETF 핸드북 (한글) | HKEX | `concept`·`risk` | 추적오차·괴리율·TER·LP/AP, 레버리지·인버스 위험 |
| ETF 용어 해설 | 금융감독원 | `concept` | 분배금·분배락·총보수 등 기본 용어 |
| 파생상품 ETF 위험고지서 | 신한투자증권 | `risk` | 레버리지·인버스 음의 복리효과 |
| 상장폐지 요건 (일괄신고서) | 하나로 | `risk` | 순자산 미달 등 ETF 상장폐지 조건 |
| ETF Tour Guide ③ 섹터 모멘텀 | 대신증권 | `sector`·`strategy` | GICS 섹터 경기/금리/달러 민감도, 듀얼 모멘텀 전략 |

선별 결과 **69청크** — 카테고리별 `tax` 13 · `concept` 28 · `risk` 9 · `sector` 14 · `strategy` 5.

## 테스트 & 평가

```bash
uv run pytest                        # 31 tests
uv run python eval/eval_retrieval.py # RAG 검색 평가 (recall@k / MRR / category)
uv run python eval/sweep.py          # 청킹·k 파라미터 스윕
```

### 검색 평가 지표 ([`eval/eval_retrieval.py`](eval/eval_retrieval.py))

앱과 **동일한 FAISS 인덱스**를 그대로 호출한다(eval=프로덕션). 골드셋은 22개 질문으로, 용어 구분·위험 vs 개념 경계 같은 어려운 케이스를 일부러 섞었다.

- **recall@k** — 상위 k개 결과 안에 정답 출처 문서가 들어왔는가 (검색 누락 측정).
- **MRR** — 정답 출처가 처음 등장하는 순위의 역수 평균 (1.0 = 항상 1등, 순위 품질 측정).
- **top-1 category** — 1등 결과의 카테고리(`tax`/`concept`/`risk`/`sector`/`strategy`)가 기대와 일치하는가 (라우팅 정확도).

현재: **recall@3 22/22 (100%) · MRR 1.000 · category 22/22 (100%)**.

### 파라미터 스윕 ([`eval/sweep.py`](eval/sweep.py))

과제 요건인 "프롬프트·chunk size·overlap·retrieve(k) 파라미터를 바꿔가며 결과 차이 확인"을 정량화. 골드셋을 재활용해 청킹 파라미터별로 인메모리 FAISS를 재빌드하고 recall/MRR을 뽑는다(프로덕션 인덱스는 건드리지 않음).

| chunk/overlap | #chunks | R@1 | R@3 | R@5 | MRR | cat@1 |
|---|---|---|---|---|---|---|
| 400 / 100 | 169 | 22/22 | 22/22 | 22/22 | 1.000 | 22/22 |
| 700 / 150 | 101 | 22/22 | 22/22 | 22/22 | 1.000 | 22/22 |
| **1000 / 150** (현재) | 69 | 22/22 | 22/22 | 22/22 | 1.000 | 22/22 |
| 1500 / 200 | 54 | 22/22 | 22/22 | 22/22 | 1.000 | 22/22 |

**해석:** 정선된 소규모 코퍼스(8종·69페이지)에서는 각 청크에 `[출처·섹션]` 헤더를 붙여 태깅하므로 **chunk size·overlap·k가 검색 recall을 바꾸지 않는다**(전 구간 100%). 정답이 항상 1등이라 k도 recall엔 무의미하며, k가 실제로 조절하는 건 LLM에 넘기는 맥락의 양(precision)이다. 결과 품질을 실제로 가르는 파라미터는 **오프토픽 거절 임계값 `MIN_SCORE`**로, 정답 통과(≥0.39)와 오프토픽 차단(비트코인 0.27·날씨 0.18)을 모두 만족하는 **0.35로 실측 튜닝**했다([retrieval.py](src/etf_agent/retrieval.py#L11-L14)).

## 데이터 정책

- **캐시 스냅샷:** 질의 시 네트워크를 치지 않는다. `ingest*`를 일 1회 재실행해 갱신(멱등). 기준일이 7일 초과하면 UI가 경고.
- **저장소 제외:** PDF 코퍼스·SQLite 캐시·FAISS 인덱스는 `.gitignore` 처리(용량·저작권). 위 3·4단계로 재생성한다.
- **RAG 코퍼스:** 공개 자료에서 관련 페이지만 선별([출처 표](#rag-코퍼스-출처) 참고).

## 다루지 않는 것

개별 주식·암호화폐·채권·부동산·시장 전망·매수/매도 판단. 데이터에 없는 질문은 "제공된 데이터에 없습니다"로 답한다. **투자 권유가 아니며 정보 제공 목적이다.**
