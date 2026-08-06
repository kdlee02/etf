# 📊 ETF 투자 리서치 어시스턴트

국가·섹터·산업 기준으로 ETF를 **실제 데이터**로 조회하고, 개념·세금·위험·전략 질문은 **문서 코퍼스(RAG)**로 답하는 하이브리드 에이전트. 모든 수치는 도구 호출 결과이며, 근거 없는 답변은 하지 않는다. **모든 답변을 도구·코퍼스 근거에 묶어 환각을 원천 차단**하는 것 — 즉 **환각 방지(anti-hallucination)**가 이 프로젝트의 핵심 설계 원칙이다.

> 코멘토 AI SA 부트캠프 프로젝트. Upstage `solar-pro3` + function-calling + langchain FAISS RAG + langgraph 라우터 + Tavily 웹검색.

## 이런 걸 물어봅니다

질문을 langgraph 라우터가 **scoped(도구·RAG) · web · reject** 세 갈래로 분류한다. 각 경로를 한 예시씩. *답변은 예시이며 실제 수치는 캐시 스냅샷에 따라 달라진다.*

**Q. 반도체 섹터 비중이 높은 국가는?** *(scoped — 구조화 조회 `rank_countries_by_sector`)*
> 대만 68.4% · 한국 41.2% · 미국 29.7% … (도구 반환값. 표+막대 차트로 표시)

**Q. 환헤지 ETF의 `(H)`가 무슨 뜻이야?** *(scoped — RAG 인용 `search_concepts`)*
> `(H)`는 환헤지(hedged)를 뜻하며 환율 변동을 상쇄하는 대신 헤지 비용이 발생합니다. **(미래에셋 환헤지 ETF p4)**

**Q. 미국 기준금리 몇 %야?** *(web — 도메인 내 사실이지만 도구·코퍼스에 없음 → Tavily 웹검색)*
> (웹 검색 결과 요약 + 출처 링크. 사실만 전달, 매수/매도 판단은 하지 않음)

**Q. 비트코인 지금 살까?** *(reject — 범위 밖 자산 → 라우터가 거절)*
> 암호화폐 매수/매도 판단은 이 어시스턴트의 범위가 아닙니다. 정보 제공 목적이며 투자 권유가 아닙니다.

## 핵심 특징

- **근거 기반(환각 방지):** 답변의 모든 수치는 도구가 반환한 값만 사용. 도구를 호출하지 않으면 티커·수치를 언급하지 않는다.
- **다방향 조회:** 국가→ETF·종목·섹터, 섹터→ETF·세부산업·대표종목(+국가 순위는 "비중 높은 나라"처럼 명시 요청 시), 산업→대표종목·세부산업·소속섹터.
- **RAG 인용:** 환헤지·양도세·상장폐지·듀얼 모멘텀 등 개념/전략 질문은 코퍼스에서 검색해 `(문서명 p페이지)`로 인용.
- **라우터 + 웹 폴백:** langgraph 라우터가 질문을 scoped/web/reject로 분기. 도구·코퍼스에 없는 도메인 내 사실은 Tavily 웹검색으로 답하고, scoped 경로가 근거를 못 얻으면 web으로 보정한다(CRAG). "근거 0건"의 판정 주체와 폴백마저 실패했을 때의 최종 응답은 [근거 판정 3층](#근거-판정-3층--근거-0건은-누가-정하나) 참고.
- **부정 규칙은 코드로 강제:** 모델이 프롬프트만으론 어기는 규칙(고지 누락, 오프토픽 거절, 티커 환각)을 코드로 잠금 — `_with_disclaimer`, `MIN_SCORE`, `_reground`.

## 아키텍처

```
질문 → route() ─ langgraph 라우터: _classify → scoped / web / reject
  ├─ scoped: function-calling loop (solar-pro3)
  │            ├─ 구조화 도구 (tools.py) ── SQLite 캐시 (db.py) ← yfinance
  │            └─ search_concepts (retrieval.py) ── langchain FAISS ← 문서 코퍼스
  │            └─ 근거 0건이면 web으로 폴백 (CRAG)
  ├─ web: Tavily 웹검색 (websearch.py) — 도구·코퍼스 밖 도메인 사실
  └─ reject: 범위 밖(개별종목·암호화폐·오프도메인) 거절
  → 가드(고지·그라운딩) → Streamlit UI (app.py: 답변 + 차트 + 근거/출처 패널)
```

| 모듈 | 역할 |
|---|---|
| `graph.py` | langgraph 라우터 — `_classify`로 scoped/web/reject 분기 + CRAG 폴백 |
| `agent.py` | function-calling 루프, 환각 방지 가드(`_with_disclaimer`, `_reground`), 웹 답변 노드 |
| `websearch.py` | Tavily 웹검색 래퍼 (도메인 내 사실질문·scoped 폴백, raise 안 함) |
| `tools.py` | 조회 도구 8종 (`get_sector_weights`, `rank_countries_by_sector`, `get_sector_landscape`, `get_industry` 등) |
| `retrieval.py` | `search_concepts` — FAISS 개념 검색 + 오프토픽 컷오프(`MIN_SCORE`) |
| `db.py` / `universe.py` | SQLite 캐시 · 국가/섹터/산업 유니버스·한국어 매핑 |
| `charts.py` | Plotly 차트 + 근거 표 |
| `ingest.py` / `ingest_sectors.py` | yfinance → SQLite 수집 (멱등) |
| `embed_corpus.py` | PDF → 청킹 → Upstage 임베딩 → FAISS 인덱스 |
| `prompts.py` | 시스템 인스트럭션(역할·근거·모름·투자권유 아님) |

### 근거 판정 3층 — "근거 0건"은 누가 정하나

CRAG 폴백의 트리거인 "근거 0건"은 단일 조건이 아니라 3층으로 나뉘고, **각 층이 서로 다른 걸 판정한다**.

| 층 | 위치 | 판정 대상 | 실패 시 |
|---|---|---|---|
| 1차 (값싼 게이트) | `MIN_SCORE = 0.35` [`retrieval.py`](src/etf_agent/retrieval.py#L83) | 벡터 top1 유사도 | `found: False` |
| 2차 (의미 게이트) | `_grade()` [`retrieval.py`](src/etf_agent/retrieval.py#L49) | LLM이 발췌별 실제 관련성 채점 | `found: False` |
| 최종 (라우팅) | `_crag_fallback()` [`graph.py`](src/etf_agent/graph.py#L34) | **툴 트레이스 전체**에 `found: True`가 하나라도 있나 | → `web` 노드 |

최종 판정은 `Answer.has_evidence` [`agent.py`](src/etf_agent/agent.py#L47) 한 줄이다:

```python
return any(c.result and c.result.get("found") for c in self.tool_calls)
```

즉 **`search_concepts` 전용이 아니다.** RAG가 빈손이어도 `rank_countries_by_sector` 같은 구조화 도구가 성공했으면 폴백하지 않는다. 1·2차는 상류 필터고, web으로 넘길지 말지의 결정권은 `_crag_fallback`에 있다.

**알려진 구멍:** `GRADE_BYPASS = 0.50` [`retrieval.py`](src/etf_agent/retrieval.py#L19) 위 구간은 지연 절감을 위해 2차 게이트를 건너뛴다. 따라서 **유사도가 강한 오탐은 어느 층도 거르지 못한다.** 현재 코퍼스(8종·69청크)에선 실측 정답 최고가 0.42라 발생하지 않지만, 코퍼스가 커져 강한 오탐이 생기면 이 상한을 올려야 한다.

### 폴백의 마지막 단계 — web도 실패하면

`web_search`는 절대 raise하지 않고 전부 `found: False`로 수렴한다([`websearch.py`](src/etf_agent/websearch.py)): `TAVILY_API_KEY` 없음 · 네트워크 예외 · 응답 형식 오류 · 결과 0건. 이때 [`_run_web`](src/etf_agent/agent.py#L297)이 모델을 부르지 않고 조기 반환하며, 사용자가 보는 최종 문구는 이것이다:

> 제공된 데이터에 없어 웹에서 찾아봤지만 신뢰할 만한 결과를 얻지 못했습니다.
>
> 투자 권유가 아닙니다.

**여기가 종착점이다** — 재시도하지 않는다. 근거를 못 얻은 상태에서 재시도는 지연만 늘고 모델이 끌어올 새 근거가 없다(`_reground`가 1회로 멈추는 것과 같은 판단). 근거 패널에는 `❌ web_search`가 남아 실패가 눈에 보인다.

### 스트리밍 중 경로 전환

scoped를 스트리밍하다 CRAG 폴백이 걸리면 이미 흘린 미리보기는 버려진다. 이때 [`ask_stream`](src/etf_agent/agent.py#L327)이 `STREAM_RESET` sentinel을 먼저 흘리고, UI는 버퍼를 비운 뒤 전환을 안내한다([`app.py`](app.py#L104)):

> _내부 자료에 근거가 없어 웹 검색으로 보완합니다…_

신호가 없으면 web 답변이 버려질 미리보기 뒤에 이어붙어 화면에 답변이 두 개로 보인다. `_reground` 재작성은 티커 몇 개만 바뀌므로 신호를 보내지 않고, 스트림 종료 후 `Answer.text`로 확정 렌더할 때 교체된다.

## 프롬프트 엔지니어링

시스템 프롬프트([`prompts.py`](src/etf_agent/prompts.py))는 **출력을 통제하는** 기법만 골라 적용했다. 이 프로젝트의 목표가 창의적 생성이 아니라 **사실 조회(환각 방지)**이기 때문.

| 기법 | 적용 | 방식 |
|---|---|---|
| **역할 지정** | ✅ | `"당신은 ETF 투자 리서치 어시스턴트입니다"`로 역할·범위 고정 |
| **형식 지정** | ✅ | 수치는 백분율(0.613→61.3%), 표·목록 유도, 인용은 `(문서명 p페이지)` 형식 강제 |
| **마크다운 구조화** | ✅ | 프롬프트를 `## 절대 규칙`·`## 도구 선택` 소제목으로 구획, 답변도 마크다운 표 유도 |
| **Few-shot (축소판)** | 🔶 | 인용 형식 예시(`(미래에셋 환헤지 ETF p4)`)를 인라인으로 제시 |
| **Chain of Thought** | 🔶 구조로 대체 | "step by step" 문구 대신 **function-calling 루프**가 "도구 호출 → 결과 → 답변" 단계를 강제 |

**의도적으로 배제:** 할루시네이션 유도(목표와 정반대), 멀티 페르소나·이어쓰기(개방형 생성용). 정확도 문구("Let's think step by step")도 미사용 — 모델의 자체 추론이 아니라 **도구 데이터**만 근거로 삼아야 하므로 핵심 지시는 "논리적으로 생각해라"가 아니라 **"먼저 도구를 호출해라"**(규칙 0)다.

프롬프트만으론 못 지키는 규칙(고지·오프토픽 거절·티커 환각)은 [코드 가드](#핵심-특징)로 이중 잠금한다 — 프롬프트는 유도, 코드는 강제.

## 설치 & 실행

[uv](https://docs.astral.sh/uv/) 사용.

```bash
# 1. 의존성
uv sync

# 2. API 키 (.env)
echo "UPSTAGE_API_KEY=발급받은_키" > .env    # https://console.upstage.ai (필수)
echo "TAVILY_API_KEY=발급받은_키" >> .env    # https://tavily.com (web 라우팅용, 없으면 web 경로만 비활성)

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
uv run pytest                        # 52 tests
uv run python eval/eval_retrieval.py # RAG 검색 평가 (recall@k / MRR / category)
uv run python eval/eval_router.py    # 라우터 분류 평가 (false-reject / 혼동행렬)
uv run python eval/sweep.py          # 청킹·k 파라미터 스윕
uv run python eval/run_eval.py       # 라이브 스모크 (네트워크·API 키 필요)
```

검색 품질과 **라우팅 품질**을 같은 수준으로 검증한다. 라우터는 판정 지점이 하나 더 늘어난
곳이라 별도 골드셋을 둔다 — 검색이 아무리 정확해도 질문이 엉뚱한 경로로 가면 소용없다.

### 검색 평가 지표 ([`eval/eval_retrieval.py`](eval/eval_retrieval.py))

앱과 **동일한 FAISS 인덱스**를 그대로 호출한다(eval=프로덕션). 골드셋은 22개 질문으로, 용어 구분·위험 vs 개념 경계 같은 어려운 케이스를 일부러 섞었다.

- **recall@k** — 상위 k개 결과 안에 정답 출처 문서가 들어왔는가 (검색 누락 측정).
- **MRR** — 정답 출처가 처음 등장하는 순위의 역수 평균 (1.0 = 항상 1등, 순위 품질 측정).
- **top-1 category** — 1등 결과의 카테고리(`tax`/`concept`/`risk`/`sector`/`strategy`)가 기대와 일치하는가 (라우팅 정확도).

현재: **recall@3 22/22 (100%) · MRR 1.000 · category 22/22 (100%)**.

### 라우터 분류 평가 ([`eval/eval_router.py`](eval/eval_router.py))

앱과 **동일한 `_classify`**를 그대로 호출한다(eval=프로덕션). 골드셋 25문항(scoped 13 · web 5 ·
reject 7)에 경계 케이스를 일부러 섞었다 — 투자 의도 말투인데 주제가 국가/섹터라 scoped인 질문,
도메인 안이지만 코퍼스 밖이라 web인 질문.

- **false-reject** — 답할 수 있는 질문(scoped/web)을 reject로 보낸 비율. **1급 지표**다.
- **false-accept** — 범위 밖 질문을 통과시킨 비율.
- **혼동행렬** — 3×3. scoped↔web 오분류는 CRAG가 사후 보정하므로 false-reject보다 덜 아프다.

셋을 같은 무게로 보지 않는 이유: scoped로 잘못 가도 근거 0건이면 web으로 넘어가지만,
reject는 되돌릴 길이 없다. 사용자는 기능이 없다고 판단하고 떠난다.

현재 (3회 반복 · 75판정): **정확도 75/75 (100%) · false-reject 0% · false-accept 0% · 편차 0**

|기대\실제| reject | scoped | web |
|---|---|---|---|
| **scoped** | 0 | 39 | 0 |
| **web** | 0 | 0 | 15 |
| **reject** | 21 | 0 | 0 |

### 도구 루프 상한 실측 ([`eval/run_eval.py`](eval/run_eval.py))

`MAX_TOOL_ROUNDS = 5`가 적절한 여유인지 라이브 스모크의 INFO 로그로 확인한다.

```bash
uv run python eval/run_eval.py --runs 3 2>&1 | grep "tool-call rounds"
```

실측 (7세션 · scoped 케이스 21관측): **1라운드 7 · 2라운드 1 · 3라운드 11 · 소진 2 (9.5%)**

소진해도 마지막 강제 답변 라운드가 받아내 **21/21 정답**이었다. 그래서 5를 유지한다 —
소진 시 오답이 관측되면 그때 올린다. 상한은 폭주 방지용이지 성능 파라미터가 아니라,
근거 없이 올리면 최악의 경우 지연·비용만 늘어난다.

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

## 변경 이력

회차별 피드백과 그 대응은 [`CHANGELOG.md`](CHANGELOG.md)에 지적 한 줄 · 대응 한 줄 · 커밋 해시로
기록한다. 미대응 항목도 **미대응**으로 남긴다 — 안 한 것도 이력이다.

## 다루지 않는 것

개별 주식·암호화폐·채권·부동산·시장 전망·매수/매도 판단. 데이터에 없는 질문은 "제공된 데이터에 없습니다"로 답한다. **투자 권유가 아니며 정보 제공 목적이다.**
