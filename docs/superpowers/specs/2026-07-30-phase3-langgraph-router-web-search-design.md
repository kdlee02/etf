# Phase 3 — langgraph 라우터 + Tavily 웹검색 폴백

작성일: 2026-07-30 · 상태: 승인됨(설계)

## 목적

오프토픽 질문(코퍼스·데이터 밖)을 tool 루프 앞단의 라우터가 먼저 분류해,
스코프 밖이면 Tavily 웹검색으로 답한다. 부수적으로 기존 `ac4` 증상(오프토픽
질문에 solar가 무관한 도구 `get_sector_weights('XLK')`를 찔러보고 근거 패널에
안 쓰인 수치가 뜨는 것)을 원인째 제거한다 — 오프토픽은 tool 루프에 아예 진입하지 않는다.

## 확정된 결정

- **라우터 구현**: langgraph `StateGraph` (과제의 "프레임워크 활용" 쇼케이스).
  기록상 "프레임워크 추가 안 함" 결정을 이 항목에 한해 뒤집는다.
- **오프토픽 매수/매도 판단("비트코인 살까?") 컴플라이언스**: 사실만 전달 + 고지문구.
  매수/매도 조언 문장은 금지한다. `투자 권유가 아닙니다.` 고지는 그대로 붙인다.
- **Tavily**: 이미 lock된 `requests`로 REST 직접 호출. `tavily-python`/`langchain-tavily`
  의존성은 추가하지 않는다. API 키는 `.env`의 `TAVILEY_API_KEY`(철자 그대로).

## 아키텍처

새 파일 `src/etf_agent/graph.py` — 기존 에이전트를 감싸는 langgraph `StateGraph`.
`ask(question, grounded)` 시그니처는 유지해 `app.py`·eval은 변경하지 않는다.

```
                    ┌─ scoped ─→ [기존 tool 루프] ─┐
question → classify ─┤                              ├─→ END
                    └─ web ────→ [Tavily + 작문] ──┘
```

### State (TypedDict)

- `question: str`
- `grounded: bool`
- `route: str` — `"scoped"` | `"web"`
- `answer: Answer`

### 노드

1. **classify** — solar-pro3 값싼 1콜(temperature 0), 라벨 `scoped` | `web` 하나만
   반환. 닫힌 선택지라 solar 긍정규칙에 강하다. 파싱 실패/미지 라벨 → `scoped`로 폴백
   (안전 쪽 = 기존 동작 유지, 가드가 계속 적용됨).
2. **scoped_agent** — 현재 `ask()`의 tool 루프를 함수(`_run_scoped(question) -> Answer`)로
   추출해 노드화. 동작·가드(`_reground`, `_with_disclaimer`, bare-topic 되묻기) 불변.
3. **web_agent** — `web_search(query)` 호출 → solar가 웹 결과만 근거로 작문.

조건부 엣지: `classify → scoped_agent | web_agent`, 둘 다 → `END`.

`grounded=False`(도구 없음 환각 시연 모드)는 그래프를 우회한다 — 라우팅 불필요.

## 분류 경계

- `scoped` = ETF·국가·섹터 데이터 + ETF 개념/세금/위험/전략(현재 도구가 커버하는 전부)
- `web` = 개별주식·암호화폐·채권·부동산·시장전망·매수매도·시사/일반질문
- 부수효과: 알려진 누수 "미국 기준금리 몇 %"(search_concepts 0.374 오검색)도 이제 web로
  정직하게 라우팅된다.

## Tavily 노드 상세

새 파일 `src/etf_agent/websearch.py`:

- `web_search(query: str) -> dict` — `requests` POST `https://api.tavily.com/search`,
  본문에 `api_key`(=`TAVILEY_API_KEY`) + `query`.
- **절대 raise 하지 않는다**(tools.py 규칙). 실패/키없음/무결과 → `{"found": False, ...}`.
- 성공 → `{"found": True, "query": ..., "results": [{"title","url","content"}, ...]}`.

web_agent 작문:

- 시스템 프롬프트: **웹 결과만 근거·사실만·매수/매도 조언 금지**, 끝에 고지문구.
- 답변 앞에 `🔎 웹에서 검색한 결과입니다` 표기.
- `_with_disclaimer` 적용.
- Tavily 실패 시 → 현재의 정중한 거절("제공된 데이터에 없습니다") + 고지로 우아하게 폴백.
- 웹 결과를 `ToolCall(name="web_search", args={"query":...}, result=...)`로 트레이스에
  넣어 증거 패널이 URL 출처를 그대로 렌더한다(`app.py` 무수정).

## 의존성

- `langgraph` 추가(`pyproject.toml`).
- `requests`(이미 lock, langchain-community 경유) 직접 사용. 신규 tavily 패키지 없음.

## 컴플라이언스 (RFP 요건 유지)

- 웹 답변에도 `_with_disclaimer` 그대로.
- 웹 작문 프롬프트가 매수/매도 조언 문장 금지.
- Tavily 실패 → 거절 폴백으로 "데이터에 없으면 모름" 정신 유지.

## 검증

- **ac4 eval 재작성**: 지금은 "거절"을 0/3으로 잡지만 동작이 웹답변으로 바뀐다.
  새 기대치: (a) 무관 ETF 도구를 찌르지 않음, (b) 고지문구 포함, (c) 웹검색 표기.
- `graph.py __main__` self-check: `classify("비트코인 살까?") == "web"`,
  `classify("한국 ETF 섹터 비중") == "scoped"` (retrieval.py처럼 실 API 호출).
- `websearch` 단위 테스트 1개: `requests`를 mock해 성공/실패 형태 검증(네트워크 없음).
- 기존 테스트 스위트 전부 통과 유지.

## 파일

- 신규: `src/etf_agent/graph.py`, `src/etf_agent/websearch.py`
- 수정: `src/etf_agent/agent.py`(tool 루프 함수 추출 + `ask`가 그래프 호출),
  `pyproject.toml`(langgraph), `src/etf_agent/prompts.py`(웹 작문 프롬프트),
  필요시 `src/etf_agent/charts.py`(web_search 결과 가드), eval의 ac4 케이스
- 무수정: `app.py`

## 스코프 밖 (안 함)

- Tavily를 스코프 내 도구 폴백(도구가 `found:false`일 때)으로 쓰지 않는다 —
  오프토픽 라우팅 전용. 스코프 내는 기존 "데이터에 없음" 거절 유지.
- category 메타필터, 하이브리드 리랭크 등 RAG 고도화는 별개(우선순위 낮음).
